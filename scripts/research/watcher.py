"""Scoped release watcher and explicit, finite public-product dispatcher.

Polling never queues science work. A pilot freezes explicit observed product IDs
once, and all future dispatches reuse that selection and its cumulative budgets.
"""
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time

from . import mast
from .protocol import ROOT, ConflictError, ValidationError, canonical_json, digest, identifier, utc_now
from .provenance import code_snapshot, file_sha256
from .store import _one, _rows
from .watcher_store import WatchStore, exclusive_lock, later, status

LOG = logging.getLogger(__name__)
DEFAULT_CONFIG = ROOT / 'configs/research_watcher_v1.json'


def load_config(path=DEFAULT_CONFIG):
    value = json.loads(Path(path).read_text())
    required = {'version','targets','max_products_per_poll','poll_seconds','poll_max_seconds','metadata_only'}
    if not isinstance(value,dict) or set(value) != required or value['version'] != 1 or value['metadata_only'] is not True:
        raise ValidationError('Watcher config v1 must explicitly use metadata_only=true and only documented fields')
    targets = value['targets']
    if (not isinstance(targets,list) or not 1<=len(targets)<=20
            or any(not isinstance(t,str) or not t.isascii() or not t.isdigit() or not 0<int(t)<10**16 for t in targets)
            or len(set(targets)) != len(targets)):
        raise ValidationError('Select 1–20 distinct explicit numeric TIC IDs')
    for key,low,high in [('max_products_per_poll',1,2),('poll_seconds',3600,86400),('poll_max_seconds',1,180)]:
        if type(value[key]) is not int or not low<=value[key]<=high:
            raise ValidationError('Invalid bounded watcher setting: '+key)
    return value


def _error(exc):
    return {'code':type(exc).__name__,'message':str(exc)[:1900] or type(exc).__name__,
            'retryable':isinstance(exc,(OSError,TimeoutError))}


def _register_product(store, observation, row, provenance_id):
    match = mast.LC_NAME.fullmatch(mast.filename(row['dataURI']))
    sector, build = int(match[1]), match[3]
    release_key = f'SPOC:sector-{sector}:file-build-{build}'
    # First observation is immutable; subsequent polls are separate snapshots.
    with store.connection() as db:
        old = db.execute('SELECT id FROM releases WHERE mission=? AND release_key=?', ('TESS',release_key)).fetchone()
    if old:
        release_id = old['id']
    else:
        release_id = store.register_release(mission='TESS', release_key=release_key, available_at=utc_now(),
            provenance_id=provenance_id, metadata={'sector':sector,'filename_processing_version':build,
                'availability_semantics':'first observed public selected product; NOT a complete sector release',
                'official_data_release_number':None})['id']
    metadata = {'sector':sector,'filename_processing_version':build,'pipeline_version':row['prvversion'],
        'size_bytes':row['size'],'filename':row['productFilename'],'obsid':str(observation['obsid']),
        'archive_release_mjd':observation['t_obs_release'],
        'archive_release_utc':mast.public_release_time(observation['t_obs_release']),
        'data_rights':'PUBLIC','product_subgroup':'LC','availability_scope':'selected_product_only',
        'upstream_checksum':None,'checksum_note':'MAST product row supplies no cryptographic checksum; capture SHA256 and validate native FITS checksums on acquisition'}
    # Identity changes when URI, processing version, size or release metadata changes.
    product_key = row['dataURI'] + ':metadata-' + digest(metadata)
    with store.connection() as db:
        old = db.execute('SELECT id FROM products WHERE release_id=? AND product_key=?', (release_id,product_key)).fetchone()
    if old:
        return old['id']
    return store.register_product(release_id=release_id,product_key=product_key,target_id=str(observation['target_name']),
        source_uri=row['dataURI'],provenance_id=provenance_id,metadata=metadata)['id']


