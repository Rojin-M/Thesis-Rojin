"""Durable bounded watcher accounting. SQLite transactions + one local flock.

Reservations remain charged at their full cap after a hard crash: unknown
network usage must never become a free retry. Completed receipts never mutate.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import uuid

from .protocol import ConflictError, ValidationError, canonical_json, digest, utc_now
from .store import _one, _rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_configs (
 id TEXT PRIMARY KEY, config_json TEXT NOT NULL, created_at TEXT NOT NULL,
 failures INTEGER NOT NULL DEFAULT 0, last_poll_at TEXT, last_success_at TEXT,
 next_poll_at TEXT, last_error_json TEXT, heartbeat_at TEXT, service_state TEXT NOT NULL DEFAULT 'stopped');
CREATE TABLE IF NOT EXISTS watch_polls (
 id TEXT PRIMARY KEY, config_id TEXT NOT NULL REFERENCES watch_configs(id),
 started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
 result_json TEXT, error_json TEXT);
CREATE TABLE IF NOT EXISTS watch_snapshots (
 id TEXT PRIMARY KEY, poll_id TEXT NOT NULL REFERENCES watch_polls(id),
 provenance_id TEXT NOT NULL REFERENCES provenance(id), path TEXT NOT NULL,
 request_json TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, retrieved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watch_seen (
 poll_id TEXT NOT NULL REFERENCES watch_polls(id), product_id TEXT NOT NULL REFERENCES products(id),
 PRIMARY KEY(poll_id,product_id));
CREATE TABLE IF NOT EXISTS watch_budget (
 id INTEGER PRIMARY KEY CHECK(id=1), cap INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS watch_spending (
 id TEXT PRIMARY KEY, operation_key TEXT UNIQUE, kind TEXT NOT NULL, pilot_id TEXT,
 cap INTEGER NOT NULL CHECK(cap>=0), used INTEGER CHECK(used>=0 AND used<=cap),
 status TEXT NOT NULL, receipt_json TEXT, created_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS watch_pilots (
 id TEXT PRIMARY KEY, spec_json TEXT NOT NULL, created_at TEXT NOT NULL,
 runtime_charged REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued');
CREATE TABLE IF NOT EXISTS watch_queue (
 product_id TEXT PRIMARY KEY REFERENCES products(id), pilot_id TEXT NOT NULL REFERENCES watch_pilots(id),
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,
 receipt_json TEXT, job_id TEXT REFERENCES jobs(id), error_json TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watch_dispatches (
 id TEXT PRIMARY KEY, pilot_id TEXT NOT NULL REFERENCES watch_pilots(id),
 started_at TEXT NOT NULL, finished_at TEXT, reserved_seconds REAL NOT NULL, used_seconds REAL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watch_automation (
 id INTEGER PRIMARY KEY CHECK(id=1), config_id TEXT NOT NULL, config_json TEXT NOT NULL,
 service_state TEXT NOT NULL, phase TEXT NOT NULL, heartbeat_at TEXT NOT NULL,
 last_cycle_json TEXT, last_error_json TEXT);
CREATE TABLE IF NOT EXISTS watch_check_requests (
 id TEXT PRIMARY KEY, config_id TEXT NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, result_json TEXT, error_json TEXT);
CREATE TABLE IF NOT EXISTS watch_catalog_checks (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), checked_at TEXT NOT NULL, result_json TEXT NOT NULL);
"""
UNSET = object()


def _automation_status(db):
    row = db.execute('SELECT * FROM watch_automation WHERE id=1').fetchone()
    if row is None:
        return {'enabled': False, 'service_state': 'stopped', 'phase': 'waiting',
                'heartbeat_at': None, 'config_id': None, 'targets': [], 'cohort': None,
                'check_request': None, 'last_cycle': None, 'last_error': None}
    record = _one(db, 'SELECT * FROM watch_automation WHERE id=1', ())
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(record['heartbeat_at'].replace('Z', '+00:00'))).total_seconds()
    health = 'stale' if record['service_state'] == 'running' and age > 120 else record['service_state']
    requests = _rows(db, 'SELECT * FROM watch_check_requests WHERE config_id=? ORDER BY created_at DESC LIMIT 1',
                     (record['config_id'],))
    discovery = None
    targets = record['config']['targets']
    if record['config'].get('schema_version') == 2:
        cycle = record['last_cycle'] or {}
        discovery = cycle.get('discovery') or {'status': 'waiting', 'targets': [], 'new_targets': [],
                                               'errors': [], 'archive_wide_complete': False}
        targets = cycle.get('targets', targets)
    return {'enabled': True, 'service_state': health, 'phase': record['phase'],
            'heartbeat_at': record['heartbeat_at'], 'config_id': record['config_id'],
            'targets': targets, 'cohort': record['config']['cohort'], 'discovery': discovery,
            'config': record['config'], 'check_request': requests[0] if requests else None,
            'last_cycle': record['last_cycle'], 'last_error': record['last_error']}


