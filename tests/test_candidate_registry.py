"""Verify deterministic, fail-closed candidate registry assessments."""
import json
import os
from pathlib import Path
import tempfile
import unittest

import requests

from scripts.vetting.check_candidate import render_markdown, run_check
from scripts.vetting.registry import (
    AssessmentStatus,
    Candidate,
    CatalogRecord,
    CatalogSnapshot,
    EphemerisMatch,
    MatchPolicy,
    SourceState,
    assess_candidate,
    compare_ephemeris,
)
from scripts.vetting.sources import (
    CatalogClient,
    EXOFOP_TOI_URL,
    parse_exofop_ctoi,
    parse_exofop_toi,
    parse_nasa_ps,
    parse_nasa_toi,
)


FIXTURES = Path(__file__).parent / "fixtures" / "candidate_vetting" / "v1"
CHECKED_AT = "2026-09-21T12:00:00Z"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def snapshot(source_id, records=None, state=SourceState.OK, required=True):
    authority = "ExoFOP-TESS" if source_id.startswith("exofop") else "NASA Exoplanet Archive"
    return CatalogSnapshot(
        source_id=source_id,
        authority=authority,
        endpoint=f"https://example.test/{source_id}",
        required_for_unmatched=required,
        state=state,
        retrieved_at_utc=CHECKED_AT,
        records=list(records or []),
        catalog_updated_at="2026-09-20T18:15:36Z",
        payload_sha256="a" * 64 if state in {SourceState.OK, SourceState.NOT_MODIFIED} else None,
        error=None if state in {SourceState.OK, SourceState.NOT_MODIFIED} else "simulated failure",
    )


def empty_complete_snapshots():
    return [
        snapshot("exofop_toi"),
        snapshot("exofop_ctoi"),
        snapshot("nasa_ps"),
        snapshot("nasa_toi", required=False),
    ]


def replace_snapshot(snapshots, replacement):
    return [replacement if item.source_id == replacement.source_id else item for item in snapshots]


class CandidateParsingTests(unittest.TestCase):
    def test_parses_realistic_source_fixtures_without_losing_signal_identity(self):
        toi_records = parse_exofop_toi(fixture("exofop_tois.csv"), "150428135")
        ctoi_records = parse_exofop_ctoi(fixture("exofop_ctois.csv"), "920000001")
        ps_records = parse_nasa_ps(
            fixture("nasa_ps.json"),
            "150428135",
            "https://example.test/nasa-ps-query",
        )
        nasa_toi_records = parse_nasa_toi(
            fixture("nasa_toi.json"),
            "150428135",
            "https://example.test/nasa-toi-query",
        )

        self.assertEqual([record.record_id for record in toi_records], ["TOI-700.02"])
        self.assertEqual(toi_records[0].metadata["imaging_observations"], 3)
        self.assertEqual(ctoi_records[0].record_id, "CTOI-920000001.01")
        self.assertEqual(ctoi_records[0].metadata["paper"], "Example et al. 2026")
        self.assertEqual(ps_records[0].disposition, "CONFIRMED")
        self.assertEqual(nasa_toi_records[0].record_id, "TOI-700.02")

    def test_invalid_candidate_identifiers_and_ephemerides_are_rejected(self):
        invalid_values = [
            {"tic_id": "TOI-700", "period_days": 1, "epoch_bjd_tdb": 2459000},
            {"tic_id": 42, "period_days": 0, "epoch_bjd_tdb": 2459000},
            {"tic_id": 42, "period_days": 1, "epoch_bjd_tdb": float("nan")},
            {"tic_id": 42, "period_days": 1, "epoch_bjd_tdb": 2000},
            {
                "tic_id": 42,
                "period_days": 1,
                "epoch_bjd_tdb": 2459000,
                "duration_hours": 24,
            },
        ]
        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ValueError):
                Candidate(**values)


