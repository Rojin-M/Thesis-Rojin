import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.experiments.ai_telescope_physical_benchmark import (
    aperture_curve, checked_record, choose_thresholds, classical_searches,
    matched_indices, physical_injection, recovery_rows, schedule,
    transit_parameters, validate_config, write_record,
)
from scripts.research.pixels import TargetPixels
from scripts.research.protocol import ROOT


def config():
    return json.loads((ROOT/"configs/ai_telescope_physical_benchmark_v1.json").read_text())


def pixels():
    t = np.arange(2880)/144
    rng = np.random.default_rng(13)
    cube = np.full((len(t), 3, 3), 20.)
    cube[:, 1, 1] = 1000*(1+rng.normal(0, .0001, len(t)))
    return TargetPixels(t, cube, np.zeros(len(t), dtype=int),
                        np.array([[0, 0, 0], [0, 2, 0], [0, 0, 0]]),
                        "42", 1, "source", "synthetic", context={})


class PhysicalBenchmarkTests(unittest.TestCase):
    def test_schedule_is_balanced_and_independent_of_host_order(self):
        cfg = config(); ids = [str(i) for i in range(90)]
        plan = schedule(ids, cfg)
        self.assertEqual(plan, schedule(ids[::-1], cfg))
        self.assertEqual({m: sum(x["mode"] == m for x in plan.values()) for m in cfg["modes"]},
                         {m: 30 for m in cfg["modes"]})
        self.assertTrue(all(22 <= sum(x["depth"] == d for x in plan.values()) <= 23 for d in cfg["depths"]))

    def test_limb_darkened_depth_and_circular_geometry(self):
        import batman
        condition = {"period_days": 5., "stellar_density_solar": 1.,
                     "impact_parameter": .5, "depth": .002}
        p, duration = transit_parameters(condition, config())
        sample = np.array([-.6*duration, -.25*duration, 0., .25*duration, .6*duration])
        loss = 1-batman.TransitModel(p, sample).light_curve(p)
        self.assertAlmostEqual(loss[2], .002, places=9)
        self.assertEqual(loss[0], 0.)
        self.assertEqual(loss[-1], 0.)
        self.assertAlmostEqual(loss[1], loss[-2], places=9)
        self.assertGreater(loss[2], loss[1])
        self.assertAlmostEqual(p.a*np.cos(np.radians(p.inc)), .5, places=9)

    def test_injection_preserves_original_and_same_aperture_signal(self):
        original = pixels(); saved = original.flux.copy()
        condition = {"period_days": 5., "stellar_density_solar": 1.,
                     "impact_parameter": .5, "depth": .002, "mode": "periodic"}
        injected, truth = physical_injection(original, condition, config())
        self.assertTrue(np.array_equal(original.flux, saved))
        self.assertEqual(len(truth["observed_centers_btjd"]), 4)
        baseline = np.median(original.flux[:, 1, 1])
        self.assertAlmostEqual(np.max(saved[:, 1, 1]-injected.flux[:, 1, 1])/baseline,
                               truth["realized_max_aperture_depth"], places=10)
        self.assertLessEqual(truth["realized_max_aperture_depth"], .002001)
        self.assertTrue(np.array_equal(injected.flux[:, 0, 0], saved[:, 0, 0]))
        flat = aperture_curve(injected, config())
        self.assertLess(flat.flux.min(), .999)

    def test_single_is_single_and_gaps_do_not_count_as_recovered_opportunities(self):
        source = pixels()
        condition = {"period_days": 60., "stellar_density_solar": 1.,
                     "impact_parameter": .5, "depth": .002, "mode": "single"}
        _, truth = physical_injection(source, condition, config())
        self.assertEqual(len(truth["planned_centers_btjd"]), 1)
        center = truth["planned_centers_btjd"][0]
        source.quality[np.abs(source.time-center) < truth["duration_hours"]/24] = 1
        _, gapped = physical_injection(source, condition, config())
        self.assertEqual(gapped["observed_centers_btjd"], [])

    def test_matching_cannot_credit_duplicates_or_distant_events(self):
        self.assertEqual(matched_indices([1., 1.01, 2.5], [1., 2.], .1), [0])
        self.assertEqual(matched_indices([1.05, 2.05], [1., 2.], .1), [0, 1])
        self.assertEqual(matched_indices([], [1.], .1), [])

    def test_original_matches_removed_and_below_threshold_baseline_rejected(self):
        cases = {name: {m: {"centers_btjd": [1.], "score": 9.}
                       for m in ("v2", "v3", "bls", "tls")}
                 for name in ("original", "injected", "inverted")}
        cases["injected"]["v3"]["centers_btjd"].append(2.)
        rows = recovery_rows([{"target_id": "42", "truth": {"mode": "periodic", "depth": .002,
            "duration_hours": 2., "observed_centers_btjd": [1., 2.]},
            "cases": cases, "exposure_days": 27.}], {"bls": 10., "tls": 8.})
        by_method = {r["method"]: r for r in rows}
        self.assertEqual(by_method["v3"]["incremental_events"], 1)
        self.assertFalse(by_method["v2"]["incremental_recovery"])
        self.assertEqual(by_method["bls"]["matched_events"], 0)
        self.assertEqual(by_method["tls"]["matched_events"], 1)

    def test_threshold_selection_counts_events_and_fails_closed(self):
        cfg = config()
        rows = [{"exposure_days": 27., "cases": {"inverted": {
            m: {"score": 8., "centers_btjd": [1., 2., 3.]}
            for m in ("bls", "tls")}}}]
        self.assertEqual(choose_thresholds(rows, cfg)["tls"]["selected_threshold"], 9.)
        cfg["tls_thresholds"] = [0., 8.]
        with self.assertRaises(ValueError):
            choose_thresholds(rows, cfg)

    def test_cache_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"case.json"
            write_record(path, {"spec_sha256": "fixed", "value": 1})
            self.assertEqual(checked_record(path, "fixed")["value"], 1)
            record = json.loads(path.read_text()); record["value"] = 2
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                checked_record(path, "fixed")

    def test_configuration_bounds_and_paths(self):
        cfg = config(); validate_config(cfg)
        for key, value in (("workers", 20), ("depths", [float("nan")]), ("output", "../elsewhere")):
            invalid = copy.deepcopy(cfg); invalid[key] = value
            with self.assertRaises(ValueError):
                validate_config(invalid)

    def test_bls_tls_recover_strong_physical_signal_on_same_grid(self):
        condition = {"period_days": 5., "stellar_density_solar": 1.,
                     "impact_parameter": .5, "depth": .005, "mode": "periodic"}
        injected, truth = physical_injection(pixels(), condition, config())
        result = classical_searches(injected, config())
        self.assertEqual(result["bls"]["periods_evaluated"], result["tls"]["periods_evaluated"])
        for m in ("bls", "tls"):
            self.assertAlmostEqual(result[m]["period_days"], 5., delta=.02)
            matched = matched_indices(result[m]["centers_btjd"], truth["observed_centers_btjd"], truth["duration_hours"]/48)
            self.assertEqual(len(matched), 4)


if __name__ == "__main__":
    unittest.main()
