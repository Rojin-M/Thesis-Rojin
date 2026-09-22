"""Real HTTP exports from an actual small synthetic training run."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from scripts.experiments.mission_adaptation import run_suite
from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import load_protocol
from scripts.research.server import ResearchServer
from scripts.research.store import Store
from tests.test_mission_adaptation import synthetic_data


class ExperimentHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.output = cls.root / "model_experiments" / "synthetic-check"
        run_suite({"seeds":[42], "arms":["pooled","dann"], "steps":2, "pretrain_steps":1,
            "eval_every":2, "batch_size":4, "bootstrap_repeats":20,
            "max_seconds":60, "invocation_seconds":60}, cls.output, synthetic_data(),
            {"cohort":"synthetic_training_fixture"})
        cls.store = Store(cls.root / "research.sqlite3").initialize()
        protocol = cls.store.register_protocol(load_protocol())
        artifacts = ArtifactStore(cls.root / "artifacts", cls.store)
        cls.server = ResearchServer(("127.0.0.1",0), cls.store, artifacts, protocol["id"])
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval":.02}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(5); cls.tmp.cleanup()

    def request(self, path, method="GET", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(conn.close)
        conn.request(method, path, headers=headers or {})
        r = conn.getresponse(); value = r.read()
        return r.status, json.loads(value) if r.getheader("Content-Type", "").startswith("application/json") else value

    def test_actual_training_results_and_downloaded_figure(self):
        code, value = self.request("/api/experiments")
        self.assertEqual(code,200)
        row = next(r for r in value["items"] if r["id"]=="synthetic-check")
        self.assertEqual(row["status"],"complete"); self.assertTrue(row["verified"])
        self.assertEqual(row["cohort"],"synthetic_training_fixture")
        self.assertEqual(row["results"]["dann"]["n_seeds"],1)
        self.assertFalse(row["claims"]["search_ready"])
        self.assertEqual(self.request(row["links"]["report.json"])[1]["spec_sha256"],row["spec_sha256"])
        self.assertIn(b"known",self.request(row["links"]["report.md"])[1].lower())
        self.assertTrue(self.request(row["links"]["comparison.png"])[1].startswith(b"\x89PNG"))
        self.assertEqual(len(self.store.list_records("candidates")),0)
        self.assertIn(b"#experiments",self.request("/")[1])

    def test_failure_and_unverified_exports_stay_visible(self):
        pending = self.root / "model_experiments" / "failed-check"
        pending.mkdir(exist_ok=True)
        (pending / "state.json").write_text(json.dumps({"status":"failed", "attempts":1,
            "error":{"type":"TimeoutError", "message":"budget exhausted"}}))
        row = next(r for r in self.request("/api/experiments")[1]["items"] if r["id"]=="failed-check")
        self.assertFalse(row["verified"]); self.assertIsNone(row["results"])
        self.assertEqual(row["error"]["message"],"budget exhausted")
        self.assertEqual(self.request("/api/experiments/failed-check/report.json")[0],404)

    def test_corruption_is_explicit_and_never_shown_as_measured_results(self):
        path = self.output / "summary.json"
        original = path.read_bytes()
        try:
            path.write_bytes(b'{}')
            row = next(r for r in self.request("/api/experiments")[1]["items"] if r["id"]=="synthetic-check")
            self.assertEqual(row["status"],"verification_failed"); self.assertIsNone(row["results"])
            self.assertEqual(self.request("/api/experiments/synthetic-check/report.json")[0],400)
        finally:
            path.write_bytes(original)

    def test_no_launch_or_arbitrary_file_route_or_cross_origin_access(self):
        self.assertEqual(self.request("/api/experiments","POST")[0],403)
        self.assertEqual(self.request("/api/experiments",headers={"Host":"evil.example"})[0],403)
        for suffix in ("best_model.pt", "../../spec.json", "%2e%2e/spec.json", "run.lock"):
            self.assertEqual(self.request("/api/experiments/synthetic-check/"+suffix)[0],404)
        self.assertEqual(self.request("/api/experiments?path=/etc/passwd")[0],400)
        target = self.root / "model_experiments" / "linked"
        target.symlink_to(self.output, target_is_directory=True)
        try:
            self.assertEqual(self.request("/api/experiments/linked/report.json")[0],404)
            self.assertNotIn("linked",[r["id"] for r in self.request("/api/experiments")[1]["items"]])
        finally:
            target.unlink()


if __name__ == "__main__":
    unittest.main()
