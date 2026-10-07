"""CLI detection -> unmodified legacy features -> trained checkpoint -> actual HTTP."""
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

import numpy as np

from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import load_protocol
from scripts.research.scoring import CHECKPOINT, NORMALIZER
from scripts.research.server import ResearchServer
from scripts.research.store import Store
from tests.support import curve, write_npz


@unittest.skipUnless(CHECKPOINT.is_file() and NORMALIZER.is_file(), "Local trained checkpoint/normalizer not committed")
class VettingHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = Path(cls.tmp.name)
        path = cls.root / "synthetic.npz"; write_npz(path, curve())
        cls.base = [sys.executable, "-m", "scripts.research", "--db", str(cls.root / "research.sqlite3"),
                    "--artifacts", str(cls.root / "artifacts")]
        cls.env = {**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
        result = subprocess.run(cls.base + ["detect", "--path", str(path), "--mission", "TESS", "--target-id", "TEST-HTTP",
            "--cohort", "synthetic_fixture", "--time-system", "BTJD", "--max-period-grid", "2000", "--max-signals", "1"],
            capture_output=True, text=True, check=True, timeout=45, env=cls.env)
        detection = json.loads(result.stdout)
        cls.cid, cls.jid = detection["candidate_ids"][0], detection["job_id"]
        cls.vet_command = cls.base + ["vet", "--job-id", cls.jid, "--catalog-mode", "offline"]
        vetted = subprocess.run(cls.vet_command, capture_output=True, text=True, timeout=340, env=cls.env)
        if vetted.returncode:
            raise AssertionError(vetted.stdout + vetted.stderr)
        cls.store = Store(cls.root / "research.sqlite3").initialize()
        cls.artifacts = ArtifactStore(cls.root / "artifacts", cls.store)
        protocol = cls.store.register_protocol(load_protocol())
        cls.server = ResearchServer(("127.0.0.1", 0), cls.store, cls.artifacts, protocol["id"])
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(5); cls.tmp.cleanup()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        self.addCleanup(connection.close)
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        if response.getheader("Content-Type", "").startswith("application/json"):
            payload = json.loads(payload)
        return response.status, payload

    def test_trained_scores_and_readable_dossiers_and_arrays_over_http(self):
        status, c = self.request("GET", "/api/candidates/" + self.cid)
        self.assertEqual(status, 200)
        self.assertIsNotNone(c["assessment"]["score"])
        self.assertEqual(c["job"]["status"], "succeeded")
        self.assertIn("registry", c["incomplete_evidence"])
        _, report = self.request("GET", f"/api/candidates/{self.cid}/report.md")
        self.assertIn(b"Model ranking score", report)
        self.assertIn(b"Review attention", report)
        self.assertIn(b"Uncalibrated", report)
        _, rows = self.request("GET", "/api/candidates")
        self.assertEqual(rows["items"][0]["assessment"]["score"], c["assessment"]["score"])
        for artifact in c["artifacts"]:
            if artifact["filename"] == "shared-v1-raw-inputs.npz":
                status, payload = self.request("GET", "/api/artifacts/" + artifact["id"])
                self.assertEqual(status, 200)
                with np.load(io.BytesIO(payload), allow_pickle=False) as arrays:
                    self.assertEqual(arrays["X_global"].shape, (1, 200, 3))
                    self.assertEqual(arrays["X_local"].shape, (1, 100, 3))
                    self.assertEqual(arrays["X_scalar"].shape, (1, 7))
            if artifact["filename"] in ("X_local.json", "secondary-phase-scan.json"):
                status, svg = self.request("GET", f"/api/artifacts/{artifact['id']}/plot.svg")
                self.assertEqual(status, 200); self.assertIn(b"<svg", svg)

    def test_cli_restart_deduplicates_and_incomplete_scored_signal_still_reviewable(self):
        repeated = subprocess.run(self.vet_command, capture_output=True, text=True, check=True, timeout=15, env=self.env)
        self.assertTrue(json.loads(repeated.stdout)["jobs"][0]["already_complete"])
        _, c = self.request("GET", "/api/candidates/" + self.cid)
        _, session = self.request("GET", "/api/session")
        status, review = self.request("POST", f"/api/candidates/{self.cid}/review",
            {"status": "on_hold", "reviewer": "integration-test", "note": "Unusual scored fixture retained pending missing evidence", "expected_revision": c["revision"]},
            {"Content-Type": "application/json", "Origin": "http://127.0.0.1:" + str(self.server.server_port), "X-CSRF-Token": session["csrf_token"]})
        self.assertEqual(status, 200)
        _, current = self.request("GET", "/api/candidates/" + self.cid)
        self.assertEqual(current["review_status"], "on_hold")
        self.assertIn("centroid", current["incomplete_evidence"])
        self.assertTrue(all(s["attempts"] == 1 for s in current["job"]["stages"]))


if __name__ == "__main__":
    unittest.main()
