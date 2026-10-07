"""Bounded, auditable sampling of new public TESS target identities.

Discovery supplies identities to the ordinary exact-product watcher. It does
not download light curves, inspect catalog ephemerides, or claim archive-wide
coverage. Its additive selection lives beside the database, outside source.
"""
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re

from . import mast
from .protocol import ROOT, ConflictError, ValidationError, canonical_json, digest, utc_now
from .provenance import file_sha256
from .watcher_store import WatchStore, exclusive_lock

SCOPE = 'bounded_sample_of_public_TESS_SPOC_observations'
EXCLUSION_FILES = (
    'data/raw/tess/metadata/manifest.csv',
    'data/processed/tess/v0/manifest_tess_v0.csv',
    'data/processed/tess/v0/selection.csv',
    'data/processed/tess/v0/kepler_overlap.csv',
)


def validate_discovery(value):
    bounds = {'lookback_days': (1, 730), 'max_pages': (1, 3), 'page_size': (1, 100),
              'max_targets': (1, 18), 'poll_seconds': (3600, 86400)}
    if not isinstance(value, dict) or set(value) != set(bounds):
        raise ValidationError('Discovery requires exactly lookback_days, max_pages, page_size, max_targets and poll_seconds')
    for key, (low, high) in bounds.items():
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValidationError('Invalid bounded discovery setting: ' + key)
    return json.loads(canonical_json(value))


def discovery_config(settings):
    return {'mode': 'target_discovery', 'targets': [], 'settings': validate_discovery(settings)}


def _tic(value):
    match = re.fullmatch(r'(?:TIC[- ]?)?([0-9]{1,16})', str(value).strip(), re.IGNORECASE)
    if match and 0 < int(match[1]) < 10**16:
        return str(int(match[1]))
    return None


def _exclusions(store, root):
    excluded, sources = set(), []
    for relative in EXCLUSION_FILES:
        path = Path(root) / relative
        if not path.exists():
            sources.append({'path': relative, 'present': False})
            continue
        if path.stat().st_size > 64 * 1024**2:
            raise ValidationError('Discovery exclusion manifest exceeds 64 MiB: ' + relative)
        found, count = set(), 0
        with path.open(newline='') as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or 'tic_id' not in reader.fieldnames:
                raise ValidationError('Discovery exclusion manifest lacks tic_id: ' + relative)
            for row in reader:
                count += 1
                if count > 100000:
                    raise ValidationError('Discovery exclusion manifest exceeds 100000 rows: ' + relative)
                target = _tic(row['tic_id'])
                if target is None:
                    raise ValidationError('Invalid TIC in discovery exclusion manifest: ' + relative)
                found.add(target)
        excluded.update(found)
        sources.append({'path': relative, 'present': True, 'sha256': file_sha256(path),
                        'rows': count, 'targets': len(found)})
    stored = set()
    with store.connection() as db:
        for row in db.execute("SELECT p.target_id FROM products p JOIN releases r ON r.id=p.release_id WHERE r.mission='TESS'"):
            if (target := _tic(row[0])):
                stored.add(target)
        for row in db.execute("SELECT target_id FROM candidates WHERE mission='TESS'"):
            if (target := _tic(row[0])):
                stored.add(target)
        for row in db.execute('SELECT inputs_json FROM jobs'):
            inputs = json.loads(row[0])
            if inputs.get('mission') == 'TESS' and (target := _tic(inputs.get('target_id'))):
                stored.add(target)
    excluded.update(stored)
    sources.append({'source': 'research_database_TESS_products_jobs_candidates',
                    'targets': len(stored), 'sha256': digest(sorted(stored))})
    return excluded, {'sources': sources, 'targets': len(excluded), 'sha256': digest(sorted(excluded))}


def _budget(store):
    with store.connection() as db:
        charged = db.execute('SELECT COALESCE(SUM(COALESCE(used,cap)),0) FROM watch_spending').fetchone()[0]
        cap = db.execute('SELECT cap FROM watch_budget WHERE id=1').fetchone()[0]
        selected = db.execute('SELECT count(*) FROM watch_queue').fetchone()[0]
        targets = {row[0] for row in db.execute('SELECT DISTINCT p.target_id FROM watch_queue q JOIN products p ON p.id=q.product_id')}
    return {'cap_bytes': cap, 'charged_bytes': charged, 'remaining_bytes': cap - charged,
            'remaining_product_slots': max(0, 20 - selected),
            'remaining_target_slots': max(0, 20 - len(targets))}, targets