def poll_once(store, config, *, client=None, force=False):
    ledger = WatchStore(store)
    root = store.path.parent / 'watcher'
    with exclusive_lock(ledger.lock_path):
        record = ledger.config(config)
        key = ledger.begin_poll(record['id'], config['poll_seconds'], force)
        if isinstance(key,dict):
            raise ConflictError('Metadata circuit stopped after 3 consecutive failures; inspect and explicitly reset')
        if key is None:
            return {'status':'not_due','config_id':record['id'],'next_poll_at':record['next_poll_at']}
        client = client or mast.MastClient(ledger)
        result = {'config_id':record['id'],'poll_id':key,'product_ids':[], 'new_product_ids':[],
            'metadata_only':True,'scope':'explicit_TICs_latest_public_standard_SPOC_LC',
            'target_ids':config['targets'], 'archive_wide_complete':False, 'snapshots':[]}
        try:
            with mast.wall_deadline(config['poll_max_seconds']):
                request = mast.observation_request(config['targets'])
                raw = client.query(request)
                prov = ledger.snapshot(key,request,raw,root)
                result['snapshots'].append(prov)
                rows, complete = mast.decode_page(raw)
                selected, selection = mast.select_observations(rows,config['targets'],config['max_products_per_poll'])
                result.update(selection, observation_page_complete=complete)
                result['metadata_pages_complete'] = complete
                for observation in selected:
                    request = mast.product_request(observation['obsid'])
                    raw = client.query(request)
                    prov = ledger.snapshot(key,request,raw,root)
                    result['snapshots'].append(prov)
                    rows, complete = mast.decode_page(raw)
                    result['metadata_pages_complete'] &= complete
                    row = mast.select_product(rows,observation)
                    with store.connection() as db:
                        old_ids = {r[0] for r in db.execute('SELECT id FROM products WHERE source_uri=?',(row['dataURI'],))}
                    pid = _register_product(store,observation,row,prov)
                    result['product_ids'].append(pid)
                    if pid not in old_ids:
                        result['new_product_ids'].append(pid)
                    with store.connection(True) as db:
                        db.execute('INSERT OR IGNORE INTO watch_seen VALUES(?,?)',(key,pid))
                result['status'] = 'succeeded'
            ledger.finish_poll(key,config['poll_seconds'],result=result)
        except Exception as exc:
            error = _error(exc)
            result.update(status='failed',error=error)
            ledger.finish_poll(key,config['poll_seconds'],result=result,error=error)
        return result


def create_pilot(store, protocol_id, *, pilot_id, product_ids, cohort, max_bytes, max_seconds):
    identifier(pilot_id,'pilot_id')
    ids = sorted(set(product_ids))
    if not 1<=len(ids)<=20 or cohort not in ('known_object_control','archival_pilot'):
        raise ValidationError('Pilot needs 1–20 observed products and an explicit control/archival cohort')
    if type(max_bytes) is not int or not 1<=max_bytes<=2*1024**3 or type(max_seconds) is not int or not 1<=max_seconds<=7200:
        raise ValidationError('Pilot requires explicit positive byte and runtime budgets (at most 2 GiB / 7200 s)')
    ledger = WatchStore(store)
    with exclusive_lock(ledger.lock_path):
        with store.connection() as db:
            old = db.execute('SELECT spec_json FROM watch_pilots WHERE id=?',(pilot_id,)).fetchone()
        # Replay the original code freeze, even if completed sources later change.
        code = json.loads(old[0])['code'] if old else code_snapshot()
        spec = {'product_ids':ids,'cohort':cohort,'max_bytes':max_bytes,'max_seconds':max_seconds,
            'protocol_id':protocol_id,'code':code,'catalog_mode':'offline','workers':1,
            'selection':'explicit_immutable_products_no_automatic_sector_expansion'}
        with store.connection() as db:
            products = [_one(db,'SELECT * FROM products WHERE id=?',(pid,)) for pid in ids]
            if any(not db.execute('SELECT 1 FROM watch_seen WHERE product_id=?',(pid,)).fetchone() for pid in ids):
                raise ValidationError('Products need a recorded public watcher snapshot')
        if sum(p['metadata']['size_bytes'] for p in products)>max_bytes:
            raise ValidationError('Selected products exceed the explicit byte budget')
        limits = store.get_protocol(protocol_id)['document']['limits']
        if len(ids)>limits['initial_products'] or len({p['target_id'] for p in products})>limits['initial_targets'] or max_bytes>limits['download_bytes_total']:
            raise ValidationError('Pilot exceeds registered protocol bounds')
        return ledger.pilot(pilot_id,spec)


def _atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as handle:
        handle.write(canonical_json(value)+'\n'); handle.flush(); os.fsync(handle.fileno())
    os.replace(temp,path)


def _verify_receipt(product, receipt):
    path = Path(receipt['path'])
    if (receipt['source_uri'] != product['source_uri'] or path.stat().st_size != product['metadata']['size_bytes']
            or file_sha256(path) != receipt['sha256']):
        raise ValidationError('Completed product is missing, changed or corrupt; no silent redownload')
    return receipt


