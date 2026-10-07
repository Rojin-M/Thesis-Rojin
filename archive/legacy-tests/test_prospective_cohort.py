import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.experiments.freeze_prospective_cohort import candidate_targets


class ProspectiveCohortTests(unittest.TestCase):
    def test_candidate_exclusions_read_only_existing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE candidates(target_id TEXT)")
                db.executemany("INSERT INTO candidates VALUES (?)", [("123",), ("TIC456",), ("123",)])
            self.assertEqual(candidate_targets(path), {"123", "TIC456"})
            self.assertEqual(candidate_targets(Path(tmp) / "missing.sqlite3"), set())


if __name__ == "__main__": unittest.main()
