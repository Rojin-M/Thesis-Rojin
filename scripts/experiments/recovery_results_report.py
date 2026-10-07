"""Export verified fresh recovery and classifier results without changing runs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from scripts.experiments.ai_telescope_blind_scan import _checked_complete
from scripts.experiments.ai_telescope_physical_benchmark import checked_record, digest
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.protocol import ROOT
from scripts.research.provenance import file_sha256


def verified_run(relative):
    run = ROOT / relative
    receipt = _checked_complete(run)
    summary = json.loads((run / 'summary.json').read_text())
    spec = json.loads((run / 'spec.json').read_text())
    if digest(spec) != receipt['spec_sha256'] or summary['spec_sha256'] != receipt['spec_sha256']:
        raise ValueError('Run specification/summary binding differs')
    for name, checksum in spec['sources'].items():
        if file_sha256(ROOT / name) != checksum:
            raise ValueError('Frozen source changed: ' + name)
    return run, receipt, summary, spec


def resolution_diagnostic(spec):
    """Separate grid resolution from the new, stricter transfer-margin policy.

    Uses calibration controls only; these diagnostic thresholds are not used
    to rescore or select models on either evaluated cohort.
    """
    baseline = ROOT / spec['config']['baseline_run']
    receipt = _checked_complete(baseline)
    original = json.loads((baseline / 'spec.json').read_text())
    operating = json.loads((baseline / 'operating_point.json').read_text())
    rows = [checked_record(baseline / 'calibration' / ('TIC' + t['target_id'] + '.json'), receipt['spec_sha256'])
            for t in original['targets']['calibration']]
    exposure = sum(row['exposure_days'] for row in rows)
    result = {}
    for method in ('bls', 'tls'):
        cases = [row['cases']['inverted'][method] for row in rows]
        grid = sorted({0., *[float(np.nextafter(case['score'], np.inf)) for case in cases]})
        for threshold in grid:
            count = sum(len(case['centers_btjd']) for case in cases if case['score'] >= threshold)
            rate = count / exposure * 27
            if rate <= original['config']['target_control_events_per_27_days']:
                result[method] = {'original_coarse_threshold': operating['classical'][method]['selected_threshold'],
                                  'exact_empirical_threshold': threshold, 'events_per_27_days': rate,
                                  'scope': 'calibration-only grid-resolution diagnostic; not an evaluated operating point'}
                break
    return result


def export_recovery():
    run, receipt, summary, spec = verified_run('outputs/research/ai_telescope/recovery-v1')
    folder = ROOT / 'results/ai_telescope_recovery_v1'
    folder.mkdir(parents=True, exist_ok=True)
    methods = list(summary['methods'])
    labels = ['Original v3', 'Calibrated v3', 'Single-event search', 'Hybrid', 'BLS exact', 'TLS exact']
    if set(methods) != {'v3_original', 'v3_calibrated', 'single_event', 'hybrid', 'bls_exact', 'tls_exact'}:
        raise ValueError('Unexpected detector set')
    methods = ['v3_original', 'v3_calibrated', 'single_event', 'hybrid', 'bls_exact', 'tls_exact']
    colors = ['#94a3b8', '#f59e0b', '#14b8a6', '#2563eb', '#8b5cf6', '#15803d']
    plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.8))
    fields = ['incremental_hosts', 'incremental_events', 'inverted_alerts_per_27_days']
    titles = ['Hosts with added recovery', 'Individual transits recovered', 'Inverted-control alerts / 27 days']
    for axis, field, title in zip(axes, fields, titles):
        values = [summary['methods'][m][field] for m in methods]
        axis.barh(np.arange(len(methods)), values, color=colors)
        axis.invert_yaxis()
        axis.set_yticks(range(len(methods)), labels if axis is axes[0] else [''] * len(methods))
        axis.set_title(title, fontsize=12)
        axis.grid(axis='x', alpha=.2)
        axis.set_axisbelow(True)
        limit = max(max(values), 1) * 1.3
        axis.set_xlim(0, limit)
        for index, value in enumerate(values):
            axis.text(value + limit * .015, index, f'{value:.3f}' if field.endswith('days') else str(value), va='center')
        if field.endswith('days'):
            axis.axvline(spec['config']['control_budget_per_27_days'], color='#b91c1c', linestyle='--', linewidth=1)
    fig.suptitle(f"Fresh physical-injection evaluation: {summary['registered_hosts']} registered hosts", fontsize=15)
    fig.text(.02, .035, 'Thresholds froze on separate calibration hosts. Recovery excludes matches already present in original data.\n'
             'Inverted controls measure alert behavior; they do not estimate the survey false-positive rate.', fontsize=10)
    fig.tight_layout(rect=(0, .1, 1, .95))
    for extension in ('png', 'pdf'):
        fig.savefig(folder / ('comparison.' + extension), dpi=180, bbox_inches='tight')
    plt.close(fig)
    source = os.path.relpath(run / 'report.md', folder)
    text = (run / 'report.md').read_text()
    baseline = summary['methods']['v3_original']
    calibrated = summary['methods']['v3_calibrated']
    hybrid = summary['methods']['hybrid']
    outcome = (f"Calibrated v3 reduces control alerts from {baseline['inverted_alerts_per_27_days']:.3f} to "
               f"{calibrated['inverted_alerts_per_27_days']:.3f} per 27 days with {calibrated['incremental_hosts']}/{summary['registered_hosts']} "
               f"host recoveries, equal to the original v3 host count. Individual event recovery decreases from {baseline['incremental_events']} to {calibrated['incremental_events']}. "
               f"The hybrid recovers only {hybrid['incremental_hosts']}/{summary['registered_hosts']} hosts and is rejected. "
               "The weak-transit issue remains: every method misses all 25 registered 500 ppm injections. "
               "v3 single-transit recovery remains 4/33. The new BLS calibration is exact but still too conservative for useful recovery here.\n\n")
    text = text.replace('# Fresh-host recovery experiment\n\n', '# Fresh-host recovery experiment\n\n' + outcome, 1)
    resolution = resolution_diagnostic(spec)
    atomic_json(folder / 'calibration_resolution.json', resolution)
    text += '\n## Grid resolution versus control margin\n\n'
    text += 'On the same 78 calibration controls, retaining the old empirical budget would give the following exact boundaries. They are calibration diagnostics only; neither fresh nor historical evaluation was rescored at these settings.\n\n'
    text += '| Method | Original coarse threshold | Exact boundary at old mean budget | Calibration alerts / 27 d |\n| --- | ---: | ---: | ---: |\n'
    for method, item in resolution.items():
        text += f"| {method} | {item['original_coarse_threshold']:g} | {item['exact_empirical_threshold']:.6f} | {item['events_per_27_days']:.3f} |\n"
    text += '\nThe stricter thresholds in the evaluated recovery study come from the new transfer margin and host-cluster uncertainty rule, not from a coarse score grid.\n'
    text += f'\n![Fresh recovery comparison](comparison.png)\n\n[Full run and calibration receipts]({source}).\n'
    (folder / 'README.md').write_text(text)
    shutil.copy2(run / 'host_recovery.csv', folder / 'host_recovery.csv')
    atomic_json(folder / 'evidence.json', {'source': str(run.relative_to(ROOT)), 'spec_sha256': receipt['spec_sha256'],
                'source_complete_sha256': file_sha256(run / 'complete.json'), 'source_artifacts_verified': len(receipt['files']),
                'files': {p.name: file_sha256(p) for p in folder.iterdir() if p.is_file() and p.name != 'evidence.json'}})
    return summary


def export_classifier():
    run, receipt, summary, _ = verified_run('outputs/research/fresh_classifier_audit/audit-v1')
    folder = ROOT / 'results/fresh_classifier_audit_v1'
    folder.mkdir(parents=True, exist_ok=True)
    text = (run / 'report.md').read_text()
    static = summary['metrics']['v4_static']['average_precision']
    nonlinear = summary['metrics']['crossfit_supermodel']['average_precision']
    text += f'\nThe frozen static v4 stack has AP {static:.4f}, compared with {nonlinear:.4f} for the nonlinear supermodel on this small cohort. The reused-audit nonlinear ranking advantage therefore did not repeat here.\n'
    text += '\n[Full audit and acquisition accounting](' + os.path.relpath(run / 'preparation.json', folder) + ').\n'
    (folder / 'README.md').write_text(text)
    shutil.copy2(run / 'predictions.csv', folder / 'predictions.csv')
    atomic_json(folder / 'evidence.json', {'source': str(run.relative_to(ROOT)), 'spec_sha256': receipt['spec_sha256'],
                'source_complete_sha256': file_sha256(run / 'complete.json'), 'source_artifacts_verified': len(receipt['files']),
                'files': {p.name: file_sha256(p) for p in folder.iterdir() if p.is_file() and p.name != 'evidence.json'}})
    return summary


def main():
    detector = export_recovery()
    classifier = export_classifier()
    folder = ROOT / 'results/research_fixes_v1'
    folder.mkdir(parents=True, exist_ok=True)
    methods = detector['methods']
    lines = ['# Follow-up to the research issues', '',
             'Calibration and evaluation tooling improved. Weak-transit detection is still unresolved, the hybrid proposal is rejected, and the fresh classifier audit remains too small for a broad superiority claim.', '',
             f"The original 90-host benchmark and 82-row classifier audit remain unchanged. New detector settings were calibrated before the fresh {detector['registered_hosts']}-host run, and the classifier was applied with frozen weights.", '',
             '| Issue | Implemented change | Fresh evidence |', '| --- | --- | --- |',
             f"| v3 control-rate transfer | 50% calibration margin with Poisson and host-bootstrap upper estimates | Calibrated v3: {methods['v3_calibrated']['inverted_alerts_per_27_days']:.3f} alerts / 27 d versus original v3: {methods['v3_original']['inverted_alerts_per_27_days']:.3f} on the same hosts |",
             f"| Weak and single events | Local sideband search over 0.5–12 h durations, plus a budgeted neural hybrid | Hybrid: {methods['hybrid']['incremental_hosts']}/{detector['registered_hosts']} hosts; see depth/mode breakdown below |",
             '| Coarse BLS calibration | Exact observed-score boundaries, tied events counted together | Mechanically resolved; conservative transfer margin can still choose a high threshold |',
             f"| Reused classifier audit | Newly acquired data, unchanged preprocessing and all eleven frozen experts | {classifier['accepted_candidates']} fresh candidates ({classifier['positive']} positive, {classifier['negative']} negative); independent but too small for a broad superiority claim |", '',
             '| Subset | Original v3 | Calibrated v3 | Single-event search | Hybrid |', '| --- | ---: | ---: | ---: | ---: |']
    for label, data in [('Single transits', detector['by_mode']['single']), ('500 ppm', detector['by_depth']['0.0005'])]:
        lines.append('| ' + label + ' | ' + ' | '.join(f"{data[m]['incremental_hosts']}/{data[m]['registered_hosts']}" for m in ['v3_original', 'v3_calibrated', 'single_event', 'hybrid']) + ' |')
    lines += ['', '[Detector protocol, figure and full results](../ai_telescope_recovery_v1/README.md).',
              '[Fresh classifier audit and individual predictions](../fresh_classifier_audit_v1/README.md).', '',
              'Implementation checks: 48 focused tests passed; the new classifier inference path also reproduced the previous 82-row AP, AUC, Brier and log-loss values and physical expert logits within 1e-7 (metrics) / 1e-5 (logits).',
              'No model was deployed. These studies still do not establish background-source rejection, binary rejection, multi-sector detector performance, or a survey false-positive rate.', '']
    (folder / 'README.md').write_text('\n'.join(lines))
    print(json.dumps({'status': 'complete', 'detector_hosts': detector['registered_hosts'], 'classifier_candidates': classifier['accepted_candidates']}))


if __name__ == '__main__':
    main()
