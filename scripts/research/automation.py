"""Persistent watchlist processing with durable requests and cumulative budgets."""
import json
import logging
import math
from pathlib import Path
import signal
import threading
import time

from . import mast
from .protocol import ROOT, ConflictError, ValidationError, canonical_json, utc_now
from .store import _one, _rows
from .watcher import create_pilot, dispatch, poll_once, process_product
from .watcher_store import WatchStore, exclusive_lock, later, status

LOG = logging.getLogger(__name__)
DEFAULT_CONFIG = ROOT / 'configs/research_automation_v1.json'


def validate_config(value):
    required = {'schema_version', 'targets', 'poll_seconds', 'poll_max_seconds', 'cohort',
                'product_max_bytes', 'product_max_seconds', 'max_products_per_cycle',
                'cycle_max_seconds', 'catalog_mode'}
    if not isinstance(value, dict) or set(value) != required or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValidationError('Automatic watcher requires exactly the documented schema_version=1 settings')
    targets = value['targets']
    if (not isinstance(targets, list) or not 1 <= len(targets) <= 20
            or any(not isinstance(target, str) or not target.isascii() or not target.isdigit()
                   or not 0 < int(target) < 10**16 or str(int(target)) != target for target in targets)
            or len(set(targets)) != len(targets)):
        raise ValidationError('Configure 1–20 distinct numeric TIC IDs without leading zeros')
    for name, lower, upper in [('poll_seconds', 3600, 86400), ('poll_max_seconds', 1, 180),
                               ('product_max_bytes', 1, 64 * 1024**2), ('product_max_seconds', 1, 7200),
                               ('max_products_per_cycle', 1, 2), ('cycle_max_seconds', 1, 3600)]:
        if type(value[name]) is not int or not lower <= value[name] <= upper:
            raise ValidationError('Invalid automatic watcher bound: ' + name)
    if value['cohort'] not in ('known_object_control', 'archival_pilot'):
        raise ValidationError('Choose known_object_control or archival_pilot; scientific prospective readiness is not established')
    if value['catalog_mode'] not in ('live', 'offline'):
        raise ValidationError('Catalog mode must be live or offline')
    return json.loads(canonical_json(value))


def load_config(path=DEFAULT_CONFIG):
    return validate_config(json.loads(Path(path).read_text()))


def metadata_configs(config):
    return [{'version': 1, 'targets': config['targets'][offset:offset + 2],
             'max_products_per_poll': 2, 'poll_seconds': config['poll_seconds'],
             'poll_max_seconds': config['poll_max_seconds'], 'metadata_only': True}
            for offset in range(0, len(config['targets']), 2)]


def _error(exc):
    return {'code': type(exc).__name__, 'message': str(exc)[:1900] or type(exc).__name__}


def _retry_due(queue, pilot):
    return (queue['state'] != 'complete' and queue['attempts'] < 3
            and (not queue['error'] or queue['error'].get('retryable'))
            and (not queue['next_attempt_at'] or queue['next_attempt_at'] <= utc_now())
            and pilot['spec']['max_seconds'] - pilot['runtime_charged'] >= 1)


def _refresh_catalogs(store, artifacts, job_id):
    from .vetting_worker import refresh_registry
    with store.connection() as db:
        previous = db.execute('SELECT checked_at,result_json FROM watch_catalog_checks WHERE job_id=?', (job_id,)).fetchone()
        if previous and previous['checked_at'] > later(-24 * 3600):
            return json.loads(previous['result_json'])
        candidate_ids = [row[0] for row in db.execute('SELECT id FROM candidates WHERE job_id=?', (job_id,))]
    if not candidate_ids:
        return {'outcomes': [], 'downloaded_bytes_known': 0}
    ledger = WatchStore(store)
    cap = 64 * 1024**2
    reservation = ledger.reserve(cap, 'catalog_refresh')
    try:
        result = refresh_registry(store, artifacts, candidate_ids, mode='live')
        used = cap if result['download_byte_counts_incomplete'] else result['downloaded_bytes_known']
        ledger.settle(reservation, used, {'job_id': job_id, 'incomplete_byte_counts': result['download_byte_counts_incomplete']})
    except Exception as exc:
        ledger.settle(reservation, cap, {'job_id': job_id, 'error': _error(exc)}, 'failed_conservative')
        with store.connection(True) as db:
            db.execute('INSERT INTO watch_catalog_checks(job_id,checked_at,result_json) VALUES(?,?,?) '
                       'ON CONFLICT(job_id) DO UPDATE SET checked_at=excluded.checked_at,result_json=excluded.result_json',
                       (job_id, utc_now(), canonical_json({'error': _error(exc),
                                                          'downloaded_bytes_known': None,
                                                          'download_byte_counts_incomplete': True})))
        raise
    with store.connection(True) as db:
        db.execute('INSERT INTO watch_catalog_checks(job_id,checked_at,result_json) VALUES(?,?,?) '
                   'ON CONFLICT(job_id) DO UPDATE SET checked_at=excluded.checked_at,result_json=excluded.result_json',
                   (job_id, utc_now(), canonical_json(result)))
    return result