def acquire(store, product, pilot_id, client):
    ledger = WatchStore(store)
    with store.connection() as db:
        queue = _one(db,'SELECT * FROM watch_queue WHERE product_id=?',(product['id'],))
    if queue['receipt']:
        return _verify_receipt(product,queue['receipt'])
    root = store.path.parent / 'watcher' / 'products' / product['id']
    root.mkdir(parents=True,exist_ok=True)
    final = root / product['metadata']['filename']
    sidecar = root / 'receipt.json'
    partial = root / 'download.part.fits'
    if sidecar.exists():
        receipt = json.loads(sidecar.read_text())
        if not final.exists() and partial.exists():
            os.replace(partial,final)
        receipt = _verify_receipt(product,receipt)
    else:
        if final.exists():
            raise ValidationError('Unreceipted completed file requires inspection; refusing overwrite')
        # Try only the selected TIC's bounded existing manifest, never scan data trees.
        from .local_selection import cached_tess_paths
        try:
            local = cached_tess_paths(ROOT,product['target_id'],20)
        except (OSError,ValidationError):
            local = []
        cached = next((p for p in local if p.name == final.name and p.stat().st_size == product['metadata']['size_bytes']),None)
        if cached:
            from .lightcurves import read_lightcurves
            curve = read_lightcurves([cached],mission='TESS',target_id=product['target_id'])
            original = curve.sources[0]
            receipt = {'path':str(cached.resolve()),'source_uri':product['source_uri'],'sha256':original['sha256'],
                'bytes':original['size_bytes'],'new_download_bytes':0,'retrieved_at':original['original_retrieved_at'],
                'verified_at':utc_now(),'mode':'reused_local_product','native_receipt':original}
            _atomic_json(sidecar,receipt)
        else:
            if partial.exists():
                partial.unlink()  # Only this queue item's incomplete owned transfer.
            receipt = client.download(product,partial,pilot_id)
            from .lightcurves import read_lightcurves
            curve = read_lightcurves([partial],mission='TESS',target_id=product['target_id'],
                expected_hashes={str(partial.resolve()):receipt['sha256']})
            receipt.update(path=str(final.resolve()),new_download_bytes=receipt['bytes'],
                           mode='public_MAST_download',native_validation=curve.metadata)
            _atomic_json(sidecar,receipt)
            os.replace(partial,final)
        receipt = _verify_receipt(product,receipt)
    ledger.queue(product['id'],receipt=receipt,state='acquired',error=None)
    return receipt


def process_product(store, artifacts, product, receipt, pilot):
    from .detection_worker import run_local_detection
    from .vetting_worker import run_vetting
    spec = pilot['spec']
    key = 'watch-bls-v1:' + product['id']
    with store.connection() as db:
        old = db.execute('SELECT id FROM jobs WHERE job_key=?',(key,)).fetchone()
    if old:
        WatchStore(store).queue(product['id'],job_id=old['id'])
        job = store.get_job(old['id'])
        if job['status'] == 'succeeded':
            return old['id']
        store.recover_expired()
        job = store.get_job(old['id'])
        if any(s['status']=='running' for s in job['stages']):
            raise OSError('Existing stage lease is still active; recovery must wait for its expiry')
        for stage in job['stages']:
            if stage['status']=='failed':
                store.retry_stage(old['id'],stage['name'],actor='bounded-watch-dispatcher',reason='Explicit frozen pilot dispatch retry within stage and queue caps')
    if code_snapshot()['manifest_sha256'] != spec['code']['manifest_sha256']:
        raise ConflictError('Source changed since pilot freeze; unfinished work requires inspection and the pinned source')
    result = run_local_detection(store,artifacts,spec['protocol_id'],paths=[receipt['path']],mission='TESS',
        target_id=product['target_id'],cohort=spec['cohort'],job_key=key,
        experiment={'kind':'public_archive_bounded_pilot','pilot_id':pilot['id'],'prospective':False},
        public_product={'product_id':product['id'],'release_id':product['release_id'],'receipt':receipt})
    WatchStore(store).queue(product['id'],job_id=result['job_id'],state='processing')
    run_vetting(store,artifacts,result['job_id'],catalog_mode='offline')
    return result['job_id']


