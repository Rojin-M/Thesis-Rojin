"""Offline automatic watcher replay, persistent controls and bounded retries."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.research import automation, mast
from scripts.research.artifacts import ArtifactStore
from scripts.research.automation import run_cycle, validate_config
from scripts.research.protocol import ConflictError, STAGES, ValidationError, load_protocol
from scripts.research.store import Store
from scripts.research.watcher import create_pilot, load_config, poll_once
from scripts.research.watcher_store import WatchStore, status
from tests.test_research_detection import write_fits
from tests.test_research_watcher import ReplayClient


class OfflineArchiveSession:
    def __init__(self, fixture, source):
        self.fixture = fixture
        self.source = source
        self.headers = {}
        self.downloads = 0
        self.transferred = 0
        self.requests = 0

    def request(self, method, url, **kwargs):
        self.requests += 1
        if method == "POST":
            payload = self.fixture.query(json.loads(kwargs["data"]["request"]))
        else:
            self.downloads += 1
            payload = self.source.read_bytes()
        self.transferred += len(payload)
        stream = io.BytesIO(payload)

        class Response:
            status_code = 200
            headers = {"Content-Length": str(len(payload))}
            raw = SimpleNamespace(read=lambda amount, **options: stream.read(amount))

            def __enter__(self):
                return self

            def __exit__(self, *args):
                stream.close()

        return Response()


class AutomaticWatcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "fixture.fits"
        write_fits(self.source)
        self.store = Store(self.root / "research.sqlite3").initialize()
        self.protocol = self.store.register_protocol(load_protocol())
        self.artifacts = ArtifactStore(self.root / "artifacts", self.store)
        self.client = ReplayClient(self.source, size=self.source.stat().st_size)
        self.config = {
            "schema_version": 1,
            "targets": ["123"],
            "poll_seconds": 21600,
            "poll_max_seconds": 120,
            "cohort": "archival_pilot",
            "product_max_bytes": 64 * 1024**2,
            "product_max_seconds": 900,
            "max_products_per_cycle": 2,
            "cycle_max_seconds": 1500,
            "catalog_mode": "offline",
        }
        self.processed = []
        self.addCleanup(patch.stopall)
        patch("requests.sessions.Session.request", side_effect=AssertionError("Public network forbidden in replay")).start()
        patch("scripts.research.local_selection.cached_tess_paths", return_value=[]).start()

    def processor(self, store, artifacts, product, receipt, pilot):
        self.processed.append(product["id"])
        self.assertTrue(Path(receipt["path"]).is_file())
        job = store.create_job(
            job_key="watch-bls-v1:" + product["id"],
            cohort=pilot["spec"]["cohort"],
            protocol_id=self.protocol["id"],
            code_provenance_id=product["provenance_id"],
            release_id=product["release_id"],
            product_id=product["id"],
            inputs={"fixture_only": True},
        )
        store.put_candidate(
            job_id=job["id"], signal_key="fixture-1", target_id=product["target_id"],
            mission="TESS", period_days=3.22, epoch=1501.1, epoch_system="BTJD", duration_hours=2.88,
            detection={"method": "fixture_processor", "ephemeris_origin": "blind_search",
                       "used_catalog_ephemeris": False, "fixture_only": True},
            provenance_id=product["provenance_id"],
        )
        for stage in STAGES:
            claim = store.claim_stage(job["id"], stage, worker="offline-automation-fixture")
            if claim is not None:
                store.finish_stage(claim["lease_token"], result={"fixture_only": True})
        return job["id"]

    def cycle(self, **kwargs):
        return run_cycle(self.store, self.artifacts, self.protocol["id"], self.config,
                         client=self.client, processor=kwargs.pop("processor", self.processor), **kwargs)

    def restart(self):
        self.store = Store(self.store.path).initialize()
        self.artifacts = ArtifactStore(self.root / "artifacts", self.store)

    def test_automatic_acquisition_candidate_and_restart_are_idempotent(self):
        self.cycle(force=True)
        first = status(self.store)
        self.assertEqual(len(first["queue"]), 1)
        self.assertEqual(first["queue"][0]["state"], "complete")
        self.assertEqual(self.client.downloads, 1)
        candidates = self.store.list_records("candidates")
        self.assertEqual(len(candidates), 1)
        candidate_id = candidates[0]["id"]
        self.assertEqual(candidates[0]["cohort"], "archival_pilot")
        calls = len(self.client.calls)
        self.restart()
        self.cycle()
        self.assertEqual(len(self.client.calls), calls)
        self.client.scenario = "duplicate"
        self.cycle(force=True)
        self.assertEqual(self.client.downloads, 1)
        self.assertEqual(len(self.processed), 1)
        self.assertEqual(len(status(self.store)["pilots"]), 1)
        self.assertEqual(self.store.list_records("candidates")[0]["id"], candidate_id)

    def test_new_release_and_reprocessing_each_add_only_one_product(self):
        self.cycle(force=True)
        original = self.store.list_records("candidates")[0]
        for scenario in ("reprocessed", "new_release"):
            self.client.scenario = scenario
            self.cycle(force=True)
            self.cycle(force=True)
        snapshot = status(self.store)
        self.assertEqual(len(snapshot["queue"]), 3)
        self.assertTrue(all(row["state"] == "complete" for row in snapshot["queue"]))
        self.assertEqual(self.client.downloads, 3)
        self.assertEqual(len(self.processed), 3)
        self.assertEqual(len(self.store.list_records("candidates")), 3)
        self.assertEqual(self.store.get_candidate(original["id"])["ephemeris"], original["ephemeris"])

    def test_metadata_only_command_stays_inert_until_automatic_cycle(self):
        poll_once(self.store, {**load_config(), "targets": ["123"]}, client=self.client, force=True)
        self.assertEqual(status(self.store)["queue"], [])
        self.assertEqual(self.client.downloads, 0)
        self.cycle(force=True)
        self.assertEqual(len(self.store.list_records("candidates")), 1)

    def test_all_target_batches_polled_with_stable_configuration_ids(self):
        self.config["targets"] = ["123", "456", "789"]
        original_query = self.client.query

        def selected_targets(request):
            page = json.loads(original_query(request))
            if request["service"] == "Mast.Caom.Filtered":
                targets = next(field["values"] for field in request["params"]["filters"]
                               if field["paramName"] == "target_name")
                page["data"] = [row for row in page["data"] if row["target_name"] in targets]
                page["paging"]["rowsFiltered"] = len(page["data"])
            return json.dumps(page).encode()

        self.client.query = selected_targets
        self.cycle(force=True)
        requests = [request for request in self.client.calls if request["service"] == "Mast.Caom.Filtered"]
        batches = [next(field["values"] for field in request["params"]["filters"]
                        if field["paramName"] == "target_name") for request in requests]
        self.assertEqual(batches, [["123", "456"], ["789"]])
        first_ids = {row["id"] for row in status(self.store)["configs"]}
        self.assertEqual(len(first_ids), 2)
        self.restart()
        self.cycle(force=True)
        self.assertEqual({row["id"] for row in status(self.store)["configs"]}, first_ids)
        self.assertEqual(self.client.downloads, 1)

    def test_retry_waits_then_reuses_receipt_after_restart(self):
        def interrupted(*args):
            raise OSError("fixture downstream interruption")

        self.cycle(force=True, processor=interrupted)
        failed = status(self.store)["queue"][0]
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["attempts"], 1)
        self.assertIsNotNone(failed["next_attempt_at"])
        self.assertEqual(self.client.downloads, 1)
        self.restart()
        self.cycle(processor=interrupted)
        self.assertEqual(status(self.store)["queue"][0]["attempts"], 1)
        WatchStore(self.store).queue(failed["product_id"], next_attempt_at=None)
        self.cycle()
        completed = status(self.store)["queue"][0]
        self.assertEqual(completed["state"], "complete")
        self.assertEqual(completed["attempts"], 2)
        self.assertEqual(self.client.downloads, 1)
        self.assertEqual(len(self.store.list_records("candidates")), 1)

    def test_three_failures_stop_dispatch_even_after_forced_polls(self):
        attempts = []

        def interrupted(*args):
            attempts.append(True)
            raise OSError("fixture repeated interruption")

        for attempt in range(1, 4):
            self.cycle(force=True, processor=interrupted)
            queued = status(self.store)["queue"][0]
            self.assertEqual(queued["attempts"], attempt)
            WatchStore(self.store).queue(queued["product_id"], next_attempt_at=None)
        self.cycle(force=True, processor=interrupted)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(self.client.downloads, 1)
        self.assertEqual(len(status(self.store)["pilots"]), 1)

    def test_nonretryable_processing_failure_does_not_loop(self):
        attempts = []

        def invalid(*args):
            attempts.append(True)
            raise ValidationError("fixture source requires inspection")

        self.cycle(force=True, processor=invalid)
        queued = status(self.store)["queue"][0]
        WatchStore(self.store).queue(queued["product_id"], next_attempt_at=None)
        self.restart()
        self.cycle(force=True, processor=invalid)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(status(self.store)["queue"][0]["attempts"], 1)
        self.assertEqual(self.client.downloads, 1)

    def test_exhausted_pilot_runtime_is_not_reset_by_restart(self):
        def interrupted(*args):
            raise OSError("fixture interruption before runtime exhaustion")

        self.cycle(force=True, processor=interrupted)
        queued = status(self.store)["queue"][0]
        WatchStore(self.store).queue(queued["product_id"], next_attempt_at=None)
        with self.store.connection(True) as database:
            database.execute("UPDATE watch_pilots SET runtime_charged=? WHERE id=?",
                             (self.config["product_max_seconds"], queued["pilot_id"]))
        self.restart()
        self.cycle(force=True)
        self.assertEqual(status(self.store)["queue"][0]["attempts"], 1)
        self.assertEqual(self.processed, [])
        self.assertEqual(self.client.downloads, 1)

    def incomplete_cycle(self, service):
        original_query = self.client.query

        def incomplete(request):
            page = json.loads(original_query(request))
            if request["service"] == service:
                page["paging"]["pagesFiltered"] = 2
            return json.dumps(page).encode()

        self.client.query = incomplete
        self.cycle(force=True)
        self.assertEqual(status(self.store)["queue"], [])
        self.assertEqual(self.client.downloads, 0)
        self.assertEqual(self.processed, [])

    def test_incomplete_observation_snapshot_never_auto_selects(self):
        self.incomplete_cycle("Mast.Caom.Filtered")

    def test_incomplete_product_snapshot_never_auto_selects(self):
        self.incomplete_cycle("Mast.Caom.Products")

    def test_cumulative_queue_cap_survives_restart_and_new_release(self):
        observed = poll_once(self.store, {**load_config(), "targets": ["123"]},
                             client=self.client, force=True)
        product = self.store.list_records("products")[0]
        product_ids = [product["id"]]
        for number in range(19):
            extra = self.store.register_product(
                release_id=product["release_id"], product_key="cap-fixture-" + str(number),
                target_id=product["target_id"], source_uri=product["source_uri"],
                provenance_id=product["provenance_id"], metadata=product["metadata"],
            )
            product_ids.append(extra["id"])
            with self.store.connection(True) as database:
                database.execute("INSERT INTO watch_seen VALUES(?,?)", (observed["poll_id"], extra["id"]))
        create_pilot(self.store, self.protocol["id"], pilot_id="previous-bounded-selection",
                     product_ids=product_ids, cohort="archival_pilot", max_bytes=10 * 1024**2, max_seconds=900)
        for product_id in product_ids:
            WatchStore(self.store).queue(product_id, state="complete")
        self.restart()
        self.client.scenario = "new_release"
        self.cycle(force=True)
        self.assertEqual(len(status(self.store)["queue"]), 20)
        self.assertEqual(self.client.downloads, 0)
        self.assertEqual(self.processed, [])

    def test_real_transfer_accounting_includes_metadata_and_reuses_completed_products(self):
        session = OfflineArchiveSession(self.client, self.source)
        client = mast.MastClient(WatchStore(self.store), session=session)
        run_cycle(self.store, self.artifacts, self.protocol["id"], self.config,
                  client=client, processor=self.processor, force=True)
        budget = status(self.store)["budget"]
        self.assertEqual(session.downloads, 1)
        self.assertEqual(budget["charged_bytes"], session.transferred)
        self.assertEqual(budget["by_kind"]["science_product"], self.source.stat().st_size)
        self.assertGreater(budget["by_kind"]["metadata"], 0)
        self.assertEqual(budget["unsettled_reservations"], 0)
        self.restart()
        client = mast.MastClient(WatchStore(self.store), session=session)
        run_cycle(self.store, self.artifacts, self.protocol["id"], self.config,
                  client=client, processor=self.processor, force=True)
        self.assertEqual(session.downloads, 1)
        self.assertEqual(status(self.store)["budget"]["charged_bytes"], session.transferred)
        self.assertEqual(len(self.store.list_records("candidates")), 1)

    def test_exhausted_network_budget_prevents_archive_requests(self):
        ledger = WatchStore(self.store)
        ledger.account("fixture-previous-spend", 2 * 1024**3, "Offline demonstration of exhausted network budget")
        session = OfflineArchiveSession(self.client, self.source)
        client = mast.MastClient(ledger, session=session)
        result = run_cycle(self.store, self.artifacts, self.protocol["id"], self.config,
                           client=client, processor=self.processor, force=True)
        self.assertEqual(session.requests, 0)
        self.assertEqual(status(self.store)["budget"]["remaining_bytes"], 0)
        self.assertEqual(status(self.store)["queue"], [])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["errors"])

    def test_failed_catalog_refresh_is_charged_once_and_cached_across_restart(self):
        self.config["catalog_mode"] = "live"
        with patch("scripts.research.vetting_worker.refresh_registry",
                   side_effect=OSError("fixture catalog service unavailable")) as refresh:
            first = self.cycle(force=True)
            self.assertTrue(first["errors"])
            job_id = status(self.store)["queue"][0]["job_id"]
            self.restart()
            self.cycle(force=True)
            cached = automation._refresh_catalogs(self.store, self.artifacts, job_id)
        refresh.assert_called_once()
        self.assertEqual(cached["error"]["code"], "OSError")
        self.assertEqual(cached["error"]["message"], "fixture catalog service unavailable")
        budget = status(self.store)["budget"]
        self.assertEqual(budget["by_kind"]["catalog_refresh"], 64 * 1024**2)
        self.assertEqual(budget["unsettled_reservations"], 0)
        with self.store.connection() as database:
            recorded = database.execute("SELECT checked_at,result_json FROM watch_catalog_checks WHERE job_id=?",
                                        (job_id,)).fetchone()
        self.assertIsNotNone(recorded["checked_at"])
        self.assertEqual(json.loads(recorded["result_json"])["error"], cached["error"])

    def test_queued_check_is_coalesced_claimed_once_and_durable(self):
        ledger = WatchStore(self.store)
        ledger.start_automation(self.config)
        first = ledger.request_check()
        self.assertEqual(first["status"], "queued")
        self.assertEqual(ledger.request_check()["id"], first["id"])
        claimed = ledger.claim_check()
        self.assertEqual(claimed["id"], first["id"])
        self.assertEqual(claimed["status"], "running")
        self.assertIsNone(ledger.claim_check())
        self.assertEqual(ledger.request_check()["id"], first["id"])
        self.restart()
        restarted = WatchStore(self.store)
        restarted.start_automation(self.config)
        resumed = restarted.claim_check()
        self.assertEqual(resumed["id"], first["id"])
        result = self.cycle(force=True)
        restarted.finish_check(resumed["id"], result=result)
        request = status(self.store)["automation"]["check_request"]
        self.assertEqual(request["status"], "succeeded")
        self.assertEqual(request["result"]["new_candidates"], 1)
        self.assertIsNone(restarted.claim_check())
        with self.assertRaises(ConflictError):
            restarted.request_check()

    def test_stopped_and_stale_services_reject_check_requests(self):
        ledger = WatchStore(self.store)
        self.assertFalse(status(self.store)["automation"]["enabled"])
        with self.assertRaises(ConflictError):
            ledger.request_check()
        ledger.start_automation(self.config)
        ledger.automation_update(state="stopped")
        with self.assertRaises(ConflictError):
            ledger.request_check()
        ledger.start_automation(self.config)
        with self.store.connection(True) as database:
            database.execute("UPDATE watch_automation SET heartbeat_at='2000-01-01T00:00:00.000000Z'")
        self.assertEqual(status(self.store)["automation"]["service_state"], "stale")
        with self.assertRaises(ConflictError):
            ledger.request_check()

    def test_configuration_change_does_not_replay_old_pending_request(self):
        ledger = WatchStore(self.store)
        ledger.start_automation(self.config)
        first = ledger.request_check()
        ledger.claim_check()
        self.restart()
        changed = {**self.config, "targets": ["456"]}
        restarted = WatchStore(self.store)
        restarted.start_automation(changed)
        self.assertIsNone(restarted.claim_check())
        with self.store.connection() as database:
            request = database.execute("SELECT status,error_json FROM watch_check_requests WHERE id=?",
                                       (first["id"],)).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertEqual(json.loads(request["error_json"])["code"], "ConfigurationChanged")
        self.assertEqual(status(self.store)["automation"]["targets"], ["456"])

    def test_failed_request_and_cycle_error_remain_visible_after_restart(self):
        ledger = WatchStore(self.store)
        ledger.start_automation(self.config)
        request = ledger.request_check()
        ledger.claim_check()
        failure = {"code": "FixtureFailure", "message": "offline demonstration unavailable"}
        ledger.automation_update(phase="error", error=failure)
        ledger.finish_check(request["id"], error=failure)
        self.restart()
        snapshot = status(self.store)["automation"]
        self.assertEqual(snapshot["last_error"], failure)
        self.assertEqual(snapshot["check_request"]["error"], failure)
        self.assertEqual(snapshot["check_request"]["status"], "failed")

    def test_elapsed_cycle_budget_stops_after_poll_even_when_poll_catches_alarm(self):
        self.config["targets"] = ["123", "456", "789"]
        original_poll = automation.poll_once
        real_monotonic = time.monotonic
        elapsed = [0]

        def consumed_poll(*args, **kwargs):
            result = original_poll(*args, **kwargs)
            elapsed[0] += self.config["cycle_max_seconds"] + 1
            return result

        with patch.object(automation.time, "monotonic", side_effect=lambda: real_monotonic() + elapsed[0]), \
                patch.object(automation, "poll_once", side_effect=consumed_poll):
            result = self.cycle(force=True)
        observations = [request for request in self.client.calls if request["service"] == "Mast.Caom.Filtered"]
        self.assertEqual(len(observations), 1)
        self.assertEqual(status(self.store)["queue"], [])
        self.assertEqual(self.client.downloads, 0)
        self.assertTrue(any(error["code"] == "TimeoutError" for error in result["errors"]))

    def test_elapsed_cycle_budget_stops_catalog_refresh_after_dispatch(self):
        self.config["catalog_mode"] = "live"
        original_dispatch = automation.dispatch
        real_monotonic = time.monotonic
        elapsed = [0]

        def consumed_dispatch(*args, **kwargs):
            result = original_dispatch(*args, **kwargs)
            elapsed[0] += self.config["cycle_max_seconds"] + 1
            return result

        with patch.object(automation.time, "monotonic", side_effect=lambda: real_monotonic() + elapsed[0]), \
                patch.object(automation, "dispatch", side_effect=consumed_dispatch), \
                patch.object(automation, "_refresh_catalogs") as refresh:
            result = self.cycle(force=True)
        self.assertEqual(result["new_candidates"], 1)
        refresh.assert_not_called()
        self.assertTrue(any(error["code"] == "TimeoutError" for error in result["errors"]))

    def test_poll_health_uses_automatic_scheduler_and_keeps_legacy_history(self):
        ledger = WatchStore(self.store)
        current = ledger.config(automation.metadata_configs(self.config)[0])
        legacy_config = deepcopy(automation.metadata_configs(self.config)[0])
        legacy_config['max_products_per_poll'] = 1
        legacy = ledger.config(legacy_config)
        ledger.start_automation(self.config)
        records = {item['id']: item for item in status(self.store)['configs']}
        self.assertEqual(records[current['id']]['health'], 'running')
        self.assertEqual(records[current['id']]['scheduler']['kind'], 'automatic')
        self.assertIsNotNone(records[current['id']]['scheduler']['heartbeat_at'])
        self.assertEqual(records[legacy['id']]['health'], 'stopped')
        ledger.automation_update(state='stopped')
        records = {item['id']: item for item in status(self.store)['configs']}
        self.assertEqual(records[current['id']]['health'], 'stopped')
        ledger.service(current['id'], 'running')
        records = {item['id']: item for item in status(self.store)['configs']}
        self.assertEqual(records[current['id']]['health'], 'running')
        self.assertEqual(records[current['id']]['scheduler']['kind'], 'metadata_only')

    def test_one_shot_cli_cannot_revive_stale_daemon_liveness(self):
        from scripts.research.__main__ import main
        from scripts.research.watcher_store import later
        ledger = WatchStore(self.store)
        config_path = self.root / 'automatic.json'
        config_path.write_text(json.dumps(self.config))
        arguments = ['--db', str(self.store.path), '--artifacts', str(self.root / 'artifacts'),
                     'watch-auto-once', '--config', str(config_path)]
        for fail in (False, True):
            ledger.start_automation(self.config)
            with self.store.connection(True) as db:
                db.execute('UPDATE watch_automation SET heartbeat_at=?', (later(-300),))
            self.assertEqual(status(self.store)['automation']['service_state'], 'stale')

            def cycle(*args, **kwargs):
                ledger.automation_update(phase='polling')
                self.assertEqual(status(self.store)['automation']['service_state'], 'stopped')
                if fail:
                    raise OSError('Fixture cycle failure')
                return {'errors': []}

            with patch.object(automation, 'run_cycle', side_effect=cycle), patch('sys.stdout', new=io.StringIO()):
                if fail:
                    with self.assertRaises(OSError):
                        main(arguments)
                else:
                    self.assertEqual(main(arguments), 0)
            self.assertEqual(status(self.store)['automation']['service_state'], 'stopped')
            with self.assertRaises(ConflictError):
                ledger.request_check()

    def test_config_rejects_unbounded_or_ambiguous_controls(self):
        self.assertEqual(validate_config(self.config), self.config)
        invalid = {
            "targets": ["123", "123"], "poll_seconds": 1, "poll_max_seconds": 0,
            "cohort": "prospective_search", "product_max_bytes": 2 * 1024**3 + 1,
            "product_max_seconds": 0, "max_products_per_cycle": 21,
            "cycle_max_seconds": 0, "catalog_mode": "online",
        }
        for field, value in invalid.items():
            with self.subTest(field=field):
                config = deepcopy(self.config)
                config[field] = value
                with self.assertRaises(ValidationError):
                    validate_config(config)


if __name__ == "__main__":
    unittest.main()