def run_cycle(store, artifacts, protocol_id, config, *, client=None, processor=process_product, force=False, max_seconds=None):
    config = validate_config(config)
    allowance = min(config['cycle_max_seconds'], max_seconds) if max_seconds is not None else config['cycle_max_seconds']
    deadline = time.monotonic() + allowance

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError('Automatic watcher cycle reached its wall-clock budget')
        return seconds

    ledger = WatchStore(store)
    result = {'status': 'succeeded', 'started_at': utc_now(), 'targets': config['targets'],
              'polls': [], 'new_product_ids': [], 'selected_product_ids': [],
              'dispatches': [], 'catalog_checks': [], 'errors': [], 'new_candidates': 0}
    with store.connection() as db:
        initial_count = db.execute('SELECT count(*) FROM candidates').fetchone()[0]
    observed = []
    try:
        with mast.wall_deadline(remaining()):
            ledger.automation_update(phase='polling', error=None)
            for metadata_config in metadata_configs(config):
                remaining()
                config_record = ledger.config(metadata_config)
                try:
                    poll = poll_once(store, metadata_config, client=client, force=force)
                    remaining()
                    result['polls'].append(poll)
                    if poll['status'] == 'failed':
                        result['errors'].append(poll['error'])
                        continue
                    if poll['status'] == 'not_due':
                        with store.connection() as db:
                            previous = db.execute("SELECT result_json FROM watch_polls WHERE config_id=? AND status='succeeded' "
                                                  'ORDER BY started_at DESC LIMIT 1', (config_record['id'],)).fetchone()
                        poll = json.loads(previous[0]) if previous else {}
                    if poll.get('status') == 'succeeded':
                        if not poll.get('metadata_pages_complete') or poll.get('selection_truncated'):
                            result['errors'].append({'code': 'IncompleteMetadata',
                                                     'message': 'Archive response was truncated; this batch was not queued'})
                            continue
                        observed.extend(poll['product_ids'])
                        result['new_product_ids'].extend(poll.get('new_product_ids', []) if result['polls'][-1]['status'] != 'not_due' else [])
                except (OSError, ValueError, LookupError) as exc:
                    result['errors'].append(_error(exc))

            remaining()
            ledger.automation_update(phase='processing')
            remaining_slots = config['max_products_per_cycle']
            for product_id in dict.fromkeys(observed):
                remaining()
                with store.connection() as db:
                    queued = db.execute('SELECT product_id FROM watch_queue WHERE product_id=?', (product_id,)).fetchone()
                if queued:
                    continue
                if remaining_slots <= 0:
                    break
                try:
                    create_pilot(store, protocol_id, pilot_id='auto-v1:' + product_id, product_ids=[product_id],
                                 cohort=config['cohort'], max_bytes=config['product_max_bytes'],
                                 max_seconds=config['product_max_seconds'])
                    result['selected_product_ids'].append(product_id)
                    remaining_slots -= 1
                except (OSError, ValueError, LookupError) as exc:
                    result['errors'].append(_error(exc))

            with store.connection() as db:
                queue = _rows(db, 'SELECT q.*,p.target_id FROM watch_queue q JOIN products p ON p.id=q.product_id '
                                 'ORDER BY q.updated_at,q.product_id')
                pilots = {pilot['id']: pilot for pilot in _rows(db, 'SELECT * FROM watch_pilots')}
            executed = 0
            for queued in queue:
                remaining()
                pilot = pilots[queued['pilot_id']]
                if not pilot['id'].startswith('auto-v1:') or queued['target_id'] not in config['targets']:
                    continue
                if not _retry_due(queued, pilot):
                    if queued['state'] != 'complete' and (
                            queued['attempts'] >= 3 or pilot['runtime_charged'] >= pilot['spec']['max_seconds']
                            or (queued['error'] and not queued['error'].get('retryable'))):
                        result['errors'].append({'code': 'ProcessingNeedsAttention', 'pilot_id': pilot['id'],
                                                 'message': queued['error']['message'] if queued['error'] else 'Product runtime allowance exhausted'})
                    continue
                if executed >= config['max_products_per_cycle']:
                    break
                executed += 1
                try:
                    outcome = dispatch(store, artifacts, pilot['id'], client=client, processor=processor)
                    result['dispatches'].append(outcome)
                    remaining()
                    if outcome['status'] != 'complete':
                        result['errors'].append({'code': 'ProcessingIncomplete',
                                                 'message': 'Product processing is ' + outcome['status'], 'pilot_id': pilot['id']})
                except (OSError, ValueError, LookupError) as exc:
                    result['errors'].append(_error(exc))

            if config['catalog_mode'] == 'live':
                remaining()
                with store.connection() as db:
                    complete = _rows(db, "SELECT q.job_id,p.target_id FROM watch_queue q JOIN products p ON p.id=q.product_id "
                                        "WHERE q.state='complete' AND q.job_id IS NOT NULL ORDER BY q.updated_at DESC")
                checked = 0
                for queued in complete:
                    remaining()
                    if queued['target_id'] not in config['targets']:
                        continue
                    if checked >= config['max_products_per_cycle']:
                        break
                    with store.connection() as db:
                        recent = db.execute('SELECT result_json FROM watch_catalog_checks WHERE job_id=? AND checked_at>?',
                                            (queued['job_id'], later(-24 * 3600))).fetchone()
                    if recent:
                        cached = json.loads(recent['result_json'])
                        if cached.get('error'):
                            result['errors'].append({'job_id': queued['job_id'], **cached['error']})
                        continue
                    checked += 1
                    try:
                        check = _refresh_catalogs(store, artifacts, queued['job_id'])
                        result['catalog_checks'].append({'job_id': queued['job_id'], **check})
                        remaining()
                    except (OSError, ValueError, LookupError) as exc:
                        result['errors'].append(_error(exc))
    except TimeoutError as exc:
        result['errors'].append(_error(exc))

    with store.connection() as db:
        result['new_candidates'] = db.execute('SELECT count(*) FROM candidates').fetchone()[0] - initial_count
    result['finished_at'] = utc_now()
    if result['errors']:
        result['status'] = 'partial' if result['dispatches'] or observed else 'failed'
    ledger.automation_update(phase='error' if result['errors'] else 'waiting', result=result,
                             error=result['errors'][0] if result['errors'] else None)
    return result


