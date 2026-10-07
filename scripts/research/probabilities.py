"""Lightweight, pinned benchmark calibration; never an actual planet posterior."""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

CALIBRATION_RELATIVE_PATH = 'results/reference_calibration_v1/calibration.json'
CALIBRATION_PATH = Path(__file__).resolve().parents[2] / CALIBRATION_RELATIVE_PATH
CALIBRATION_SHA256 = '5aec4e2e3c4743790436c17309bb89851ce942efa2274eae75862ec4d215fdaf'
MODEL_SHA256 = '7890efd17fc072efb74465a9fbfa6fb8b0192388d91af520961349f0066ba703'
NORMALIZER_SHA256 = '6f4ac773f6f2dd6c2200e68b903acb0c7a3f585a593ac2d882c03af03c705dc1'
MAX_CALIBRATION_BYTES = 1024**2
PLANET_REASON = ('Actual planet probability is unavailable: this search has no validated probability model '
                 'covering astrophysical false positives, detection selection and the blind-search population.')


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _sigmoid(value):
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1 + exponential)


@lru_cache(maxsize=4)
def _verified(raw, expected_sha):
    # Cache by immutable content, not filesystem timestamps: some filesystems
    # retain the same timestamp across a fast same-length replacement.
    if not raw or len(raw) > MAX_CALIBRATION_BYTES:
        raise ValueError('Calibration artifact size is invalid')
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('Calibration artifact checksum does not match the pinned release')
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get('schema_version') != 1
            or value.get('method') != 'temperature_scaling'
            or value.get('model_sha256') != MODEL_SHA256
            or value.get('normalization_sha256') != NORMALIZER_SHA256
            or value.get('input_contract') != 'shared_v1'
            or value.get('applicability') != 'not_validated_for_blind_search'
            or value.get('planet_probability', 'missing') is not None
            or (value.get('fit_n'), value.get('audit_n')) != (81, 82)
            or not _number(value.get('temperature')) or not .05 <= value['temperature'] <= 20):
        raise ValueError('Calibration artifact does not satisfy the frozen benchmark contract')
    for key in ('raw_brier', 'calibrated_brier', 'raw_nll', 'calibrated_nll'):
        if not _number(value.get('audit', {}).get(key)):
            raise ValueError('Calibration audit metrics are missing or nonfinite')
    limits = value.get('calibration_logit_range')
    if (not isinstance(limits, list) or len(limits) != 2
            or not all(_number(limit) for limit in limits) or not limits[0] < limits[1]):
        raise ValueError('Calibration logit support is missing or invalid')
    bins = value.get('audit_reliability')
    if (not isinstance(bins, list) or len(bins) != 10
            or any(not isinstance(row, dict) or type(row.get('n')) is not int or row['n'] < 0
                   or not _number(row.get('lower')) or not _number(row.get('upper'))
                   or row['lower'] != index / 10 or row['upper'] != (index + 1) / 10
                   or (row['n'] and (not _number(row.get('positive_fraction'))
                                    or not 0 <= row['positive_fraction'] <= 1))
                   for index, row in enumerate(bins))
            or sum(row['n'] for row in bins) != 82):
        raise ValueError('Calibration audit reliability bins are invalid')
    return value


def _load():
    path = Path(CALIBRATION_PATH)
    stat = path.stat()
    if stat.st_size <= 0 or stat.st_size > MAX_CALIBRATION_BYTES:
        raise ValueError('Calibration artifact is empty or exceeds 1 MiB')
    with path.open('rb') as handle:
        raw = handle.read(MAX_CALIBRATION_BYTES + 1)
    if len(raw) != stat.st_size:
        raise ValueError('Calibration artifact changed while being read')
    return _verified(raw, CALIBRATION_SHA256)


def probability_assessment(model_evidence, *, mission=None, cohort=None):
    """Assess one unchanged frozen score with explicit scope and failure reasons."""
    benchmark = {'status': 'unavailable', 'estimate': None,
                 'label': 'Experimental TESS benchmark estimate', 'reason': '',
                 'calibration_id': CALIBRATION_SHA256, 'method': 'temperature_scaling',
                 'calibration_artifact': CALIBRATION_RELATIVE_PATH,
                 'temperature': None, 'fit_n': None, 'audit_n': None,
                 'positive_class': 'CP/KP label in curated TESS benchmark',
                 'applicability': 'not_validated_for_blind_search', 'audit': {}, 'support': None}
    result = {'planet_probability': None, 'planet_probability_status': 'unavailable',
              'reason': PLANET_REASON, 'benchmark': benchmark,
              'derived_annotation': 'read_time_calculation_not_persisted_candidate_evidence'}

    def unavailable(reason):
        benchmark['reason'] = reason
        return result

    if mission != 'TESS':
        return unavailable('The calibrator applies only to TESS benchmark inputs; mission is absent or unsupported.')
    if cohort == 'synthetic_fixture':
        return unavailable('Synthetic or transformed controls do not receive a sky-candidate benchmark estimate.')
    if cohort not in ('known_object_control', 'archival_pilot', 'prospective_search'):
        return unavailable('The candidate cohort is absent or unsupported for this benchmark estimate.')
    if not isinstance(model_evidence, dict) or model_evidence.get('state') != 'complete':
        return unavailable('A complete verified reference CNN score is required.')
    payload = model_evidence.get('payload')
    if not isinstance(payload, dict):
        return unavailable('Reference CNN score metadata is unavailable.')
    if (payload.get('model_sha256') != MODEL_SHA256 or payload.get('normalization_sha256') != NORMALIZER_SHA256
            or payload.get('input_contract') != 'shared_v1'):
        return unavailable('Checkpoint, normalization or input contract differs from this exact reference calibrator.')
    logit, score = payload.get('logit'), payload.get('score')
    if not _number(logit) or not _number(score) or not 0 <= score <= 1:
        return unavailable('The reference score and logit must both be finite and valid.')
    if not math.isclose(_sigmoid(logit), score, rel_tol=1e-5, abs_tol=1e-7):
        return unavailable('The recorded score is inconsistent with its reference logit.')
    try:
        calibration = _load()
    except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
        return unavailable('Verified calibration unavailable: ' + str(exc))
    benchmark.update(temperature=calibration['temperature'], fit_n=calibration['fit_n'], audit_n=calibration['audit_n'],
                     audit={key: calibration['audit'][key] for key in
                            ('raw_brier', 'calibrated_brier', 'raw_nll', 'calibrated_nll')})
    low, high = calibration['calibration_logit_range']
    if not low <= logit <= high:
        return unavailable('The reference logit is outside the observed calibration support; no numeric estimate is reported.')
    estimate = _sigmoid(logit / calibration['temperature'])
    support = dict(calibration['audit_reliability'][min(int(estimate * 10), 9)])
    support['interpretation'] = 'Labelled audit examples in this estimate bin; not an individual-object confidence interval.'
    benchmark['support'] = support
    if support['n'] == 0:
        return unavailable('No held-out audit examples support this estimate range; no numeric estimate is reported.')
    reason = ('Temperature-scaled reference output for CP/KP versus FP/FA labels in a curated TESS benchmark. '
              'Different search selection, class prevalence and inferred ephemerides prevent interpreting it as a planet probability. ')
    reason += (f'This audit bin contains only {support["n"]} examples; local support is sparse.'
               if support['n'] < 20 else f'This audit bin contains {support["n"]} examples.')
    benchmark.update(status='available', estimate=estimate, reason=reason)
    return result
