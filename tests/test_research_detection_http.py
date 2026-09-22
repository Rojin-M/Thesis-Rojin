"""Actual CLI -> blind CPU subprocess -> SQLite -> loopback HTTP integration."""
import http.client
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from scripts.research.artifacts import ArtifactStore, render_plot
from scripts.research.protocol import load_protocol
from scripts.research.server import ResearchServer
from scripts.research.store import Store
from tests.test_research_detection import curve, write_npz


class DetectionHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        source = cls.root / "injected.npz"
        write_npz(source, curve())
        cls.command = [sys.executable, "-m", "scripts.research", "--db", str(cls.root / "store.sqlite3"),
                       "--artifacts", str(cls.root / "artifacts"), "detect", "--path", str(source),
                       "--mission", "TESS", "--target-id", "SYNTHETIC-HTTP", "--cohort", "synthetic_fixture",
                       "--time-system", "BTJD", "--max-period-grid", "3000", "--max-signals", "1", "--max-seconds", "30"]
        cls.environment = {**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
        ran = subprocess.run(cls.command, check=True, capture_output=True, text=True, timeout=45, env=cls.environment)
        cls.result = json.loads(ran.stdout)
        cls.candidate_id = cls.result["candidate_ids"][0]
        cls.store = Store(cls.root / "store.sqlite3").initialize()
        cls.protocol = cls.store.register_protocol(load_protocol())
        cls.artifacts = ArtifactStore(cls.root / "artifacts", cls.store)
        cls.server = ResearchServer(("127.0.0.1", 0), cls.store, cls.artifacts, cls.protocol["id"])
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def get(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", path)
        response = connection.getresponse()
        payload = response.read()
        self.assertEqual(response.status, 200)
        if response.getheader("Content-Type", "").startswith("application/json"):
            return json.loads(payload)
        return payload

    def test_actual_blind_dossier_report_plots_and_full_arrays(self):
        c = self.get("/api/candidates/" + self.candidate_id)
        self.assertEqual(c["cohort"], "synthetic_fixture")
        self.assertEqual(c["detection"]["ephemeris_origin"], "blind_search")
        self.assertLess(abs(c["ephemeris"]["period_days"] - 3.22), .01)
        self.assertIn("registry", c["incomplete_evidence"])
        self.assertIn("centroid", c["incomplete_evidence"])
        self.assertEqual(self.get("/api/overview")["detection"], "bounded_local_blind_bls_v1")
        self.assertIn(b"BJD TDB", self.get(f"/api/candidates/{self.candidate_id}/report.md"))
        for artifact in c["artifacts"]:
            payload = self.get("/api/artifacts/" + artifact["id"])
            if artifact["kind"] == "plot":
                self.assertTrue(len(payload["x"]) > 1)
                self.assertIn(b"<svg", self.get(f"/api/artifacts/{artifact['id']}/plot.svg"))
            if artifact["kind"] == "data":
                with np.load(io.BytesIO(payload), allow_pickle=False) as arrays:
                    self.assertTrue(np.all(np.diff(arrays["time_btjd"]) > 0))
                    self.assertIn("bls_1_periods", arrays.files)

    def test_cli_replay_retains_same_records_visible_over_http(self):
        replay = subprocess.run(self.command, check=True, capture_output=True, text=True, timeout=45, env=self.environment)
        self.assertEqual(json.loads(replay.stdout), self.result)
        self.assertEqual(len(self.get("/api/jobs")["items"]), 1)
        self.assertEqual(len(self.get("/api/candidates")["items"]), 1)
        j = self.get("/api/jobs/" + self.result["job_id"])
        self.assertEqual(next(s for s in j["stages"] if s["name"] == "detection")["attempts"], 1)
        self.assertEqual(next(s for s in j["stages"] if s["name"] == "features")["status"], "queued")

    def test_browser_six_connection_plot_burst_is_queued_without_losing_images(self):
        c = self.store.get_candidate(self.candidate_id)
        plot = next(a for a in c["artifacts"] if a["kind"] == "plot")
        def slow_render(value):
            time.sleep(.15)
            return render_plot(value)
        def get_plot(_):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
            try:
                connection.request("GET", f"/api/artifacts/{plot['id']}/plot.svg")
                response = connection.getresponse()
                payload = response.read()
                return response.status, payload[:4]
            finally:
                connection.close()
        # These are I/O client threads, not additional science CPU workers.
        with patch("scripts.research.server.render_plot", side_effect=slow_render):
            with ThreadPoolExecutor(max_workers=6) as clients:
                results = list(clients.map(get_plot, range(6)))
        self.assertEqual(results, [(200, b"<svg")] * 6)