def serve_automatic(store, artifacts, protocol_id, config, *, max_hours=None):
    config = validate_config(config)
    if max_hours is not None and (isinstance(max_hours, bool) or not isinstance(max_hours, (int, float))
                                  or not math.isfinite(max_hours) or not 0 < max_hours <= 168):
        raise ValidationError('Optional service lifetime must be positive and at most 168 hours')
    ledger = WatchStore(store)
    stop = threading.Event()
    heartbeat_stop = threading.Event()
    deadline = time.monotonic() + max_hours * 3600 if max_hours is not None else None

    def shutdown(signum, frame):
        stop.set()

    def heartbeat():
        while not heartbeat_stop.wait(15):
            try:
                ledger.automation_update()
            except Exception:
                LOG.exception('Automatic watcher heartbeat failed')

    with exclusive_lock(store.path.with_suffix('.watch-service.lock')):
        ledger.start_automation(config)
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        previous = {signum: signal.signal(signum, shutdown) for signum in (signal.SIGINT, signal.SIGTERM)}
        next_tick = 0.0
        try:
            while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
                request = ledger.claim_check()
                if request is not None or time.monotonic() >= next_tick:
                    try:
                        remaining = deadline - time.monotonic() if deadline is not None else config['cycle_max_seconds']
                        result = run_cycle(store, artifacts, protocol_id, config,
                                           force=request is not None, max_seconds=remaining)
                        if request is not None:
                            ledger.finish_check(request['id'], result=result,
                                                error=result['errors'][0] if result['errors'] else None)
                        LOG.info('automatic cycle %s', canonical_json(result))
                    except Exception as exc:
                        failure = _error(exc)
                        ledger.automation_update(phase='error', error=failure)
                        if request is not None:
                            ledger.finish_check(request['id'], error=failure)
                        LOG.exception('Automatic watcher cycle failed')
                    next_tick = time.monotonic() + 60
                stop.wait(2)
        finally:
            stop.set()
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=5)
            ledger.automation_update(state='stopped')
            for signum, handler in previous.items():
                signal.signal(signum, handler)
