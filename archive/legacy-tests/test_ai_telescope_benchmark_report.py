import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.experiments import ai_telescope_benchmark_report as report
from scripts.research.protocol import canonical_json


def documents():
    spec = {"targets": {
        "calibration": [{"target_id": "1"}, {"target_id": "2"}],
        "evaluation": [{"target_id": str(i)} for i in (3, 4, 5)]},
        "neural_thresholds": {"v2": .9, "v3": .86},
        "config": {"target_control_events_per_27_days": .3}}
    thresholds = {"v2": .9, "v3": .86, "bls": 7.5, "tls": 6.}
    summary = {"registered_hosts": 3, "thresholds": thresholds,
               "methods": {m: {"registered_hosts": 3, "incremental_hosts": 1,
                               "hosts_with_observable_injection": 2}
                           for m in thresholds}}
    operating = {"calibration_hosts": 2, "neural": spec["neural_thresholds"].copy(),
                 "classical": {m: {"selected_threshold": thresholds[m]} for m in ("bls", "tls")}}
    return spec, summary, operating


class BenchmarkReportTests(unittest.TestCase):
    def test_nondefault_cohort_and_thresholds_come_from_frozen_inputs(self):
        metadata = report.report_metadata(*documents())
        self.assertEqual(metadata["registered_hosts"], 3)
        self.assertEqual(metadata["calibration_hosts"], 2)
        self.assertEqual(metadata["observable_hosts"], 2)
        self.assertEqual(metadata["unobservable_hosts"], 1)
        self.assertEqual(metadata["control_budget"], .3)
        self.assertEqual(metadata["thresholds"]["bls"], 7.5)

    def test_changed_operating_point_cannot_be_published_as_frozen(self):
        spec, summary, operating = documents()
        operating["classical"]["bls"]["selected_threshold"] = 9.
        with self.assertRaisesRegex(ValueError, "thresholds"):
            report.report_metadata(spec, summary, operating)

    def test_duplicate_or_overlapping_hosts_are_rejected(self):
        for bad_id in ("3", "1"):
            spec, summary, operating = documents()
            spec["targets"]["evaluation"][1]["target_id"] = bad_id
            with self.assertRaises(ValueError):
                report.report_metadata(spec, summary, operating)

    def test_missing_host_or_inconsistent_observable_denominator_is_rejected(self):
        for field, value in (("registered_hosts", 2), ("hosts_with_observable_injection", 1),
                             ("incremental_hosts", 3)):
            spec, summary, operating = documents()
            summary["methods"]["v3"][field] = value
            with self.assertRaises(ValueError):
                report.report_metadata(spec, summary, operating)

    def test_mixed_specifications_are_rejected_even_with_individually_valid_files(self):
        spec, summary, operating = documents()
        checksum = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
        summary["spec_sha256"] = operating["spec_sha256"] = checksum
        receipt = {"spec_sha256": checksum}
        report.verify_spec_binding(spec, summary, operating, receipt)
        wrong = copy.deepcopy(operating); wrong["spec_sha256"] = "another-run"
        with self.assertRaisesRegex(ValueError, "different frozen specifications"):
            report.verify_spec_binding(spec, summary, wrong, receipt)

    def test_export_cannot_write_into_or_above_the_frozen_run(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(report, "ROOT", Path(directory)):
            for output in ("run", "run/export", "."):
                with self.assertRaises(ValueError):
                    report.report_paths("run", output)
            with self.assertRaises(ValueError):
                report.report_paths("run/nested", "run")
            self.assertEqual(report.report_paths("run", "results/report")[1],
                             Path(directory)/"results/report")

    def test_symlink_cannot_redirect_export_into_frozen_artifacts(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(report, "ROOT", Path(directory)):
            root = Path(directory); (root/"run").mkdir()
            (root/"alias").symlink_to(root/"run", target_is_directory=True)
            with self.assertRaises(ValueError):
                report.report_paths("run", "alias")


if __name__ == "__main__":
    unittest.main()