def dispatch(store, artifacts, pilot_id, *, client=None, processor=process_product):
    ledger = WatchStore(store)
    with exclusive_lock(ledger.lock_path):
        with store.connection() as db:
            pilot = _one(db,'SELECT * FROM watch_pilots WHERE id=?',(pilot_id,))
            queue = _rows(db,'SELECT * FROM watch_queue WHERE pilot_id=? ORDER BY product_id',(pilot_id,))
        if all(q['state']=='complete' for q in queue):
            return {'pilot_id':pilot_id,'status':'complete','already_complete':True}
        key, remaining = ledger.dispatch_start(pilot_id)
        started = time.monotonic()
        state, outcomes = 'paused', []
        client = client or mast.MastClient(ledger)
        try:
            with mast.wall_deadline(remaining):
                store.recover_expired()
                for row in queue:
                    pid = row['product_id']
                    if row['state']=='complete' or row['attempts']>=3 or (row['next_attempt_at'] and row['next_attempt_at']>utc_now()):
                        continue
                    if row['error'] and not row['error']['retryable']:
                        continue
                    with store.connection() as db:
                        product = _one(db,'SELECT * FROM products WHERE id=?',(pid,))
                        prior = db.execute('SELECT id FROM jobs WHERE job_key=?',('watch-bls-v1:'+pid,)).fetchone()
                    if prior:
                        active = [s for s in store.get_job(prior['id'])['stages'] if s['status']=='running']
                        if active:
                            # A restart must wait for the fenced stage lease;
                            # waiting is neither a new download nor an attempt.
                            ledger.queue(pid,state='waiting_for_lease',job_id=prior['id'],
                                next_attempt_at=max(s['lease_until'] for s in active),
                                error={'code':'ActiveStageLease','message':'Waiting for existing stage lease to expire', 'retryable':True})
                            continue
                    attempt = row['attempts']+1
                    ledger.queue(pid,state='running',attempts=attempt,error=None)
                    try:
                        receipt = acquire(store,product,pilot_id,client)
                        job_id = processor(store,artifacts,product,receipt,pilot)
                        ledger.queue(pid,state='complete',job_id=job_id,error=None,next_attempt_at=None)
                        outcomes.append({'product_id':pid,'job_id':job_id,'status':'complete'})
                    except Exception as exc:
                        error = _error(exc)
                        # Detection may have published a job before failing. Link
                        # it immediately so its lease/attempt evidence is visible.
                        with store.connection() as db:
                            job = db.execute('SELECT id FROM jobs WHERE job_key=?',('watch-bls-v1:'+pid,)).fetchone()
                        if job:
                            ledger.queue(pid,job_id=job['id'])
                        ledger.queue(pid,state='failed',error=error,next_attempt_at=later(60*2**(attempt-1)))
                        outcomes.append({'product_id':pid,'status':'failed','error':error})
                        LOG.warning('Product %s failed: %s',pid,error['message'])
                    if time.monotonic()-started >= remaining:
                        break
            with store.connection() as db:
                states = [r[0] for r in db.execute('SELECT state FROM watch_queue WHERE pilot_id=?',(pilot_id,))]
            state = 'complete' if all(s=='complete' for s in states) else ('failed' if 'failed' in states else 'paused')
        except TimeoutError as exc:
            outcomes.append({'status':'runtime_exhausted','error':_error(exc)})
            state = 'runtime_exhausted'
        finally:
            ledger.dispatch_finish(key,time.monotonic()-started,state)
        return {'pilot_id':pilot_id,'status':state,'outcomes':outcomes,'elapsed_seconds':time.monotonic()-started}


def serve_metadata(store,config,*,max_hours=12):
    if not 0<max_hours<=12:
        raise ValidationError('Metadata service lifetime must be at most 12 hours per invocation')
    ledger=WatchStore(store)
    record=ledger.config(config)
    stop=threading.Event()
    def shutdown(signum,frame):
        stop.set()
    previous={s:signal.signal(s,shutdown) for s in (signal.SIGINT,signal.SIGTERM)}
    deadline=time.monotonic()+max_hours*3600
    owns_service=False
    try:
        # Separate service lock prevents duplicate heartbeat/poll schedulers;
        # the short database lock still lets explicit pilots run between polls.
        with exclusive_lock(store.path.with_suffix('.watch-service.lock')):
            owns_service=True
            ledger.service(record['id'],'running')
            while not stop.is_set() and time.monotonic()<deadline:
                ledger.service(record['id'],'running')
                try:
                    with mast.wall_deadline(max(.001,deadline-time.monotonic())):
                        result=poll_once(store,config)
                    if result['status']!='not_due':
                        LOG.info('metadata poll %s',canonical_json(result))
                except ConflictError as exc:
                    LOG.info('metadata poll held: %s',exc)
                except TimeoutError:
                    LOG.info('Metadata service reached its finite lifetime')
                    break
                stop.wait(min(30,max(0,deadline-time.monotonic())))
    finally:
        if owns_service:
            ledger.service(record['id'],'stopped')
        for s,handler in previous.items():
            signal.signal(s,handler)