def _request(settings, page, low, high):
    request = mast.observation_request([])
    request.update(page=page, pagesize=settings['page_size'])
    request['params']['columns'] = 'obsid,obs_collection,provenance_name,dataproduct_type,target_name,dataRights,dataURL,t_obs_release,sequence_number,t_min,t_max'
    request['params']['filters'] = [entry for entry in request['params']['filters'] if entry['paramName'] != 'target_name']
    request['params']['filters'].append({'paramName': 't_obs_release', 'values': [{'min': low, 'max': high}]})
    request['params']['filters'].append({'paramName': 't_min', 'values': [{'min': low, 'max': high}]})
    return request


def _page(raw, request):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError('Discovery received invalid JSON') from exc
    if not isinstance(value, dict) or value.get('status') != 'COMPLETE':
        raise OSError('Discovery archive query did not complete')
    rows, paging = value.get('data'), value.get('paging')
    if (not isinstance(rows, list) or len(rows) > request['pagesize']
            or any(not isinstance(row, dict) for row in rows) or not isinstance(paging, dict)):
        raise ValidationError('Discovery page has invalid or excessive rows')
    for key in ('page', 'pagesFiltered', 'rowsFiltered'):
        if type(paging.get(key)) is not int or paging[key] < 0:
            raise ValidationError('Discovery page lacks valid paging identity')
    if (paging['page'] != request['page'] or paging['rowsFiltered'] < len(rows)
            or (rows and paging['pagesFiltered'] < paging['page'])):
        raise ValidationError('Discovery response paging identity is inconsistent')
    return rows, paging


