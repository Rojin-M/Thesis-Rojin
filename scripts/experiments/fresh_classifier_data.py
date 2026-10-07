"""Acquire an independent labelled TESS audit without changing training data."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

import pandas as pd
import requests

from scripts.data.tess_download_raw import select_lightcurves
from scripts.data.tess_selection import select_candidates
from scripts.experiments.ai_telescope_physical_benchmark import digest
from scripts.experiments.freeze_prospective_cohort import candidate_targets
from scripts.experiments.mission_adaptation import atomic_json
from scripts.experiments.tls_pixel_pilot import _download
from scripts.research.mast import INVOKE, public_product_url
from scripts.research.protocol import ROOT, utc_now
from scripts.research.provenance import file_sha256

OUTPUT = ROOT / "outputs/research/fresh_classifier_audit/data-v1"
CATALOG = ROOT / "outputs/research/fresh_classifier_audit/catalog/toi.csv"
ACQUISITION = {"target_pixel_root": "data/raw/tess/fresh_classifier_v1/lightcurves",
               "receipt_root": "data/raw/tess/fresh_classifier_v1/receipts",
               "max_product_bytes": 64 * 1024**2, "max_total_download_bytes": 1024**3}


def freeze():
    path = OUTPUT / "pool.json"
    if path.exists():
        value = json.loads(path.read_text())
        receipt = json.loads((OUTPUT / "frozen.json").read_text())
        if receipt["pool_sha256"] != file_sha256(path):
            raise ValueError("Fresh classifier pool changed")
        for name, checksum in value["inputs"].items():
            if file_sha256(ROOT / name) != checksum:
                raise ValueError("Fresh classifier input changed: " + name)
        return value
    catalog = pd.read_csv(CATALOG, dtype={"toi": str})
    kepler_path = ROOT / "data/raw/kepler/metadata/koi_cumulative.csv"
    manifest_path = ROOT / "data/processed/kepler/v0/manifest_kepler_v0.csv"
    # Grant provisional archive eligibility only; actual coverage is queried next.
    selected, audit, overlap = select_candidates(catalog, pd.DataFrame({'tic_id': catalog.tid}),
        pd.read_csv(kepler_path, comment='#'), pd.read_csv(manifest_path))
    excluded = {int(p.name[3:]) for p in (ROOT / "data/raw/tess/lightcurves").glob("TIC*") if p.name[3:].isdigit()}
    excluded.update(int(t.removeprefix('TIC')) for t in candidate_targets(ROOT / 'outputs/research/research.sqlite3')
                    if t.removeprefix('TIC').isdigit())
    groups = set(audit[audit.tic_id.isin(excluded)].split_group.dropna())
    selected = selected[~selected.tic_id.isin(excluded) & ~selected.split_group.isin(groups)].copy()
    # Unscored, deterministic complete eligible pool, with an explicit cap.
    hosts = sorted(set(selected.tic_id.astype(int)))
    if len(hosts) > 500:
        raise ValueError("Fresh classifier pool exceeds the registered acquisition cap")
    known = catalog.rename(columns={"tid": "star_id", "pl_orbper": "period", "pl_tranmid": "epoch_bjd",
                                     "pl_trandurh": "duration_hours"})
    known['candidate_id'] = 'TOI-' + known.toi.astype(str)
    selected['star_id'] = selected.tic_id.astype(int)
    keys = ['candidate_id', 'star_id', 'tic_id', 'split_group', 'tfopwg_disp', 'y', 'period', 'epoch_bjd', 'duration_hours']
    companions = known[known.star_id.isin(hosts)][['candidate_id', 'star_id', 'period', 'epoch_bjd', 'duration_hours']]
    sources = [CATALOG, kepler_path, manifest_path, ROOT / 'scripts/experiments/fresh_classifier_data.py',
               ROOT / 'scripts/data/tess_selection.py', ROOT / 'scripts/data/tess_download_raw.py']
    value = {'version': 'fresh_classifier_data_v1', 'frozen_at': utc_now(), 'hosts': list(map(str, hosts)),
             'candidates': json.loads(selected[keys].to_json(orient='records')),
             'companions': json.loads(companions.to_json(orient='records')),
             'excluded_cached_or_reviewed_hosts': sorted(excluded), 'kepler_quarantined_hosts': overlap.tic_id.nunique(),
             'inputs': {str(p.relative_to(ROOT)): file_sha256(p) for p in sources},
             'rules': {'ephemeris_and_period_cuts': 'unchanged shared_v1 selection; period 0.5–30 d',
                       'sector_selection': 'latest three native 120-second public SPOC sectors',
                       'preprocessing': 'unchanged shared_v1 coverage and companion rules',
                       'model_tuning': False, 'replacement_after_scores': False}, 'acquisition': ACQUISITION}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    atomic_json(path, value)
    atomic_json(OUTPUT / 'frozen.json', {'pool_sha256': file_sha256(path), 'frozen_at': utc_now()})
    return value


def query(pool):
    path = OUTPUT / 'archive_manifest.json'
    if path.exists():
        value = json.loads(path.read_text())
        if value['pool_sha256'] != digest(pool):
            raise ValueError('Archive pool differs')
        return value
    products, receipts = [], []
    for start in range(0, len(pool['hosts']), 50):
        targets = pool['hosts'][start:start+50]
        cache = OUTPUT / f'query-{start:03d}.json'
        if cache.exists():
            page = json.loads(cache.read_text())
        else:
            request = {'service': 'Mast.Caom.Filtered', 'format': 'json', 'page': 1, 'pagesize': 10000,
                       'params': {'columns': '*', 'filters': [
                           {'paramName': key, 'values': value} for key, value in {
                               'obs_collection': ['TESS'], 'provenance_name': ['SPOC'],
                               'target_name': targets, 'dataproduct_type': ['timeseries'],
                               'dataRights': ['PUBLIC']}.items()]}}
            with requests.post(INVOKE, data={'request': json.dumps(request)}, timeout=(10, 90), stream=True) as response:
                response.raise_for_status()
                content = bytearray()
                for block in response.iter_content(65536):
                    content.extend(block)
                    if len(content) > 16 * 1024**2:
                        raise ValueError('Archive metadata exceeds bound')
            page = json.loads(content)
            if page.get('status') != 'COMPLETE' or int(page.get('paging', {}).get('pagesFiltered', 2)) > 1:
                raise ValueError('Incomplete archive query')
            atomic_json(cache, page)
        rows = [row for row in page['data'] if row.get('t_exptime') is not None and row.get('sequence_number') is not None
                and str(row.get('dataRights', '')).upper() == 'PUBLIC']
        available = select_lightcurves(rows, set(targets), 999)
        for target in targets:
            local = sorted([r for r in available if r['tic_id'] == target], key=lambda r: (r['sector'], r['filename']))[-3:]
            for item in local:
                item['relative_path'] = 'fresh_classifier_v1/' + item['relative_path']
            products.extend(local)
        receipts.append({'path': cache.name, 'sha256': file_sha256(cache)})
        print(json.dumps({'stage': 'classifier_archive', 'queried': min(start+50, len(pool['hosts'])),
                          'hosts_with_products': len({p['tic_id'] for p in products})}), flush=True)
    value = {'pool_sha256': digest(pool), 'products': products, 'queries': receipts,
             'missing_hosts': sorted(set(pool['hosts']) - {p['tic_id'] for p in products})}
    atomic_json(path, value)
    return value


def acquire(pool, manifest):
    def preflight(product):
        url = public_product_url(product['data_uri'])
        with requests.head(url, timeout=(5, 30), allow_redirects=False, headers={'Accept-Encoding': 'identity'}) as response:
            response.raise_for_status()
            length = int(response.headers.get('Content-Length', 0))
            if not 0 < length <= ACQUISITION['max_product_bytes']:
                raise ValueError('LC byte count outside cap')
            return {**product, 'target_id': product['tic_id'], 'url': url, 'size_bytes': length,
                    'etag': response.headers.get('ETag'), 'last_modified': response.headers.get('Last-Modified')}
    path = OUTPUT / 'download_plan.json'
    if path.exists():
        plan = json.loads(path.read_text())
        if plan['manifest_sha256'] != digest(manifest):
            raise ValueError('LC download plan differs')
    else:
        with ThreadPoolExecutor(max_workers=4) as workers:
            products = list(workers.map(preflight, manifest['products']))
        if sum(p['size_bytes'] for p in products) > ACQUISITION['max_total_download_bytes']:
            raise ValueError('Fresh LC download exceeds 1 GiB cap')
        plan = {'manifest_sha256': digest(manifest), 'products': products}
        atomic_json(path, plan)
    def download(product):
        with requests.Session() as session:
            path, receipt, _ = _download(session, product, {'target_id': product['target_id']}, ACQUISITION)
        return {**product, 'path': str(path.relative_to(ROOT)), 'sha256': receipt['sha256']}
    products = []
    with ThreadPoolExecutor(max_workers=4) as workers:
        for result in workers.map(download, plan['products']):
            products.append(result)
            print(json.dumps({'stage': 'classifier_lc_acquisition', 'completed': len(products), 'registered': len(plan['products'])}), flush=True)
    atomic_json(OUTPUT / 'acquired.json', {'pool_sha256': digest(pool), 'products': products, 'completed_at': utc_now()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquire', action='store_true')
    args = parser.parse_args()
    pool = freeze()
    print(json.dumps({'stage': 'classifier_pool_frozen', 'hosts': len(pool['hosts']), 'candidates': len(pool['candidates'])}), flush=True)
    if args.acquire:
        acquire(pool, query(pool))


if __name__ == '__main__':
    main()
