"""Rebuild the fixed, validation-only reference CNN calibration audit on CPU."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / 'results/reference_calibration_v1'
SOURCE_FILES = (
    'scripts/experiments/calibrate_reference.py',
    'scripts/experiments/adaptation_data.py',
    'scripts/experiments/adaptation_metrics.py',
    'scripts/research/scoring.py',
    'scripts/research/contracts.py',
    'scripts/data/tess_dataset.py',
    'scripts/data/tess_selection.py',
    'training/cnn/train_kepler_cnn.py',
)


def _sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _json(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _publish(path, payload):
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError('Immutable calibration artifact differs; use a new versioned output: ' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(payload)


def _csv(rows, columns):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def rebuild(output=DEFAULT_OUTPUT):
    import numpy as np
    import pandas as pd
    import scipy
    from scipy.special import expit
    import sklearn
    import torch

    from scripts.experiments.adaptation_data import audit_partitions, make_roles
    from scripts.experiments.adaptation_metrics import fit_temperature, metrics
    from scripts.research.scoring import CHECKPOINT, CHECKPOINT_SHA, NORMALIZER, NORMALIZER_SHA, FrozenScorer

    torch.set_num_threads(2)
    output = Path(output).resolve()
    folder = ROOT / 'data/processed/tess/shared_v1'
    names = ('dataset_tess_shared_v1.npz', 'manifest_tess_shared_v1.csv', 'splits_tess_shared_v1_seed42.npz')
    summary = json.loads((folder / 'preparation_summary.json').read_text())
    receipts = {}
    for name in names:
        path = folder / name
        actual = _sha(path)
        if actual != summary['outputs'][name]:
            raise ValueError('Prepared calibration input checksum changed: ' + name)
        receipts[str(path.relative_to(ROOT))] = actual
    frame = pd.read_csv(folder / names[1])
    with np.load(folder / names[2], allow_pickle=False) as archive:
        splits = {key: archive[key] for key in archive.files}
    audit_partitions(frame, splits)
    roles = make_roles(frame, partition_seed=2718, max_train_groups=None)
    spec_path = ROOT / 'outputs/research/model_experiments/pilot-v1/spec.json'
    # A saved experiment spec is an additional audit when available. The fixed
    # partition can be rebuilt from prepared identities without this local run.
    if spec_path.exists():
        saved = json.loads(spec_path.read_text())
        if saved['config']['partition_seed'] != 2718:
            raise ValueError('Saved calibration role seed changed')
        for role in ('calibration', 'audit'):
            if roles[role].tolist() != saved['data']['roles']['tess'][role]['row_indices']:
                raise ValueError('Fixed calibration/audit role identities changed')
    overlap_path = ROOT / 'data/processed/tess/v0/kepler_overlap.csv'
    overlap = pd.read_csv(overlap_path)
    if set(frame.tic_id.astype(str)) & set(overlap.tic_id.astype(str)):
        raise ValueError('Prepared TESS identities overlap quarantined Kepler targets')
    receipts[str(overlap_path.relative_to(ROOT))] = _sha(overlap_path)
    for path, expected in ((CHECKPOINT, CHECKPOINT_SHA), (NORMALIZER, NORMALIZER_SHA)):
        if _sha(path) != expected:
            raise ValueError('Frozen reference model or normalization changed')
        receipts[str(path.relative_to(ROOT))] = expected
    indices = np.concatenate([roles['calibration'], roles['audit']])
    selection = {}
    for role in ('calibration', 'audit'):
        subset = frame.iloc[roles[role]]
        selection[role] = {'row_indices': roles[role].tolist(), 'candidate_ids': subset.candidate_id.tolist(),
                           'groups': sorted(subset.split_group.unique().tolist()),
                           'positive': int(subset.y.sum()), 'negative': int((subset.y == 0).sum())}
        if not subset.split.eq('val').all():
            raise ValueError('Only original validation rows can enter calibration or audit')
    if (len(roles['calibration']), len(roles['audit']), selection['calibration']['positive'], selection['audit']['positive']) != (81, 82, 42, 44):
        raise ValueError('Fixed reference calibration cohort changed')
    with np.load(folder / names[0], allow_pickle=False) as archive:
        arrays = {key: archive[key][indices] for key in ('X_global', 'X_local', 'X_scalar', 'X')}
        labels = archive['y'][indices]
    if not np.array_equal(labels, frame.iloc[indices].y.to_numpy()):
        raise ValueError('Prepared labels differ from manifest identities')
    prediction = FrozenScorer(batch_size=32).predict(arrays)
    logits = np.asarray(prediction['logits'])
    boundary = len(roles['calibration'])
    fit = fit_temperature(labels[:boundary], logits[:boundary])
    audit = {'raw': metrics(labels[boundary:], logits[boundary:]),
             'calibrated': metrics(labels[boundary:], logits[boundary:], fit['temperature'])}
    rows = []
    for offset, index in enumerate(indices):
        row = frame.iloc[index]
        rows.append({'role': 'calibration' if offset < boundary else 'audit', 'row_index': int(index),
                     'candidate_id': row.candidate_id, 'star_id': str(row.star_id), 'split_group': row.split_group,
                     'label': int(labels[offset]), 'logit': float(logits[offset]),
                     'raw_score': float(expit(logits[offset])),
                     'benchmark_estimate': float(expit(logits[offset] / fit['temperature']))})
    predictions = _csv(rows, list(rows[0]))
    reliability = [{'mode': mode, **item} for mode in ('raw', 'calibrated') for item in audit[mode]['reliability']]
    sources = {relative: _sha(ROOT / relative) for relative in SOURCE_FILES}
    flat_audit = {f'{mode}_{key}': audit[mode][key]
                  for mode in ('raw', 'calibrated') for key in ('brier', 'nll', 'ece_10_equal_width')}
    calibration = {
        'schema_version': 1, 'name': 'reference_tess_benchmark_temperature_v1',
        'method': 'temperature_scaling', 'temperature': fit['temperature'],
        'model_sha256': CHECKPOINT_SHA, 'normalization_sha256': NORMALIZER_SHA, 'input_contract': 'shared_v1',
        'partition_seed': 2718, 'fit_n': boundary, 'audit_n': len(indices) - boundary,
        'fit_positive': selection['calibration']['positive'], 'audit_positive': selection['audit']['positive'],
        'fit_groups': len(selection['calibration']['groups']), 'audit_groups': len(selection['audit']['groups']),
        'positive_class': 'CP/KP label in curated TESS benchmark',
        'applicability': 'not_validated_for_blind_search', 'planet_probability': None,
        'fit': fit, 'audit': flat_audit, 'audit_reliability': audit['calibrated']['reliability'],
        'calibration_logit_range': [float(logits[:boundary].min()), float(logits[:boundary].max())],
        'source_receipts': sources, 'input_receipts': receipts,
        'selection_sha256': hashlib.sha256(_json(selection)).hexdigest(),
        'predictions_sha256': hashlib.sha256(predictions).hexdigest(),
        'limitations': [
            'Known-ephemeris labelled TESS benchmark; blind proposals have different masks, selection and prevalence.',
            'Calibration/audit groups are disjoint original-validation subsets; this is a descriptive audit, not an untouched prospective test.',
            'Small audit bins provide limited local support; a bin fraction is not an individual-object confidence interval.',
            'No calibration of astrophysical false-positive scenarios, correlated noise or survey detection selection.',
            'A transformed model output is not the actual probability that a blind proposal is a planet.',
        ],
    }
    artifact = _json(calibration)
    if len(artifact) >= 1024**2:
        raise ValueError('Calibration artifact exceeds runtime size bound')
    provenance = {'input_receipts': receipts, 'source_receipts': sources,
                  'environment': {'python': platform.python_version(), 'numpy': np.__version__,
                                  'torch': str(torch.__version__), 'scipy': scipy.__version__,
                                  'sklearn': sklearn.__version__, 'cpu_threads': 2},
                  'original_test_used': False, 'calibration_sha256': hashlib.sha256(artifact).hexdigest()}
    payloads = {'calibration.json': artifact, 'selection.json': _json(selection), 'predictions.csv': predictions,
                'audit.json': _json(audit), 'reliability.csv': _csv(reliability, list(reliability[0])),
                'provenance.json': _json(provenance)}
    # Check all existing artifacts before publishing any new ones.
    for name, payload in payloads.items():
        if (output / name).exists() and (output / name).read_bytes() != payload:
            raise ValueError('Immutable calibration artifact differs; use a new versioned output: ' + name)
    for name, payload in payloads.items():
        _publish(output / name, payload)
    return {'output': str(output), 'calibration_sha256': provenance['calibration_sha256'],
            'temperature': fit['temperature'], 'fit_n': boundary, 'audit_n': len(indices) - boundary, 'audit': flat_audit}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(rebuild(args.output), indent=2))


if __name__ == '__main__':
    main()