def _save(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as handle:
        handle.write(canonical_json({'schema_version': 1, **result}) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def discover_targets(store, settings, *, client=None, force=False, root=ROOT):
    """Return a persistent additive selection; never create products or pilots."""
    settings = validate_discovery(settings)
    ledger = WatchStore(store)
    state_path = store.path.parent / 'discovery' / 'state.json'
    with exclusive_lock(ledger.lock_path):
        previous = json.loads(state_path.read_text()) if state_path.exists() else {}
        if not isinstance(previous, dict):
            raise ValidationError('Discovery state must contain a selection object')
        targets = previous.get('targets', [])
        observations = previous.get('selected_observations', [])
        if (previous and previous.get('schema_version') != 1
                or not isinstance(targets, list) or any(not isinstance(target, str) for target in targets)
                or len(set(targets)) != len(targets)
                or any(_tic(target) != target for target in targets)
                or not isinstance(observations, list)
                or any(not isinstance(row, dict) for row in observations)
                or [row.get('target_id') for row in observations] != targets):
            raise ValidationError('Discovery state is invalid; inspect the persisted selection')
        if len(targets) > settings['max_targets']:
            raise ConflictError('Discovery cannot shrink an existing immutable target selection')
        record = ledger.config(discovery_config(settings))
        budget, queued_targets = _budget(store)
        pending = len(set(targets) - queued_targets)
        capacity = min(settings['max_targets'] - len(targets), budget['remaining_product_slots'] - pending,
                       budget['remaining_target_slots'] - pending)
        result = {'status': 'cached', 'config_id': record['id'], 'poll_id': None,
                  'settings': settings, 'targets': list(targets), 'selected_observations': list(observations),
                  'new_targets': [], 'errors': [], 'next_poll_at': record['next_poll_at'],
                  'exhausted': capacity <= 0 or budget['remaining_bytes'] < mast.METADATA_CAP,
                  'budget': budget, 'scope': SCOPE, 'archive_wide_complete': False,
                  'source_exclusions': previous.get('source_exclusions'),
                  'snapshots': [], 'started_at': utc_now(),
                  'last_polled_at': previous.get('last_polled_at')}
        if result['exhausted']:
            result['exhausted_reason'] = ('target_selection_full' if len(targets) >= settings['max_targets'] else
                                          'cumulative_product_or_target_cap' if capacity <= 0 else 'network_budget')
            result['finished_at'] = utc_now()
            _save(state_path, result)
            return result
        key = ledger.begin_poll(record['id'], settings['poll_seconds'], force)
        if isinstance(key, dict):
            result.update(status='circuit_open', errors=[{'code': 'DiscoveryCircuitOpen',
                          'message': 'Discovery stopped after three consecutive failures; inspect and explicitly reset'}])
            return result
        if key is None:
            result['status'] = 'not_due'
            return result
        result['poll_id'] = key
        result['last_polled_at'] = result['started_at']
        client = client or mast.MastClient(ledger)
        error = None
        try:
            with mast.wall_deadline(60 * settings['max_pages']):
                excluded, result['source_exclusions'] = _exclusions(store, root)
                excluded.update(targets)
                high = (datetime.now(timezone.utc) - datetime(1858, 11, 17, tzinfo=timezone.utc)).total_seconds() / 86400
                low = high - settings['lookback_days']
                result['release_mjd_window'] = {'min': low, 'max': high}
                result['observation_start_mjd_window'] = {'min': low, 'max': high}
                result['pages_sampled'] = 0
                result['observations_sampled'] = 0
                for page in range(1, settings['max_pages'] + 1):
                    request = _request(settings, page, low, high)
                    raw = client.query(request)
                    provenance = ledger.snapshot(key, request, raw, state_path.parent)
                    result['snapshots'].append(provenance)
                    rows, paging = _page(raw, request)
                    result['pages_sampled'] += 1
                    result['observations_sampled'] += len(rows)
                    eligible = []
                    for row in rows:
                        try:
                            release = float(row.get('t_obs_release'))
                            observed = float(row.get('t_min'))
                        except (ValueError, TypeError):
                            continue
                        if (row.get('dataproduct_type') == 'timeseries' and math.isfinite(release) and math.isfinite(observed)
                                and low <= release <= high and low <= observed <= high
                                and _tic(row.get('target_name')) == str(row.get('target_name'))
                                and str(row['target_name']) not in excluded):
                            eligible.append(row)
                    ordered_targets = sorted({str(row['target_name']) for row in eligible}, key=int)
                    chosen, _ = mast.select_observations(eligible, ordered_targets, capacity)
                    for row in chosen:
                        target = str(row['target_name'])
                        receipt = {'target_id': target, 'obsid': str(row['obsid']),
                                   'source_uri': row['dataURL'], 'sector': int(row['sequence_number']),
                                   'archive_release_mjd': row['t_obs_release'], 'provenance_id': provenance,
                                   'observation_start_mjd': row['t_min'],
                                   'selected_at': utc_now(), 'page': page, 'poll_id': key,
                                   'source_exclusions_sha256': result['source_exclusions']['sha256'],
                                   'policy': 'ascending_TIC_in_bounded_pages_latest_valid_observation_within_page',
                                   'cohort': 'archival_pilot', 'archive_wide_complete': False}
                        result['targets'].append(target)
                        result['new_targets'].append(target)
                        result['selected_observations'].append(receipt)
                        excluded.add(target)
                        capacity -= 1
                    if capacity <= 0 or page >= paging['pagesFiltered'] or not rows:
                        break
                result['status'] = 'succeeded'
        except Exception as exc:
            error = {'code': type(exc).__name__, 'message': str(exc)[:1900] or type(exc).__name__,
                     'retryable': isinstance(exc, (OSError, TimeoutError))}
            result.update(status='partial' if result['new_targets'] else 'failed', errors=[error])
        result['finished_at'] = utc_now()
        result['budget'], _ = _budget(store)
        result['exhausted'] = capacity <= 0 or result['budget']['remaining_bytes'] < mast.METADATA_CAP
        ledger.finish_poll(key, settings['poll_seconds'], result=result, error=error)
        result['next_poll_at'] = ledger.config(discovery_config(settings))['next_poll_at']
        _save(state_path, result)
        return result
