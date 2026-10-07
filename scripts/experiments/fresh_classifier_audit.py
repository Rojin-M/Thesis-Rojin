"""Evaluate the frozen eleven-expert supermodel on new labelled host data."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests
import torch

from scripts.data.shared_preprocessing import KEYS, SharedConfig, prepare_shared_star
from scripts.data.tess_dataset import apply_normalization
from scripts.experiments.adaptation_data import INPUTS
from scripts.experiments.adaptation_metrics import metrics, paired_group_bootstrap
from scripts.experiments.ai_telescope_blind_scan import _checked_complete
from scripts.experiments.ai_telescope_physical_benchmark import digest
from scripts.experiments.crossfit_competence import EXPERTS, context_matrix, full_role
from scripts.experiments.crossfit_supermodel_v2 import blend_logits, meta_logits, static_logits
from scripts.experiments.diagnostic_experts import load_models as load_diagnostics
from scripts.experiments.fresh_classifier_data import OUTPUT as DATA
from scripts.experiments.mission_adaptation import atomic_json
from scripts.experiments.physical_experts import KINDS, archive_plan, run_target
from scripts.experiments.transformer_expert import load_models as load_transformers
from scripts.research.model_comparison import ComparisonScorer
from scripts.research.experiments import verified_summary
from scripts.research.protocol import ROOT, utc_now
from scripts.research.provenance import file_sha256

OUTPUT = ROOT / 'outputs/research/fresh_classifier_audit/audit-v1'
RUNS = {'cnn': 'outputs/research/model_experiments/pilot-v1',
        'transformer': 'outputs/research/transformer_expert/pilot-v1',
        'diagnostic': 'outputs/research/diagnostic_experts/pilot-v2',
        'physical': 'outputs/research/physical_experts/pilot-v1',
        'supermodel': 'results/crossfit_supermodel_v2'}


def prepare_spec():
    pool = json.loads((DATA / 'pool.json').read_text())
    acquired = json.loads((DATA / 'acquired.json').read_text())
    if acquired['pool_sha256'] != digest(pool):
        raise ValueError('Fresh classifier acquisition differs from frozen pool')
    if json.loads((DATA / 'frozen.json').read_text())['pool_sha256'] != file_sha256(DATA / 'pool.json'):
        raise ValueError('Fresh classifier pool checksum mismatch')
    for name, checksum in pool['inputs'].items():
        if file_sha256(ROOT / name) != checksum:
            raise ValueError('Frozen classifier data input changed: ' + name)
    shared = pd.read_csv(ROOT / 'data/processed/tess/shared_v1/manifest_tess_shared_v1.csv')
    if {int(t) for t in pool['hosts']} & set(shared.star_id):
        raise ValueError('Classifier audit overlaps a prior TESS role')
    receipts = {key: (verified_summary(ROOT / path)[1] if key == 'cnn' else _checked_complete(ROOT / path))
                for key, path in RUNS.items()}
    sources = ['scripts/experiments/fresh_classifier_audit.py', 'scripts/data/shared_preprocessing.py',
               'scripts/data/tess_preprocessing.py', 'scripts/data/tess_dataset.py',
               'scripts/experiments/crossfit_competence.py', 'scripts/experiments/crossfit_supermodel_v2.py',
               'scripts/experiments/physical_experts.py']
    spec = {'version': 'fresh_classifier_audit_v1', 'runs': RUNS,
            'model_receipts': {key: file_sha256(ROOT / path / 'complete.json') for key, path in RUNS.items()},
            'pool_sha256': file_sha256(DATA / 'pool.json'), 'acquisition_sha256': file_sha256(DATA / 'acquired.json'),
            'sources': {name: file_sha256(ROOT / name) for name in sources},
            'physical_config': {**json.loads((ROOT / 'configs/physical_experts_v1.json').read_text()),
                                'tls_use_threads': 1, 'max_total_download_bytes': 12 * 1024**3},
            'protocol': {'fresh_host_pool': len(pool['hosts']), 'weights_selected_or_fitted': False,
                         'temperature_refitted': False, 'decision_threshold': .5,
                         'quality_cuts': 'unchanged shared_v1; every rejection recorded',
                         'ephemerides_and_labels': 'new separately pinned TOI catalog snapshot',
                         'physical_sector': 'first lexical among the latest three acquired sectors',
                         'classification_scope': 'catalog-disposition classification at known ephemerides',
                         'deployment': False}}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / 'spec.json'
    if path.exists() and json.loads(path.read_text()) != spec:
        raise ValueError('Frozen classifier audit specification changed')
    atomic_json(path, spec)
    return spec, pool, acquired, receipts


def install_reader_receipts(products):
    """Adapt exact download receipts to the unchanged shared_v1 reader contract."""
    for product in products:
        path = ROOT / product['path']
        if file_sha256(path) != product['sha256'] or path.stat().st_size != product['size_bytes']:
            raise ValueError('Fresh light curve changed')
        destination = ROOT / 'data/raw/tess/metadata/receipts' / (product['filename'] + '.json')
        value = {key: product[key] for key in ('data_uri', 'relative_path', 'size_bytes', 'sha256')}
        value['acquisition_manifest'] = str((DATA / 'acquired.json').relative_to(ROOT))
        if destination.exists() and json.loads(destination.read_text()) != value:
            raise ValueError('Existing shared-reader receipt differs; refusing overwrite')
        atomic_json(destination, value)


def prepare_host(task):
    star, products, candidates, companions = task
    return star, prepare_shared_star(ROOT, 'tess', int(star), products, candidates, companions, SharedConfig())


def prepare_features(pool, acquired, spec_sha):
    cache = OUTPUT / 'prepared.npz'
    record_path = OUTPUT / 'preparation.json'
    if record_path.exists():
        record = json.loads(record_path.read_text())
        if record['spec_sha256'] != spec_sha or record['arrays_sha256'] != file_sha256(cache):
            raise ValueError('Fresh prepared feature cache differs')
        with np.load(cache, allow_pickle=False) as saved:
            arrays = {key: saved[key] for key in saved.files}
        return arrays, record
    products = acquired['products']
    install_reader_receipts(products)
    by_host = {}
    for product in products:
        by_host.setdefault(product['tic_id'], []).append(product)
    candidates = {row['candidate_id']: row for row in pool['candidates']}
    tasks = []
    for star in sorted(by_host, key=int):
        tasks.append((star, by_host[star], [c for c in pool['candidates'] if str(c['star_id']) == star],
                      [c for c in pool['companions'] if str(c['star_id']) == star]))
    records, accepted = [], []
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as workers:
        futures = [workers.submit(prepare_host, task) for task in tasks]
        for future in as_completed(futures):
            star, (results, _, _) = future.result()
            for result in results:
                record = {key: result[key] for key in ('candidate_id', 'status', 'reason', 'diagnostics')}
                records.append(record)
                if result['status'] == 'accepted':
                    accepted.append((candidates[result['candidate_id']], result['arrays']))
            print(json.dumps({'stage': 'classifier_preparation', 'host': star, 'accepted_so_far': len(accepted)}), flush=True)
    accepted.sort(key=lambda item: item[0]['candidate_id'])
    missing = set(pool['hosts']) - set(by_host)
    for candidate in pool['candidates']:
        if str(candidate['star_id']) in missing:
            records.append({'candidate_id': candidate['candidate_id'], 'status': 'rejected', 'reason': 'no_public_120s_product'})
    arrays = {key: np.stack([item[1][key] for item in accepted]) for key in KEYS} if accepted else {}
    arrays['y'] = np.array([item[0]['y'] for item in accepted], dtype=np.float32)
    np.savez_compressed(cache, **arrays)
    record = {'spec_sha256': spec_sha, 'arrays_sha256': file_sha256(cache), 'candidates': [item[0] for item in accepted],
              'audit': sorted(records, key=lambda row: row['candidate_id']), 'registered_candidates': len(pool['candidates'])}
    atomic_json(record_path, record)
    return arrays, record


def physical_worker(target, product, config, output, spec_sha):
    torch.set_num_threads(1)
    with requests.Session() as session:
        return run_target(target, product, config, session, output, spec_sha)[0]


def physical_features(record, acquired, spec, spec_sha):
    folder = OUTPUT / 'physical'
    folder.mkdir(exist_ok=True)
    targets = []
    candidates = record['candidates']
    for star in sorted({str(row['star_id']) for row in candidates}, key=int):
        source = min([p for p in acquired['products'] if p['tic_id'] == star], key=lambda p: p['filename'])
        rows = [{'candidate_id': c['candidate_id'], 'role': 'fresh_audit', 'label': int(c['y']),
                 'period_days': c['period'], 'epoch_bjd_tdb': c['epoch_bjd'], 'duration_hours': c['duration_hours']}
                for c in candidates if str(c['star_id']) == star]
        targets.append({'target_id': star, 'lightcurve_path': source['path'], 'lightcurve_sha256': source['sha256'],
                        'sector': source['sector'], 'cadence_seconds': 120, 'candidates': rows})
    with requests.Session() as session:
        plan = archive_plan(session, {'targets': targets}, spec['physical_config'], folder)
    by_id = {p['target_id']: p for p in plan['products']}
    rows = []
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as workers:
        futures = [workers.submit(physical_worker, t, by_id.get(t['target_id']), spec['physical_config'], folder, spec_sha) for t in targets]
        for future in as_completed(futures):
            rows.extend(future.result())
            print(json.dumps({'stage': 'classifier_physical', 'candidates_completed': len(rows)}), flush=True)
    features = pd.DataFrame(rows).set_index('candidate_id')
    checkpoint = torch.load(ROOT / RUNS['physical'] / 'physical_experts.pt', map_location='cpu', weights_only=True)
    predictions = features[['target_id', 'role', 'label']].copy()
    for kind in KINDS:
        item = checkpoint['experts'][kind]
        raw = features[item['features']].to_numpy(float)
        logits = ((raw - np.array(item['mean'])) / np.array(item['scale'])) @ np.array(item['coefficient']) + item['intercept']
        predictions[kind + '_logit'] = logits
        predictions[kind + '_available'] = features[item['availability_column']].astype(bool)
    features.to_csv(OUTPUT / 'physical_features.csv')
    predictions.to_csv(OUTPUT / 'physical_predictions.csv')
    return features, predictions


def score(arrays, record, features, physical, receipts):
    cnn = ROOT / RUNS['cnn']
    scorer = ComparisonScorer(cnn.parent, cnn.name, receipts['cnn']['spec_sha256'])
    models = scorer.models + load_transformers(ROOT / RUNS['transformer'], receipts['transformer']['spec_sha256'])
    models += load_diagnostics(ROOT / RUNS['diagnostic'], receipts['diagnostic']['spec_sha256'])
    normalized = apply_normalization({key: arrays[key] for key in KEYS}, scorer.stats)
    part = {key: torch.from_numpy(normalized[key]) for key in INPUTS}
    part.update(y=torch.from_numpy(arrays['y']).float(), metadata=record['candidates'])
    base, availability, raw, columns = full_role(models, part, features, physical)
    context, names = context_matrix(base, raw, availability[:, -3:], part, columns)
    artifact = joblib.load(ROOT / RUNS['supermodel'] / 'supermodel.joblib')
    if artifact['feature_names'] != names or artifact['experts'] != list(EXPERTS):
        raise ValueError('Fresh supermodel feature schema differs from training')
    static = static_logits(base, availability, artifact['prior'])
    nonlinear = meta_logits(artifact['model'], context)
    combined = blend_logits(static, nonlinear, artifact['selected_configuration']['blend'])
    labels = arrays['y']
    outputs = {'crossfit_supermodel': metrics(labels, combined, artifact['calibration_temperature']),
               'v4_static': metrics(labels, static),
               'experts': {name: metrics(labels, base[:, index]) for index, name in enumerate(EXPERTS)}}
    groups = np.array([c['split_group'] for c in record['candidates']])
    variability = base[:, list(EXPERTS).index('stellar_variability')]
    bootstrap = paired_group_bootstrap(labels, groups, variability, combined, repeats=2000)
    bootstrap['metric'] = 'crossfit_supermodel_minus_variability_average_precision'
    predictions = pd.DataFrame({'candidate_id': [c['candidate_id'] for c in record['candidates']],
                                'target_id': [c['star_id'] for c in record['candidates']], 'label': labels,
                                'supermodel_logit': combined, 'v4_static_logit': static,
                                **{name + '_logit': base[:, i] for i, name in enumerate(EXPERTS)}})
    predictions.to_csv(OUTPUT / 'predictions.csv', index=False)
    return outputs, bootstrap


def main():
    torch.set_num_threads(1)
    spec, pool, acquired, receipts = prepare_spec()
    spec_sha = digest(spec)
    if (OUTPUT / 'complete.json').exists():
        _checked_complete(OUTPUT)
        print(json.dumps({'stage': 'already_complete'}))
        return
    arrays, record = prepare_features(pool, acquired, spec_sha)
    if len(arrays['y']) < 2 or len(set(arrays['y'])) != 2:
        atomic_json(OUTPUT / 'insufficient_labels.json', {'status': 'insufficient_labels', 'spec_sha256': spec_sha,
                    'accepted': len(arrays['y']), 'positive': int(arrays['y'].sum()), 'registered': len(pool['candidates'])})
        print(json.dumps({'stage': 'insufficient_labels', 'accepted': len(arrays['y'])}), flush=True)
        return
    features, physical = physical_features(record, acquired, spec, spec_sha)
    outputs, bootstrap = score(arrays, record, features, physical, receipts)
    summary = {'status': 'complete', 'version': spec['version'], 'spec_sha256': spec_sha, 'completed_at': utc_now(),
               'registered_candidates': len(pool['candidates']), 'accepted_candidates': len(arrays['y']),
               'positive': int(arrays['y'].sum()), 'negative': int((arrays['y'] == 0).sum()),
               'metrics': outputs, 'paired_group_bootstrap': bootstrap,
               'claims': {'new_host_validation': True, 'weights_or_thresholds_tuned': False,
                          'large_confirmatory_audit': False, 'deployed': False},
               'limitations': ['Archive availability and unchanged coverage rules restrict this cohort.',
                              'A small, imbalanced audit cannot establish a general superiority claim.',
                              'Labels are catalog dispositions from a pinned snapshot, not independent follow-up.',
                              'Latest three LC sectors and one pixel sector per host; known ephemerides.']}
    atomic_json(OUTPUT / 'summary.json', summary)
    lines = ['# Fresh labelled classifier audit', '',
             f"{len(pool['candidates'])} candidates were registered before inference; {len(arrays['y'])} passed archive and unchanged preprocessing rules.",
             f"Class counts: {summary['positive']} positive and {summary['negative']} negative.",
             'The existing model weights, blend, normalization and calibration temperature were reused without fitting.', '',
             '| Model | AP | ROC AUC | Brier | Accuracy at 0.5 |', '| --- | ---: | ---: | ---: | ---: |']
    for name, result in [('crossfit_supermodel', outputs['crossfit_supermodel']), ('v4_static', outputs['v4_static']), *outputs['experts'].items()]:
        rate = result['at_0_5']
        accuracy = (rate['tp'] + rate['tn']) / result['n']
        lines.append(f"| {name} | {result['average_precision']:.4f} | {result['roc_auc']:.4f} | {result['brier']:.4f} | {accuracy:.4f} |")
    lines += ['', 'The supermodel uses its frozen calibration temperature. Comparator Brier values use raw logits; AP/AUC do not depend on temperature.',
              'Every acquisition or preprocessing exclusion is retained in preparation.json. The small class counts limit conclusions; this is an independent check, not a large confirmation study.', '',
              'Paired AP uncertainty and all individual predictions are retained alongside this report. No model was selected on this audit and nothing was deployed.', '']
    (OUTPUT / 'report.md').write_text('\n'.join(lines))
    files = {str(p.relative_to(OUTPUT)): file_sha256(p) for p in OUTPUT.rglob('*') if p.is_file() and p.name != 'complete.json'}
    atomic_json(OUTPUT / 'complete.json', {'status': 'complete', 'spec_sha256': spec_sha, 'completed_at': utc_now(), 'files': files})
    print(json.dumps({'stage': 'classifier_complete', 'n': len(arrays['y']), 'supermodel': outputs['crossfit_supermodel']}), flush=True)


if __name__ == '__main__':
    main()
