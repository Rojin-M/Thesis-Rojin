"""Actual loopback HTTP requests against temporary, explicitly synthetic stores."""
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from scripts.research.artifacts import ArtifactStore
from scripts.research.fixtures import seed_fixture
from scripts.research.protocol import ValidationError, load_protocol
from scripts.research.server import ResearchServer
from scripts.research.store import Store


class ResearchHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.store = Store(cls.root / "research.sqlite3").initialize()
        cls.protocol = cls.store.register_protocol(load_protocol())
        cls.artifacts = ArtifactStore(cls.root / "artifacts", cls.store)
        cls.candidate = seed_fixture(cls.store, cls.artifacts, cls.protocol["id"])
        # Fail loudly on unavailable socket permission; do not silently skip HTTP validation.
        cls.server = ResearchServer(("127.0.0.1", 0), cls.store, cls.artifacts, cls.protocol["id"])
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def request(self, path, method="GET", data=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(connection.close)
        body = raw if raw is not None else json.dumps(data) if data is not None else None
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        payload = response.read()
        content = json.loads(payload) if response.getheader("Content-Type", "").startswith("application/json") else payload
        return response.status, dict(response.getheaders()), content

    def mutation_headers(self):
        status, _, session = self.request("/api/session")
        self.assertEqual(status, 200)
        return {"Origin": self.origin, "X-CSRF-Token": session["csrf_token"], "Content-Type": "application/json"}

    def review(self, **kwargs):
        revision = self.store.get_candidate(self.candidate["id"])["revision"]
        return {"status": "in_review", "reviewer": "HTTP tester", "note": "Synthetic HTTP test", "expected_revision": revision, **kwargs}

    def test_live_health_overview_and_frontend_assets(self):
        status, headers, body = self.request("/api/health")
        self.assertEqual((status, body["status"]), (200, "ok"))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, _, body = self.request("/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(body["candidates_by_cohort"], {"synthetic_fixture": 1})
        self.assertEqual(body["release_count"], 0)
        for route, expected in (("/", b"LOCAL RESEARCH PILOT"), ("/app.js", b"/api/candidates/"), ("/style.css", b".notice")):
            status, _, body = self.request(route)
            self.assertEqual(status, 200)
            self.assertIn(expected, body)

    def test_candidate_job_details_and_filters_expose_real_failure(self):
        status, _, candidates = self.request("/api/candidates?cohort=synthetic_fixture&limit=5")
        self.assertEqual(status, 200)
        self.assertEqual(candidates["items"][0]["id"], self.candidate["id"])
        self.assertEqual(self.request("/api/candidates?cohort=archival_pilot")[2]["items"], [])
        status, _, c = self.request("/api/candidates/" + self.candidate["id"])
        self.assertEqual(status, 200)
        self.assertIn("model_score", c["incomplete_evidence"])
        status, _, j = self.request("/api/jobs/" + self.candidate["job_id"])
        self.assertEqual(status, 200)
        self.assertEqual(j["status"], "failed")
        self.assertEqual(j["stages"][4]["error"]["code"], "synthetic_failure")

    def test_review_requires_same_origin_json_and_csrf(self):
        path = f"/api/candidates/{self.candidate['id']}/review"
        valid = self.mutation_headers()
        for headers in ({}, {**valid, "Origin": "https://attacker.invalid"}, {**valid, "X-CSRF-Token": "wrong"},
                        {**valid, "Sec-Fetch-Site": "cross-site"}, {k:v for k,v in valid.items() if k != "Origin"}):
            with self.subTest(headers=list(headers)):
                self.assertEqual(self.request(path, "POST", self.review(), headers)[0], 403)
        self.assertEqual(self.request(path, "POST", self.review(), {**valid, "Content-Type": "text/plain"})[0], 400)

    def test_review_persists_then_conflicts_without_losing_history(self):
        path = f"/api/candidates/{self.candidate['id']}/review"
        data = self.review(note='<img src=x onerror="alert(1)"> literal reviewer text\nSecond line of recorded reasoning.')
        status, _, body = self.request(path, "POST", data, self.mutation_headers())
        self.assertEqual(status, 200)
        self.assertEqual(body["revision"], data["expected_revision"] + 1)
        self.assertEqual(self.request(path, "POST", data, self.mutation_headers())[0], 409)
        persisted = Store(self.store.path).get_candidate(self.candidate["id"])
        self.assertEqual(persisted["reviews"][-1]["note"], data["note"])
        self.assertTrue(persisted["incomplete_evidence"])

    def test_reports_and_plots_are_actual_artifacts_with_checksums(self):
        identifier = self.candidate["id"]
        status, headers, document = self.request(f"/api/candidates/{identifier}/report.json")
        self.assertEqual(status, 200)
        self.assertEqual(document["candidate"]["cohort"], "synthetic_fixture")
        self.assertIn("attachment", headers["Content-Disposition"])
        status, _, report = self.request(f"/api/candidates/{identifier}/report.md")
        self.assertEqual(status, 200)
        self.assertIn(b"not proof of novelty", report)
        artifact = self.candidate["artifacts"][0]
        status, _, values = self.request(f"/api/artifacts/{artifact['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(len(values["x"]), 901)
        status, headers, svg = self.request(f"/api/artifacts/{artifact['id']}/plot.svg")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/svg+xml")
        self.assertIn(b"SYNTHETIC", svg)
        self.assertEqual(svg.count(b"<circle"), 901)

    def test_dns_rebinding_paths_missing_records_and_pagination(self):
        self.assertEqual(self.request("/api/overview", headers={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.request("/api/health", headers={"Host": f"localhost:{self.port}"})[0], 200)
        for path in ("/../../README.md", "/%2e%2e/README.md", "/api/artifacts/../../research.sqlite3", "/.git/config",
                     "/api/candidates/" + "a" * 32, "/missing"):
            self.assertEqual(self.request(path)[0], 404, path)
        for path in ("/api/jobs?limit=201", "/api/jobs?offset=-1", "/api/jobs?limit=x", "/api/jobs?limit=1&limit=2",
                     "/api/candidates?cohort=unlabelled", "/api/jobs?review_status=confirmed"):
            self.assertEqual(self.request(path)[0], 400, path)

    def test_invalid_mutations_fail_visibly_without_write(self):
        path = f"/api/candidates/{self.candidate['id']}/review"
        before = self.store.get_candidate(self.candidate["id"])["revision"]
        headers = self.mutation_headers()
        for raw in ('{"status":"in_review","status":"rejected"}', '{"x": NaN}', '[1,2]', 'null', '{broken', '"' + 'x' * 66000 + '"'):
            self.assertEqual(self.request(path, "POST", headers=headers, raw=raw)[0], 400)
        for data in (self.review(status="confirmed"), self.review(expected_revision=True), self.review(note=""),
                     {**self.review(), "unexpected": 1}):
            self.assertEqual(self.request(path, "POST", data, headers)[0], 400)
        self.assertEqual(self.store.get_candidate(self.candidate["id"])["revision"], before)

    def test_retry_api_changes_only_retryable_failed_stage(self):
        code = self.candidate["job"]["code_provenance_id"]
        job = self.store.create_job(job_key="http-retry-fixture", cohort="synthetic_fixture", protocol_id=self.protocol["id"], code_provenance_id=code)
        claim = self.store.claim_stage(job["id"], "metadata", worker="test")
        self.store.finish_stage(claim["lease_token"], error={"code": "temporary_failure", "message": "Temporary test error", "retryable": True})
        data = {"stage": "metadata", "actor": "HTTP tester", "reason": "Recovery test"}
        status, _, j = self.request(f"/api/jobs/{job['id']}/retry", "POST", data, self.mutation_headers())
        self.assertEqual(status, 200)
        self.assertEqual(j["status"], "queued")
        self.assertEqual(j["attempt_history"][0]["status"], "failed")
        self.assertEqual(self.request(f"/api/jobs/{job['id']}/retry", "POST", data, self.mutation_headers())[0], 409)
        self.assertEqual(self.request(f"/api/jobs/{job['id']}/retry", "POST", {**data, "stage": {}}, self.mutation_headers())[0], 400)

    def test_service_refuses_nonloopback_binding(self):
        with self.assertRaises(ValidationError):
            ResearchServer(("0.0.0.0", 0), self.store, self.artifacts, self.protocol["id"])


class ResearchCLITests(unittest.TestCase):
    def test_cli_empty_init_status_fixture_and_export_are_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = [sys.executable, "-m", "scripts.research", "--db", str(root / "store.sqlite3"),
                       "--artifacts", str(root / "artifacts")]
            def run(*args):
                return subprocess.run([*command, *args], capture_output=True, text=True, timeout=20, check=True)
            self.assertEqual(json.loads(run("init").stdout)["jobs_by_status"], {})
            first = json.loads(run("seed-fixture").stdout)
            second = json.loads(run("seed-fixture").stdout)
            self.assertEqual(first["candidate_id"], second["candidate_id"])
            self.assertEqual(json.loads(run("status").stdout)["candidates_by_cohort"], {"synthetic_fixture": 1})
            report = root / "dossier.json"
            run("export", first["candidate_id"], "--output", str(report))
            self.assertEqual(json.loads(report.read_text())["candidate"]["id"], first["candidate_id"])
            refused = subprocess.run([*command, "export", first["candidate_id"], "--output", str(report)], capture_output=True, timeout=20)
            self.assertNotEqual(refused.returncode, 0)


if __name__ == "__main__":
    unittest.main()