class EphemerisMatchingTests(unittest.TestCase):
    def setUp(self):
        self.record = CatalogRecord(
            source_id="exofop_toi",
            authority="ExoFOP-TESS",
            record_id="TOI-42.01",
            tic_id="42",
            disposition="PC",
            period_days=10.0,
            epoch_bjd_tdb=2459000.0,
            duration_hours=2.0,
            row_updated_at="2026-09-20",
            evidence_url="https://example.test/42",
        )

    def test_integer_cycle_epoch_offset_is_a_direct_match(self):
        candidate = Candidate("42", 10.001, 2459100.0, 2.0)
        match_type, metrics = compare_ephemeris(candidate, self.record, MatchPolicy())
        self.assertEqual(match_type, EphemerisMatch.DIRECT)
        self.assertLessEqual(
            metrics["epoch_phase_difference_days"], metrics["epoch_tolerance_days"]
        )

    def test_small_integer_period_harmonics_are_aliases_not_direct_matches(self):
        cases = [
            (5.0, EphemerisMatch.HALF_PERIOD_ALIAS),
            (20.0, EphemerisMatch.DOUBLE_PERIOD_ALIAS),
            (10.0 / 3.0, EphemerisMatch.THIRD_PERIOD_ALIAS),
            (30.0, EphemerisMatch.TRIPLE_PERIOD_ALIAS),
        ]
        for period, expected in cases:
            with self.subTest(period=period):
                candidate = Candidate("42", period, 2459000.0, 2.0)
                match_type, _ = compare_ephemeris(candidate, self.record, MatchPolicy())
                self.assertEqual(match_type, expected)

    def test_period_and_epoch_tolerances_are_both_enforced(self):
        period_mismatch = Candidate("42", 10.049, 2459000.0, 2.0)
        epoch_mismatch = Candidate("42", 10.0, 2459000.4, 2.0)
        self.assertEqual(
            compare_ephemeris(period_mismatch, self.record, MatchPolicy())[0],
            EphemerisMatch.MISMATCH,
        )
        self.assertEqual(
            compare_ephemeris(epoch_mismatch, self.record, MatchPolicy())[0],
            EphemerisMatch.MISMATCH,
        )

    def test_match_policy_rejects_unbounded_epoch_tolerances(self):
        with self.assertRaises(ValueError):
            MatchPolicy(maximum_epoch_tolerance_fraction_of_period=0.5)


