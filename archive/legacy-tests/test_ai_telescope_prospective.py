import json
from pathlib import Path
import unittest

from scripts.experiments.ai_telescope_prospective import select_unreviewed, validate_config


class ProspectiveTelescopeTests(unittest.TestCase):
    def test_prior_reviews_removed_without_reordering_or_replacement(self):
        rows = [{"target_id": str(i)} for i in (7, 3, 9, 2)]
        self.assertEqual(select_unreviewed(rows, ["7"], ["8"]), rows[1:])

    def test_development_overlap_fails_instead_of_silently_changing_cohort(self):
        with self.assertRaisesRegex(ValueError, "overlaps"):
            select_unreviewed([{"target_id": "3"}], [], ["3"])

    def test_duplicate_membership_and_inconsistent_prior_cohort_rejected(self):
        for rows, prior in (([{"target_id": "3"}]*2, []), ([{"target_id": "3"}], ["4"])):
            with self.assertRaises(ValueError):
                select_unreviewed(rows, prior, [])

    def test_downloads_bounded_and_no_path_escape(self):
        config = json.loads(Path("configs/ai_telescope_prospective_v1.json").read_text())
        validate_config(config)
        for key, value in (("max_total_download_bytes", 10**15), ("target_pixel_root", "../escape")):
            with self.assertRaises(ValueError):
                validate_config({**config, key: value})


if __name__ == "__main__":
    unittest.main()
