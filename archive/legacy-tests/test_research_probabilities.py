"""Semantic and integrity boundaries of experimental benchmark probabilities."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.research import probabilities as probability


class ProbabilityTests(unittest.TestCase):
    def setUp(self):
        probability._verified.cache_clear()
        self.addCleanup(probability._verified.cache_clear)
        self.evidence = {'state': 'complete', 'payload': {
            'model_sha256': probability.MODEL_SHA256,
            'normalization_sha256': probability.NORMALIZER_SHA256,
            'input_contract': 'shared_v1', 'logit': -3.412670135498047,
            'score': 0.031901828944683075}}

    def assess(self, evidence=None, **kwargs):
        return probability.probability_assessment(self.evidence if evidence is None else evidence,
            mission=kwargs.pop('mission', 'TESS'), cohort=kwargs.pop('cohort', 'archival_pilot'), **kwargs)

    def unavailable(self, result):
        self.assertIsNone(result['planet_probability'])
        self.assertEqual(result['planet_probability_status'], 'unavailable')
        self.assertTrue(result['reason'])
        self.assertEqual(result['benchmark']['status'], 'unavailable')
        self.assertIsNone(result['benchmark']['estimate'])
        self.assertTrue(result['benchmark']['reason'])

    def test_exact_reference_estimate_keeps_actual_planet_probability_unavailable(self):
        original = deepcopy(self.evidence)
        result = self.assess()
        self.assertIsNone(result['planet_probability'])
        self.assertEqual(result['planet_probability_status'], 'unavailable')
        benchmark = result['benchmark']
        self.assertEqual(benchmark['status'], 'available')
        self.assertEqual(benchmark['label'], 'Experimental TESS benchmark estimate')
        self.assertAlmostEqual(benchmark['estimate'], 0.26866907403621894, places=12)
        self.assertEqual(benchmark['applicability'], 'not_validated_for_blind_search')
        self.assertEqual((benchmark['fit_n'], benchmark['audit_n']), (81, 82))
        self.assertEqual(benchmark['support']['n'], 12)
        self.assertEqual(benchmark['support']['positive_fraction'], .5)
        self.assertIn('sparse', benchmark['reason'])
        self.assertEqual(original, self.evidence)

    def test_missing_score_wrong_model_normalizer_or_contract_are_suppressed(self):
        self.unavailable(self.assess({}))
        self.unavailable(self.assess({'state': 'incomplete'}))
        for key in ('model_sha256', 'normalization_sha256', 'input_contract'):
            changed = deepcopy(self.evidence)
            changed['payload'][key] = 'other'
            self.unavailable(self.assess(changed))

    def test_missing_nonfinite_bool_out_of_range_and_inconsistent_numbers_are_suppressed(self):
        for key in ('logit', 'score'):
            for invalid in (None, float('nan'), float('inf'), float('-inf'), True, '0.1'):
                changed = deepcopy(self.evidence)
                changed['payload'][key] = invalid
                self.unavailable(self.assess(changed))
        for score in (-.1, 1.1, .75):
            changed = deepcopy(self.evidence)
            changed['payload']['score'] = score
            self.unavailable(self.assess(changed))

    def test_non_tess_synthetic_and_unknown_cohorts_are_suppressed(self):
        for mission in ('Kepler', None, ''):
            self.unavailable(self.assess(mission=mission))
        for cohort in ('synthetic_fixture', None, 'unknown'):
            self.unavailable(self.assess(cohort=cohort))
        self.assertEqual(self.assess(cohort='known_object_control')['benchmark']['status'], 'available')

    def test_pinned_artifact_bytes_and_audit_receipts_match(self):
        payload = probability.CALIBRATION_PATH.read_bytes()
        self.assertLess(len(payload), 1024**2)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), probability.CALIBRATION_SHA256)
        record = json.loads(payload)
        folder = probability.CALIBRATION_PATH.parent
        self.assertEqual(hashlib.sha256((folder / 'selection.json').read_bytes()).hexdigest(), record['selection_sha256'])
        self.assertEqual(hashlib.sha256((folder / 'predictions.csv').read_bytes()).hexdigest(), record['predictions_sha256'])
        selection = json.loads((folder / 'selection.json').read_text())
        fit, audit = selection['calibration'], selection['audit']
        self.assertFalse(set(fit['candidate_ids']) & set(audit['candidate_ids']))
        self.assertFalse(set(fit['groups']) & set(audit['groups']))
        self.assertEqual((len(fit['groups']), len(audit['groups'])), (79, 79))
        self.assertLess(record['audit']['calibrated_brier'], record['audit']['raw_brier'])

    def test_missing_corrupt_and_oversized_calibration_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'calibration.json'
            with patch.object(probability, 'CALIBRATION_PATH', path):
                self.unavailable(self.assess())
                path.write_text('{}')
                self.unavailable(self.assess())
                path.write_bytes(b' ' * (1024**2 + 1))
                self.unavailable(self.assess())

    def test_corruption_after_successful_cached_read_is_detected_even_with_restored_mtime(self):
        original = probability.CALIBRATION_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'calibration.json'
            path.write_bytes(original)
            with patch.object(probability, 'CALIBRATION_PATH', path):
                self.assertEqual(self.assess()['benchmark']['status'], 'available')
                before = path.stat()
                path.write_bytes(b'!' + original[1:])
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                self.unavailable(self.assess())

    def test_valid_checksum_with_invalid_scientific_contract_is_still_suppressed(self):
        document = json.loads(probability.CALIBRATION_PATH.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'calibration.json'
            for field, value in [('temperature', float('nan')), ('temperature', 0), ('fit_n', 999),
                                 ('planet_probability', .5), ('applicability', 'actual_planet_probability'),
                                 ('calibration_logit_range', [float('nan'), 1]),
                                 ('calibration_logit_range', [2, 1]), ('calibration_logit_range', [1, 1])]:
                modified = {**document, field: value}
                payload = json.dumps(modified).encode()
                path.write_bytes(payload)
                with patch.object(probability, 'CALIBRATION_PATH', path), patch.object(probability, 'CALIBRATION_SHA256', hashlib.sha256(payload).hexdigest()):
                    self.unavailable(self.assess())

    def test_cached_calibration_cannot_be_changed_by_mutating_returned_assessment(self):
        result = self.assess()
        result['benchmark']['support']['n'] = 999
        result['benchmark']['audit']['raw_brier'] = 999
        following = self.assess()['benchmark']
        self.assertEqual(following['support']['n'], 12)
        self.assertLess(following['audit']['raw_brier'], 1)

    def test_large_finite_logits_are_numerically_stable_but_extrapolation_is_suppressed(self):
        for logit, score in ((1000., 1.), (-1000., 0.)):
            changed = deepcopy(self.evidence)
            changed['payload'].update(logit=logit, score=score)
            result = self.assess(changed)
            self.unavailable(result)
            self.assertIn('outside', result['benchmark']['reason'])

    def test_empty_audit_bin_suppresses_numeric_estimate(self):
        document = json.loads(probability.CALIBRATION_PATH.read_text())
        document['audit_reliability'][1]['n'] += document['audit_reliability'][2]['n']
        document['audit_reliability'][2].update(n=0, positive_fraction=None, mean_score=None)
        payload = json.dumps(document).encode()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'calibration.json'
            path.write_bytes(payload)
            with patch.object(probability, 'CALIBRATION_PATH', path), patch.object(probability, 'CALIBRATION_SHA256', hashlib.sha256(payload).hexdigest()):
                result = self.assess()
                self.unavailable(result)
                self.assertEqual(result['benchmark']['support']['n'], 0)
                self.assertIn('No held-out audit examples', result['benchmark']['reason'])

    def test_missing_artifact_after_warm_cache_is_suppressed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'calibration.json'
            path.write_bytes(probability.CALIBRATION_PATH.read_bytes())
            with patch.object(probability, 'CALIBRATION_PATH', path):
                self.assertEqual(self.assess()['benchmark']['status'], 'available')
                path.unlink()
                self.unavailable(self.assess())


if __name__ == '__main__':
    unittest.main()