class CandidateAssessmentTests(unittest.TestCase):
    def records_for(self, tic_id):
        return parse_exofop_toi(fixture("exofop_tois.csv"), str(tic_id))

    def assess_with_toi(self, candidate):
        snapshots = replace_snapshot(
            empty_complete_snapshots(),
            snapshot("exofop_toi", self.records_for(candidate.tic_id)),
        )
        return assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)

    def test_nasa_direct_match_is_confirmed_with_auditable_evidence(self):
        candidate = Candidate("150428135", 37.4236838, 2458330.486155, 3.365, "TOI-700.02")
        snapshots = empty_complete_snapshots()
        snapshots = replace_snapshot(
            snapshots,
            snapshot("exofop_toi", parse_exofop_toi(fixture("exofop_tois.csv"), candidate.tic_id)),
        )
        snapshots = replace_snapshot(
            snapshots,
            snapshot(
                "nasa_ps",
                parse_nasa_ps(fixture("nasa_ps.json"), candidate.tic_id, "https://example.test/ps"),
            ),
        )
        snapshots = replace_snapshot(
            snapshots,
            snapshot(
                "nasa_toi",
                parse_nasa_toi(
                    fixture("nasa_toi.json"), candidate.tic_id, "https://example.test/toi"
                ),
                required=False,
            ),
        )

        report = assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)

        self.assertEqual(report["status"], AssessmentStatus.CONFIRMED_PLANET.value)
        self.assertEqual(report["coverage"], "COMPLETE")
        self.assertFalse(report["human_review_required"])
        self.assertIn("TOI-700 d", report["summary"])
        self.assertNotIn("TOI-700.02", report["summary"])
        self.assertTrue(report["study_evidence"]["public_follow_up_recorded"])
        self.assertIsNone(report["study_evidence"]["research_completion_percentage"])
        nasa_match = next(item for item in report["matches"] if item["source_id"] == "nasa_ps")
        self.assertEqual(nasa_match["ephemeris_match"], "DIRECT")
        self.assertTrue(nasa_match["evidence_url"].startswith("https://"))
        self.assertTrue(all(source["payload_sha256"] for source in report["sources"]))

    def test_candidate_false_positive_and_false_alarm_remain_distinct(self):
        cases = [
            ("910000001", 5.0, 2459000.0, AssessmentStatus.KNOWN_CANDIDATE),
            ("910000002", 7.0, 2459001.0, AssessmentStatus.KNOWN_FALSE_POSITIVE),
            ("910000003", 9.0, 2459002.0, AssessmentStatus.KNOWN_FALSE_ALARM),
        ]
        for tic_id, period, epoch, expected in cases:
            with self.subTest(tic_id=tic_id):
                report = self.assess_with_toi(Candidate(tic_id, period, epoch, 2.0))
                self.assertEqual(report["status"], expected.value)

    def test_community_candidate_and_paper_are_reported(self):
        candidate = Candidate("920000001", 11.0, 2459100.5, 3.0)
        snapshots = replace_snapshot(
            empty_complete_snapshots(),
            snapshot(
                "exofop_ctoi",
                parse_exofop_ctoi(fixture("exofop_ctois.csv"), candidate.tic_id),
            ),
        )
        report = assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)
        self.assertEqual(report["status"], AssessmentStatus.KNOWN_CANDIDATE.value)
        self.assertEqual(
            report["study_evidence"]["papers_or_references"], ["Example et al. 2026"]
        )

    def test_another_planet_on_same_tic_never_matches_by_host_alone(self):
        candidate = Candidate("910000004", 8.0, 2459000.0, 2.0)
        report = self.assess_with_toi(candidate)
        self.assertEqual(report["status"], AssessmentStatus.UNMATCHED.value)
        self.assertEqual(len(report["matches"]), 2)
        self.assertTrue(all(item["ephemeris_match"] == "MISMATCH" for item in report["matches"]))
        self.assertIn("does not establish novelty", report["summary"])

    def test_matching_signal_is_selected_on_a_multi_planet_host(self):
        candidate = Candidate("910000004", 5.0, 2459001.0, 2.0)
        report = self.assess_with_toi(candidate)
        self.assertEqual(report["status"], AssessmentStatus.KNOWN_PLANET.value)
        direct = [item for item in report["matches"] if item["ephemeris_match"] == "DIRECT"]
        self.assertEqual([item["record_id"] for item in direct], ["TOI-913.02"])

    def test_half_or_double_period_never_inherits_planet_status(self):
        candidate = Candidate("910000004", 10.0, 2459001.0, 2.0)
        report = self.assess_with_toi(candidate)
        self.assertEqual(report["status"], AssessmentStatus.AMBIGUOUS_ALIAS.value)
        self.assertTrue(report["human_review_required"])
        self.assertIn("DOUBLE_PERIOD_ALIAS", render_markdown(report))

    def test_required_source_outage_fails_closed(self):
        candidate = Candidate("910000001", 5.0, 2459000.0, 2.0)
        snapshots = replace_snapshot(
            empty_complete_snapshots(),
            snapshot("exofop_toi", self.records_for(candidate.tic_id)),
        )
        snapshots = replace_snapshot(
            snapshots,
            snapshot("exofop_ctoi", state=SourceState.UNAVAILABLE),
        )
        report = assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)
        self.assertEqual(report["status"], AssessmentStatus.INCOMPLETE_LOOKUP.value)
        self.assertEqual(report["coverage"], "PARTIAL")

    def test_missing_or_duplicate_required_snapshots_fail_closed(self):
        candidate = Candidate("999999999", 13.0, 2459000.0, 2.0)
        missing = assess_candidate(
            candidate,
            [snapshot("exofop_toi")],
            generated_at_utc=CHECKED_AT,
        )
        duplicated_snapshots = empty_complete_snapshots() + [snapshot("nasa_ps")]
        duplicated = assess_candidate(
            candidate,
            duplicated_snapshots,
            generated_at_utc=CHECKED_AT,
        )
        self.assertEqual(missing["status"], AssessmentStatus.INCOMPLETE_LOOKUP.value)
        self.assertEqual(duplicated["status"], AssessmentStatus.INCOMPLETE_LOOKUP.value)
        self.assertIn("Required source snapshots missing", missing["warnings"][0])
        self.assertTrue(any("Duplicate source snapshots" in value for value in duplicated["warnings"]))

    def test_same_host_record_with_missing_ephemeris_is_ambiguous(self):
        candidate = Candidate("940000001", 4.0, 2459000.0, 2.0)
        incomplete = CatalogRecord(
            source_id="exofop_toi",
            authority="ExoFOP-TESS",
            record_id="TOI-940.01",
            tic_id=candidate.tic_id,
            disposition="PC",
            period_days=4.0,
            epoch_bjd_tdb=None,
            duration_hours=2.0,
            row_updated_at="2026-09-20",
            evidence_url="https://example.test/incomplete",
        )
        snapshots = replace_snapshot(
            empty_complete_snapshots(), snapshot("exofop_toi", [incomplete])
        )
        report = assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)
        self.assertEqual(report["status"], AssessmentStatus.AMBIGUOUS_MATCH.value)

    def test_unpromoted_community_conflict_is_not_silently_discarded(self):
        candidate = Candidate("910000004", 5.0, 2459001.0, 2.0)
        toi_records = self.records_for(candidate.tic_id)
        ctoi = CatalogRecord(
            source_id="exofop_ctoi",
            authority="ExoFOP-TESS",
            record_id="CTOI-910000004.01",
            tic_id=candidate.tic_id,
            disposition="FP",
            period_days=5.0,
            epoch_bjd_tdb=2459001.0,
            duration_hours=2.0,
            row_updated_at="2026-09-20",
            evidence_url="https://example.test/community",
        )
        snapshots = replace_snapshot(
            empty_complete_snapshots(), snapshot("exofop_toi", toi_records)
        )
        snapshots = replace_snapshot(snapshots, snapshot("exofop_ctoi", [ctoi]))
        conflict = assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)
        self.assertEqual(conflict["status"], AssessmentStatus.CONFLICTING_RECORDS.value)

        promoted = CatalogRecord(
            **{
                **ctoi.__dict__,
                "metadata": {"promoted_to_toi": "913.02"},
            }
        )
        promoted_snapshots = replace_snapshot(snapshots, snapshot("exofop_ctoi", [promoted]))
        resolved = assess_candidate(candidate, promoted_snapshots, generated_at_utc=CHECKED_AT)
        self.assertEqual(resolved["status"], AssessmentStatus.KNOWN_PLANET.value)

    def test_confirmed_and_false_positive_for_same_signal_is_a_conflict(self):
        candidate = Candidate("910000002", 7.0, 2459001.0, 2.5)
        confirmed = CatalogRecord(
            source_id="nasa_ps",
            authority="NASA Exoplanet Archive",
            record_id="Synthetic b",
            tic_id=candidate.tic_id,
            disposition="CONFIRMED",
            period_days=7.0,
            epoch_bjd_tdb=2459001.0,
            duration_hours=None,
            row_updated_at="2026-09-20",
            evidence_url="https://example.test/confirmed",
        )
        snapshots = replace_snapshot(
            empty_complete_snapshots(),
            snapshot("exofop_toi", self.records_for(candidate.tic_id)),
        )
        snapshots = replace_snapshot(snapshots, snapshot("nasa_ps", [confirmed]))
        report = assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)
        self.assertEqual(report["status"], AssessmentStatus.CONFLICTING_RECORDS.value)

    def test_controversial_nasa_planet_requires_human_review(self):
        candidate = Candidate("930000001", 3.0, 2459000.0, 1.5)
        controversial = CatalogRecord(
            source_id="nasa_ps",
            authority="NASA Exoplanet Archive",
            record_id="Controversial b",
            tic_id=candidate.tic_id,
            disposition="CONFIRMED",
            period_days=3.0,
            epoch_bjd_tdb=2459000.0,
            duration_hours=None,
            row_updated_at="2026-09-20",
            evidence_url="https://example.test/controversial",
            metadata={"controversial_flag": 1},
        )
        snapshots = replace_snapshot(empty_complete_snapshots(), snapshot("nasa_ps", [controversial]))
        report = assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)
        self.assertEqual(report["status"], AssessmentStatus.CONFIRMED_CONTROVERSIAL.value)
        self.assertTrue(report["human_review_required"])

    def test_unsupported_nasa_epoch_time_system_cannot_confirm(self):
        candidate = Candidate("150428135", 37.4236838, 2458330.486155, 3.365)
        payload = fixture("nasa_ps.json").replace(b"BJD-TDB", b"HJD-UTC")
        nasa_records = parse_nasa_ps(
            payload,
            candidate.tic_id,
            "https://example.test/unsupported-time-system",
        )
        self.assertIsNone(nasa_records[0].epoch_bjd_tdb)
        snapshots = replace_snapshot(
            empty_complete_snapshots(), snapshot("nasa_ps", nasa_records)
        )
        report = assess_candidate(candidate, snapshots, generated_at_utc=CHECKED_AT)
        self.assertEqual(report["status"], AssessmentStatus.AMBIGUOUS_MATCH.value)

    def test_high_model_score_cannot_change_an_unmatched_catalog_status(self):
        candidate = Candidate("999999999", 13.0, 2459000.0, 2.0)
        report = assess_candidate(candidate, empty_complete_snapshots(), generated_at_utc=CHECKED_AT)
        report["model_score_for_test"] = 0.999
        self.assertEqual(report["status"], AssessmentStatus.UNMATCHED.value)
        self.assertNotIn("new planet", report["summary"].lower())