def later(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec='microseconds').replace('+00:00', 'Z')


@contextmanager
def exclusive_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConflictError('Another watcher/dispatcher owns this database lock') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class WatchStore:
    def __init__(self, store):
        self.store = store
        self.lock_path = store.path.with_suffix('.watch.lock')

    def initialize(self):
        # Called by Store.initialize too, so the HTTP reader needs no migrations.
        with self.store.connection(True) as db:
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    db.execute(statement)
            db.execute('INSERT OR IGNORE INTO watch_budget(id,cap) VALUES(1,?)', (2 * 1024**3,))
        return self

    def config(self, config):
        key = digest(config)
        with self.store.connection(True) as db:
            db.execute('INSERT OR IGNORE INTO watch_configs(id,config_json,created_at) VALUES(?,?,?)',
                       (key, canonical_json(config), utc_now()))
            return _one(db, 'SELECT * FROM watch_configs WHERE id=?', (key,))

    def begin_poll(self, config_id, interval, force=False):
        now = utc_now()
        with self.store.connection(True) as db:
            c = _one(db, 'SELECT * FROM watch_configs WHERE id=?', (config_id,))
            # Lock ownership proves the previous poll cannot still be executing.
            abandoned = {'code': 'InterruptedPoll', 'message': 'Previous poll ended without a receipt', 'retryable': True}
            unfinished = _rows(db, "SELECT * FROM watch_polls WHERE status='running'")
            for poll in unfinished:
                db.execute('UPDATE watch_configs SET failures=failures+1,last_error_json=? WHERE id=?',
                           (canonical_json(abandoned), poll['config_id']))
            db.execute("UPDATE watch_polls SET status='interrupted',finished_at=?,error_json=? WHERE status='running'",
                       (now, canonical_json(abandoned)))
            c = _one(db, 'SELECT * FROM watch_configs WHERE id=?', (config_id,))
            # Return a persisted circuit state instead of raising inside this
            # transaction (which would roll back interrupted-poll accounting).
            if c['failures'] >= 3:
                return {'status':'circuit_open','config_id':config_id}
            if not force and c['next_poll_at'] and c['next_poll_at'] > now:
                return None
            key = uuid.uuid4().hex
            db.execute("INSERT INTO watch_polls(id,config_id,started_at,status) VALUES(?,?,?,'running')", (key, config_id, now))
            db.execute('UPDATE watch_configs SET last_poll_at=?,heartbeat_at=?,next_poll_at=? WHERE id=?',
                       (now, now, later(interval), config_id))
            return key

    def finish_poll(self, key, interval, result=None, error=None):
        with self.store.connection(True) as db:
            poll = _one(db, 'SELECT * FROM watch_polls WHERE id=?', (key,))
            c = _one(db, 'SELECT * FROM watch_configs WHERE id=?', (poll['config_id'],))
            failures = c['failures'] + 1 if error else 0
            delay = min(86400, interval * 2 ** min(failures, 3))
            db.execute('UPDATE watch_polls SET status=?,finished_at=?,result_json=?,error_json=? WHERE id=?',
                ('failed' if error else 'succeeded', utc_now(), canonical_json(result), canonical_json(error), key))
            db.execute('UPDATE watch_configs SET failures=?,last_error_json=?,next_poll_at=?,heartbeat_at=?,last_success_at=COALESCE(?,last_success_at) WHERE id=?',
                (failures, canonical_json(error), later(delay), utc_now(), None if error else utc_now(), c['id']))

    def service(self, config_id, state):
        with self.store.connection(True) as db:
            db.execute('UPDATE watch_configs SET service_state=?,heartbeat_at=? WHERE id=?', (state, utc_now(), config_id))

    def start_automation(self, config):
        config_id = digest(config)
        with self.store.connection(True) as db:
            now = utc_now()
            changed = canonical_json({'code': 'ConfigurationChanged', 'message': 'Watchlist changed before request execution'})
            db.execute("UPDATE watch_check_requests SET status='failed',finished_at=?,error_json=? "
                       "WHERE config_id<>? AND status IN ('queued','running')", (now, changed, config_id))
            db.execute("UPDATE watch_check_requests SET status='queued',started_at=NULL "
                       "WHERE config_id=? AND status='running'", (config_id,))
            db.execute("INSERT INTO watch_automation(id,config_id,config_json,service_state,phase,heartbeat_at) "
                       "VALUES(1,?,?,'running','waiting',?) ON CONFLICT(id) DO UPDATE SET "
                       "last_cycle_json=CASE WHEN watch_automation.config_id=excluded.config_id THEN watch_automation.last_cycle_json ELSE NULL END,"
                       "config_id=excluded.config_id,config_json=excluded.config_json,service_state='running',"
                       "phase='waiting',heartbeat_at=excluded.heartbeat_at,last_error_json=NULL",
                       (config_id, canonical_json(config), now))
            return _automation_status(db)

    def automation_update(self, *, phase=None, state=None, result=None, error=UNSET):
        if phase is not None and phase not in ('waiting', 'polling', 'processing', 'paused', 'error'):
            raise ValidationError('Invalid automatic watcher phase')
        if state is not None and state not in ('running', 'stopped'):
            raise ValidationError('Invalid automatic watcher service state')
        values = {'heartbeat_at': utc_now()}
        if phase is not None:
            values['phase'] = phase
        if state is not None:
            values['service_state'] = state
        if result is not None:
            values['last_cycle_json'] = canonical_json(result)
        if error is not UNSET:
            values['last_error_json'] = canonical_json(error)
        with self.store.connection(True) as db:
            db.execute('UPDATE watch_automation SET ' + ','.join(name + '=?' for name in values) + ' WHERE id=1',
                       tuple(values.values()))

    def request_check(self):
        with self.store.connection(True) as db:
            runtime = _automation_status(db)
            if runtime['service_state'] != 'running':
                raise ConflictError('Automatic watcher is not running; start the watch-auto-serve service first')
            pending = _rows(db, "SELECT * FROM watch_check_requests WHERE config_id=? AND status IN ('queued','running') "
                               'ORDER BY created_at LIMIT 1', (runtime['config_id'],))
            if pending:
                return pending[0]
            previous = runtime['check_request']
            if previous and previous['created_at'] > later(-30):
                raise ConflictError('A check was just requested; wait 30 seconds before requesting another')
            request_id = uuid.uuid4().hex
            db.execute("INSERT INTO watch_check_requests(id,config_id,status,created_at) VALUES(?,?,'queued',?)",
                       (request_id, runtime['config_id'], utc_now()))
            return _one(db, 'SELECT * FROM watch_check_requests WHERE id=?', (request_id,))

    def claim_check(self):
        with self.store.connection(True) as db:
            runtime = _automation_status(db)
            requests = _rows(db, "SELECT * FROM watch_check_requests WHERE config_id=? AND status='queued' "
                                'ORDER BY created_at LIMIT 1', (runtime['config_id'],))
            if not requests:
                return None
            request_id = requests[0]['id']
            db.execute("UPDATE watch_check_requests SET status='running',started_at=? WHERE id=?", (utc_now(), request_id))
            return _one(db, 'SELECT * FROM watch_check_requests WHERE id=?', (request_id,))

    def finish_check(self, request_id, result=None, error=None):
        with self.store.connection(True) as db:
            db.execute('UPDATE watch_check_requests SET status=?,finished_at=?,result_json=?,error_json=? WHERE id=?',
                       ('failed' if error else 'succeeded', utc_now(), canonical_json(result), canonical_json(error), request_id))

    def reset(self, config_id):
        with self.store.connection(True) as db:
            _one(db, 'SELECT * FROM watch_configs WHERE id=?', (config_id,))
            db.execute('UPDATE watch_configs SET failures=0,next_poll_at=NULL WHERE id=?', (config_id,))
            self.store._event(db, 'watcher_circuit_reset', {'config_id': config_id})

    def reserve(self, cap, kind, pilot_id=None, operation_key=None):
        if type(cap) is not int or cap < 0:
            raise ValidationError('Byte reservation must be a nonnegative integer')
        with self.store.connection(True) as db:
            if operation_key:
                old = db.execute('SELECT * FROM watch_spending WHERE operation_key=?', (operation_key,)).fetchone()
                if old:
                    if old['cap'] != cap or old['kind'] != kind:
                        raise ConflictError('Accounting identity changed')
                    return old['id']
            total = db.execute('SELECT COALESCE(SUM(COALESCE(used,cap)),0) FROM watch_spending').fetchone()[0]
            limit = db.execute('SELECT cap FROM watch_budget WHERE id=1').fetchone()[0]
            if total + cap > limit:
                raise ValidationError('Cumulative 2 GiB network budget exhausted, including outstanding reservations')
            if pilot_id:
                pilot = _one(db, 'SELECT * FROM watch_pilots WHERE id=?', (pilot_id,))
                used = db.execute('SELECT COALESCE(SUM(COALESCE(used,cap)),0) FROM watch_spending WHERE pilot_id=?', (pilot_id,)).fetchone()[0]
                if used + cap > pilot['spec']['max_bytes']:
                    raise ValidationError('Pilot cumulative byte budget exhausted')
            key = uuid.uuid4().hex
            db.execute("INSERT INTO watch_spending(id,operation_key,kind,pilot_id,cap,status,created_at) VALUES(?,?,?,?,?,'reserved',?)",
                       (key, operation_key, kind, pilot_id, cap, utc_now()))
            return key

    def settle(self, key, used, receipt, status='complete'):
        with self.store.connection(True) as db:
            row = _one(db, 'SELECT * FROM watch_spending WHERE id=?', (key,))
            if row['used'] is not None:
                if row['used'] != used or row['receipt'] != receipt:
                    raise ConflictError('Transfer receipt is immutable')
                return
            if type(used) is not int or not 0 <= used <= row['cap']:
                raise ValidationError('Transfer exceeded its reservation')
            db.execute('UPDATE watch_spending SET used=?,status=?,receipt_json=?,finished_at=? WHERE id=?',
                       (used, status, canonical_json(receipt), utc_now(), key))

    def account(self, key, amount, reason):
        identity = self.reserve(amount, 'prior_usage', operation_key=key)
        self.settle(identity, amount, {'reason': reason})
        return identity

    def snapshot(self, poll_id, request, payload, root):
        import hashlib
        sha = hashlib.sha256(payload).hexdigest()
        path = Path(root) / 'metadata' / (sha + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != payload:
            raise ConflictError('Stored metadata checksum changed')
        if not path.exists():
            with path.open('xb') as handle:
                handle.write(payload)
        now = utc_now()
        prov = self.store.register_provenance(kind='public_metadata', identity='MAST:' + digest(request),
            sha256_digest=sha, retrieved_at=now, details={'request': request, 'path': str(path.resolve()),
                'size_bytes': len(payload), 'source': 'https://mast.stsci.edu/api/v0/invoke'})
        with self.store.connection(True) as db:
            db.execute('INSERT INTO watch_snapshots VALUES(?,?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, poll_id, prov['id'], str(path.resolve()), canonical_json(request), sha, len(payload), now))
        return prov['id']

    def pilot(self, pilot_id, spec):
        with self.store.connection(True) as db:
            old = db.execute('SELECT * FROM watch_pilots WHERE id=?', (pilot_id,)).fetchone()
            if old:
                if json.loads(old['spec_json']) != spec:
                    raise ConflictError('Pilot selection/settings are frozen; do not change an existing pilot')
                return _one(db, 'SELECT * FROM watch_pilots WHERE id=?', (pilot_id,))
            products = spec['product_ids']
            all_selected = db.execute('SELECT count(*) FROM watch_queue').fetchone()[0]
            targets = {r[0] for r in db.execute('SELECT DISTINCT p.target_id FROM watch_queue q JOIN products p ON p.id=q.product_id')}
            for pid in products:
                product = _one(db, 'SELECT * FROM products WHERE id=?', (pid,))
                targets.add(product['target_id'])
                if db.execute('SELECT 1 FROM watch_queue WHERE product_id=?', (pid,)).fetchone():
                    raise ConflictError('Product already belongs to a pilot; resume that pilot')
            if all_selected + len(products) > 20 or len(targets) > 20:
                raise ValidationError('Cumulative initial selection cap is 20 products / 20 targets')
            db.execute('INSERT INTO watch_pilots(id,spec_json,created_at) VALUES(?,?,?)', (pilot_id, canonical_json(spec), utc_now()))
            for pid in products:
                db.execute("INSERT INTO watch_queue(product_id,pilot_id,state,updated_at) VALUES(?,?,'queued',?)", (pid,pilot_id,utc_now()))
            return _one(db, 'SELECT * FROM watch_pilots WHERE id=?', (pilot_id,))

    def queue(self, product_id, **values):
        allowed = {'state', 'attempts', 'next_attempt_at', 'receipt', 'job_id', 'error'}
        if not values or set(values) - allowed:
            raise ValidationError('Invalid queue update')
        fields = {(k + '_json' if k in ('receipt','error') else k): canonical_json(v) if k in ('receipt','error') else v for k,v in values.items()}
        fields['updated_at'] = utc_now()
        with self.store.connection(True) as db:
            db.execute('UPDATE watch_queue SET ' + ','.join(k+'=?' for k in fields) + ' WHERE product_id=?', (*fields.values(), product_id))

    def dispatch_start(self, pilot_id):
        with self.store.connection(True) as db:
            pilot = _one(db, 'SELECT * FROM watch_pilots WHERE id=?', (pilot_id,))
            remaining = pilot['spec']['max_seconds'] - pilot['runtime_charged']
            if remaining < 1:
                raise ValidationError('Cumulative pilot runtime exhausted; an interrupted reservation remains charged')
            # One invocation owns at most ten minutes. A hard crash charges that
            # slice, leaving any larger cumulative pilot allowance resumable.
            remaining = min(remaining, 600)
            db.execute("UPDATE watch_dispatches SET status='interrupted',finished_at=? WHERE status='running'", (utc_now(),))
            key = uuid.uuid4().hex
            db.execute("INSERT INTO watch_dispatches(id,pilot_id,started_at,reserved_seconds,status) VALUES(?,?,?,?,'running')", (key,pilot_id,utc_now(),remaining))
            db.execute("UPDATE watch_pilots SET runtime_charged=runtime_charged+?,status='running' WHERE id=?", (remaining,pilot_id))
            return key, remaining

    def dispatch_finish(self, key, elapsed, state):
        with self.store.connection(True) as db:
            run = _one(db, 'SELECT * FROM watch_dispatches WHERE id=?', (key,))
            used = min(run['reserved_seconds'], elapsed)
            db.execute('UPDATE watch_dispatches SET used_seconds=?,finished_at=?,status=? WHERE id=?', (used,utc_now(),state,key))
            db.execute('UPDATE watch_pilots SET runtime_charged=runtime_charged-?+?,status=? WHERE id=?', (run['reserved_seconds'],used,state,run['pilot_id']))


def status(store):
    with store.connection() as db:
        configs = _rows(db, 'SELECT * FROM watch_configs ORDER BY created_at DESC LIMIT 20')
        now = utc_now()
        automation = _automation_status(db)
        automatic_ids = set()
        if automation['enabled']:
            from .automation import metadata_configs
            effective_config = dict(automation['config'], targets=automation['targets'])
            automatic_ids = {digest(config) for config in metadata_configs(effective_config)}
            if automation['config'].get('schema_version') == 2:
                from .discovery import discovery_config
                automatic_ids.add(digest(discovery_config(automation['config']['discovery'])))
        for c in configs:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(c['heartbeat_at'].replace('Z','+00:00'))).total_seconds() if c['heartbeat_at'] else None
            c['health'] = 'circuit_open' if c['failures'] >= 3 else ('stale' if c['service_state'] == 'running' and (age is None or age > 120) else c['service_state'])
            c['scheduler'] = {'kind': 'metadata_only', 'heartbeat_at': c['heartbeat_at']}
            if c['id'] in automatic_ids and not (c['health'] == 'running' and automation['service_state'] != 'running'):
                c['scheduler'] = {'kind': 'automatic', 'heartbeat_at': automation['heartbeat_at']}
                if c['failures'] < 3:
                    c['health'] = automation['service_state']
        charged = db.execute('SELECT COALESCE(SUM(COALESCE(used,cap)),0) FROM watch_spending').fetchone()[0]
        cap = db.execute('SELECT cap FROM watch_budget WHERE id=1').fetchone()[0]
        return {'configs': configs, 'polls': _rows(db, 'SELECT * FROM watch_polls ORDER BY started_at DESC LIMIT 20'),
            'pilots': _rows(db, 'SELECT * FROM watch_pilots ORDER BY created_at DESC LIMIT 20'),
            'queue': _rows(db, 'SELECT q.*,p.target_id,p.product_key,p.metadata_json FROM watch_queue q JOIN products p ON p.id=q.product_id ORDER BY q.updated_at DESC LIMIT 20'),
            'budget': {'cap_bytes': cap, 'charged_bytes': charged, 'remaining_bytes': cap-charged,
                'unsettled_reservations': db.execute("SELECT count(*) FROM watch_spending WHERE used IS NULL").fetchone()[0],
                'by_kind': {r[0]:r[1] for r in db.execute('SELECT kind,SUM(COALESCE(used,cap)) FROM watch_spending GROUP BY kind')}},
            'automation': automation,
            'mode': 'automatic_watchlist' if automation['enabled'] else 'metadata_only_unless_explicit_frozen_pilot', 'observed_at': now,
            'scope': ('New-to-project TICs selected from bounded recent public SPOC metadata samples; not archive-wide completeness'
                      if automation.get('discovery') is not None else
                      'Selected TICs and bounded latest SPOC light-curve observations; not archive-wide completeness')}
