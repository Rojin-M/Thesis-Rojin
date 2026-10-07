import unittest

import numpy as np

from scripts.experiments.ai_telescope_blind_scan import (
    annotate_events,
    group_events,
    scan_starts,
    validate_config,
)


class AITelescopeBlindScanTests(unittest.TestCase):
    def test_scan_starts_cover_both_edges_without_gaps(self):
        starts = scan_starts(1000, 256, 128)
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts[-1], 744)
        covered = np.zeros(1000, dtype=bool)
        for start in starts:
            covered[start:start + 256] = True
        self.assertTrue(covered.all())

    def test_group_events_merges_short_gaps_and_rejects_singletons(self):
        score = np.zeros(20, dtype=float)
        score[[3, 4, 6, 12]] = [.8, .9, .85, .99]
        events = group_events(score, np.ones(20, dtype=bool), .75, merge_gap=1,
                              minimum_cadences=2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["peak_index"], 4)
        self.assertEqual(events[0]["cadences_above_threshold"], 3)

    def test_ephemeris_annotation_happens_after_event_detection(self):
        time = np.arange(20, dtype=float)
        events = [{"start_index": 4, "end_index": 6, "peak_index": 5,
                   "cadences_above_threshold": 3, "max_probability": .9,
                   "mean_probability": .85}]
        candidates = [{"candidate_id": "TOI-X.01", "period_days": 10,
                       "epoch_bjd_tdb": 2457005., "duration_hours": 4,
                       "label": 1}]
        result = annotate_events(events, time, candidates)
        self.assertEqual(result[0]["matched_candidate_ids"], ["TOI-X.01"])
        self.assertGreater(result[0]["review_score"], result[0]["max_probability"])

    def test_config_rejects_stride_gaps(self):
        value = {"schema_version": 1, "model_run": "a", "physical_run": "b", "output": "c",
                 "window_length": 256, "pixel_frames": 32, "spatial_size": 11,
                 "stride": 512, "batch_size": 8, "maximum_events_per_target": 10,
                 "top_unmatched": 100, "merge_gap_cadences": 2,
                 "minimum_event_cadences": 2, "cpu_threads": 2}
        with self.assertRaises(ValueError):
            validate_config(value)


if __name__ == "__main__":
    unittest.main()