class FakeResponse:
    def __init__(self, payload=b"", status_code=200, headers=None, url=EXOFOP_TOI_URL):
        self.content = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CatalogClientTests(unittest.TestCase):
    def test_static_catalog_cache_is_conditionally_revalidated(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = fixture("exofop_tois.csv")
            first_session = FakeSession(
                [
                    FakeResponse(
                        payload,
                        headers={
                            "Content-Type": "text/csv",
                            "ETag": '"fixture-v1"',
                            "Last-Modified": "Sun, 20 Sep 2026 18:15:36 GMT",
                        },
                    )
                ]
            )
            first_client = CatalogClient(
                Path(temporary),
                session=first_session,
                attempts=1,
                clock=lambda: CHECKED_AT,
            )
            first = first_client.fetch_exofop_toi("150428135")
            self.assertEqual(first.state, SourceState.OK)

            second_session = FakeSession([FakeResponse(status_code=304)])
            second_client = CatalogClient(
                Path(temporary),
                session=second_session,
                attempts=1,
                clock=lambda: CHECKED_AT,
            )
            second = second_client.fetch_exofop_toi("150428135")
            self.assertEqual(second.state, SourceState.NOT_MODIFIED)
            self.assertEqual(second.payload_sha256, first.payload_sha256)
            sent_headers = second_session.calls[0][1]["headers"]
            self.assertEqual(sent_headers["If-None-Match"], '"fixture-v1"')

    def test_html_or_changed_schema_is_not_misread_as_no_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = FakeSession(
                [FakeResponse(b"<html>maintenance</html>", headers={"Content-Type": "text/html"})]
            )
            client = CatalogClient(
                Path(temporary), session=session, attempts=1, clock=lambda: CHECKED_AT
            )
            result = client.fetch_exofop_toi("42")
            self.assertEqual(result.state, SourceState.SCHEMA_ERROR)
            self.assertIn("not CSV", result.error)

    def test_malformed_numeric_cell_becomes_schema_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = fixture("exofop_tois.csv").replace(
                b"37.4236838274161", b"not-a-period", 1
            )
            session = FakeSession(
                [FakeResponse(payload, headers={"Content-Type": "text/csv"})]
            )
            client = CatalogClient(
                Path(temporary), session=session, attempts=1, clock=lambda: CHECKED_AT
            )
            result = client.fetch_exofop_toi("150428135")
            self.assertEqual(result.state, SourceState.SCHEMA_ERROR)
            self.assertIn("invalid numeric", result.error)

    def test_impossible_catalog_period_or_btjd_epoch_becomes_schema_error(self):
        replacements = [
            (b"37.4236838274161", b"-37.4", "must be positive"),
            (b"2458330.486155", b"1330.486155", "plausible absolute BJD"),
        ]
        for old, new, expected in replacements:
            with self.subTest(replacement=new), tempfile.TemporaryDirectory() as temporary:
                payload = fixture("exofop_tois.csv").replace(old, new, 1)
                session = FakeSession(
                    [FakeResponse(payload, headers={"Content-Type": "text/csv"})]
                )
                client = CatalogClient(
                    Path(temporary), session=session, attempts=1, clock=lambda: CHECKED_AT
                )
                result = client.fetch_exofop_toi("150428135")
                self.assertEqual(result.state, SourceState.SCHEMA_ERROR)
                self.assertIn(expected, result.error)

    def test_network_failure_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = FakeSession([requests.Timeout("simulated timeout")])
            client = CatalogClient(
                Path(temporary), session=session, attempts=1, clock=lambda: CHECKED_AT
            )
            result = client.fetch_exofop_toi("42")
            self.assertEqual(result.state, SourceState.UNAVAILABLE)
            self.assertIn("Timeout", result.error)


class CandidateReportTests(unittest.TestCase):
    def test_run_writes_raw_snapshots_json_and_markdown(self):
        candidate = Candidate("910000001", 5.0, 2459000.0, 2.0)
        snapshots = replace_snapshot(
            empty_complete_snapshots(),
            snapshot(
                "exofop_toi",
                parse_exofop_toi(fixture("exofop_tois.csv"), candidate.tic_id),
            ),
        )
        for item in snapshots:
            item.raw_payload = b"[]" if item.source_id.startswith("nasa") else b"header\n"

        class StubClient:
            def lookup(self, tic_id):
                self.tic_id = tic_id
                return snapshots

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = run_check(
                candidate,
                StubClient(),
                root / "snapshots",
                root / "reports",
                generated_at_utc=CHECKED_AT,
            )
            json_path = Path(report["report_paths"]["json"])
            markdown_path = Path(report["report_paths"]["markdown"])
            manifest_path = Path(report["source_snapshot_manifest"])
            self.assertTrue(json_path.is_file())
            self.assertTrue(markdown_path.is_file())
            self.assertTrue(manifest_path.is_file())
            self.assertEqual(json.loads(json_path.read_text())["status"], "KNOWN_CANDIDATE")
            markdown = render_markdown(report)
            self.assertIn("Research completion percentage: not defined", markdown)
            self.assertIn("does not validate, confirm, or announce a new planet", markdown)


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_CATALOG_TESTS") == "1",
    "set RUN_LIVE_CATALOG_TESTS=1 for current official-catalog contract test",
)
class LiveCatalogContractTests(unittest.TestCase):
    def test_current_sources_recognize_toi_700_d(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = CatalogClient(Path(temporary), attempts=2, timeout_seconds=180)
            candidate = Candidate("150428135", 37.4236838, 2458330.486155, 3.365)
            snapshots = client.lookup(candidate.tic_id)
            states = {item.source_id: item.state for item in snapshots}
            self.assertIn(states["exofop_toi"], {SourceState.OK, SourceState.NOT_MODIFIED})
            self.assertIn(states["exofop_ctoi"], {SourceState.OK, SourceState.NOT_MODIFIED})
            self.assertEqual(states["nasa_ps"], SourceState.OK)
            report = assess_candidate(candidate, snapshots)
            self.assertEqual(report["status"], AssessmentStatus.CONFIRMED_PLANET.value)
            self.assertTrue(any(item["record_id"] == "TOI-700 d" for item in report["matches"]))
