"""Candidate sorting/filtering across real temporary SQLite and loopback HTTP."""
from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import ValidationError, load_protocol
from scripts.research.server import ResearchServer
from scripts.research.store import Store
from scripts.vetting.registry import AssessmentStatus


class SortingFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / 'research.sqlite3').initialize()
        self.protocol = self.store.register_protocol(load_protocol())
        self.provenance = self.store.register_provenance(kind='fixture', identity='sorting-test-only',
            sha256_digest='a' * 64, retrieved_at='2026-01-01T00:00:00Z', details={'temporary': True})['id']
        self.jobs = {cohort: self.store.create_job(job_key='sorting-' + cohort, cohort=cohort,
                     protocol_id=self.protocol['id'], code_provenance_id=self.provenance)['id']
                     for cohort in ('archival_pilot', 'known_object_control')}
        self.serial = 0
        self.evidence_serial = 0

    def candidate(self, *, target=None, period=3., cohort='archival_pilot', created=None):
        self.serial += 1
        created = created or (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=self.serial)).isoformat().replace('+00:00', 'Z')
        with patch('scripts.research.store.utc_now', return_value=created):
            return self.store.put_candidate(job_id=self.jobs[cohort], signal_key=f'fixture-{self.serial}',
                target_id=str(target if target is not None else self.serial), mission='TESS',
                period_days=period, epoch=1500., epoch_system='BTJD', duration_hours=2.,
                detection={'method': 'sorting_fixture', 'ephemeris_origin': 'blind_search',
                           'used_catalog_ephemeris': False}, provenance_id=self.provenance)['id']

    def score(self, candidate, value=None, *, state='complete'):
        self.evidence_serial += 1
        payload = {'score': value, 'model_sha256': 'b' * 64, 'normalization_sha256': 'c' * 64,
                   'input_contract': 'shared_v1'} if state == 'complete' else {'reason': 'later fixture failure'}
        return self.store.put_evidence(candidate_id=candidate, evidence_key=f'score-{self.evidence_serial}',
            kind='model_score', state=state, summary='Temporary sorting evidence', payload=payload,
            provenance_id=self.provenance)

    def registry(self, candidate, status, *, state=None):
        self.evidence_serial += 1
        state = state or ('incomplete' if status in (None, 'INCOMPLETE_LOOKUP') else 'complete')
        return self.store.put_evidence(candidate_id=candidate, evidence_key=f'registry-{self.evidence_serial}',
            kind='registry', state=state, summary='Temporary registry evidence',
            payload={'status': status, 'required_sources_complete': state == 'complete'},
            provenance_id=self.provenance)

    def ids(self, **options):
        return [row['id'] for row in self.store.list_records('candidates', **options)]


class CandidateSortingTests(SortingFixture):
    def test_latest_score_overrides_old_evidence_and_zero_is_not_missing(self):
        missing = self.candidate()
        zero = self.candidate()
        strong = self.candidate()
        superseded = self.candidate()
        self.score(zero, 0.)
        self.score(strong, .8)
        self.score(superseded, .99)
        self.score(superseded, state='incomplete')
        self.assertEqual(self.ids(sort='score_desc'), [strong, zero, superseded, missing])
        self.assertEqual(self.ids(sort='score_asc'), [zero, strong, superseded, missing])
        rows = {row['id']: row for row in self.store.list_records('candidates', sort='score_desc')}
        self.assertEqual(rows[zero]['assessment']['score'], 0.)
        self.assertIsNone(rows[superseded]['assessment']['score'])
        self.assertEqual(rows[superseded]['assessment']['score_state'], 'incomplete')

    def test_equal_scores_use_stable_creation_and_identity_ties_across_pages(self):
        older = self.candidate(created='2026-01-01T00:00:00Z')
        same_day = [self.candidate(created='2026-01-02T00:00:00Z') for _ in range(3)]
        for candidate in [older, *same_day]:
            self.score(candidate, .5)
        expected = sorted(same_day, reverse=True) + [older]
        self.assertEqual(self.ids(sort='score_desc'), expected)
        pages = self.ids(sort='score_desc', limit=2) + self.ids(sort='score_desc', limit=2, offset=2)
        self.assertEqual(pages, expected)
        self.assertEqual(len(set(pages)), 4)
        self.assertEqual(self.ids(sort='score_asc'), expected)

    def test_period_order_is_numeric_and_ties_are_stable(self):
        long = self.candidate(period=10.)
        middle = self.candidate(period=2.)
        short = self.candidate(period=.5)
        middle_new = self.candidate(period=2.)
        self.assertEqual(self.ids(sort='period_asc'), [short, middle_new, middle, long])
        self.assertEqual(self.ids(sort='period_desc'), [long, middle_new, middle, short])

    def test_target_order_is_numeric_then_case_insensitive_text(self):
        targets = ['100', '9', '2', 'Beta', 'alpha', 'ALPHA', '00010']
        identifiers = {target: self.candidate(target=target) for target in targets}
        self.assertEqual(self.ids(sort='target'), [identifiers[target] for target in
                         ['2', '9', '00010', '100', 'ALPHA', 'alpha', 'Beta']])

    def test_dates_default_oldest_identity_ties_and_review_updates(self):
        oldest = self.candidate(created='2026-01-01T00:00:00Z')
        newer = [self.candidate(created='2026-01-02T00:00:00Z') for _ in range(2)]
        self.assertEqual(self.ids(), sorted(newer, reverse=True) + [oldest])
        self.assertEqual(self.ids(sort='newest'), self.ids())
        self.assertEqual(self.ids(sort='oldest'), [oldest] + sorted(newer))
        self.store.review_candidate(oldest, status='on_hold', reviewer='fixture', note='Review changes update order.', expected_revision=0)
        self.assertEqual(self.ids(sort='updated')[0], oldest)
        self.assertEqual(self.ids(sort='newest')[-1], oldest)
        self.assertEqual(self.ids(sort='updated', review_status='on_hold'), [oldest])

    def test_cohort_review_and_latest_registry_filters_compose_before_pagination(self):
        desired = self.candidate()
        superseded = self.candidate()
        other_cohort = self.candidate(cohort='known_object_control')
        not_reviewed = self.candidate()
        for candidate in [desired, superseded, other_cohort, not_reviewed]:
            self.registry(candidate, 'UNMATCHED')
            self.score(candidate, .5)
        self.registry(superseded, 'KNOWN_PLANET')
        for candidate in [desired, superseded, other_cohort]:
            self.store.review_candidate(candidate, status='on_hold', reviewer='fixture', note='Filter fixture.', expected_revision=0)
        rows = self.store.list_records('candidates', cohort='archival_pilot', review_status='on_hold',
                                       registry_status='UNMATCHED', sort='score_desc', limit=1)
        self.assertEqual([row['id'] for row in rows], [desired])
        self.assertEqual(rows[0]['assessment']['registry_status'], 'UNMATCHED')
        self.assertEqual(self.ids(registry_status='KNOWN_PLANET'), [superseded])
        self.assertEqual(self.ids(cohort='archival_pilot', review_status='on_hold',
                                  registry_status='UNMATCHED', sort='score_desc', limit=1, offset=1), [])

    def test_null_or_absent_latest_registry_is_not_run_and_later_incomplete_wins(self):
        absent = self.candidate()
        null = self.candidate()
        stale_match = self.candidate()
        self.registry(null, 'KNOWN_PLANET')
        self.registry(null, None)
        self.registry(stale_match, 'UNMATCHED')
        self.registry(stale_match, 'INCOMPLETE_LOOKUP')
        self.assertEqual(self.ids(registry_status='NOT_RUN'), [null, absent])
        self.assertEqual(self.ids(registry_status='UNMATCHED'), [])
        self.assertEqual(self.ids(registry_status='KNOWN_PLANET'), [])
        self.assertEqual(self.ids(registry_status='INCOMPLETE_LOOKUP'), [stale_match])
        rows = self.store.list_records('candidates', registry_status='NOT_RUN')
        self.assertTrue(all(row['assessment']['registry_status'] == 'NOT_RUN' for row in rows))

    def test_sort_and_registry_filters_reject_unsupported_values_and_non_candidate_lists(self):
        for invalid in ('', 'strongest', 'score_desc; DROP TABLE candidates', 'newest DESC', 1):
            with self.assertRaises(ValidationError):
                self.store.list_records('candidates', sort=invalid)
        for invalid in ('', 'PLANET', 'UNMATCHED OR 1=1', 1):
            with self.assertRaises(ValidationError):
                self.store.list_records('candidates', registry_status=invalid)
        for table in ('jobs', 'releases', 'products', 'protocols'):
            for options in ({'sort': 'newest'}, {'registry_status': 'UNMATCHED'}):
                with self.assertRaises(ValidationError):
                    self.store.list_records(table, **options)


class CandidateSortingHTTPTests(SortingFixture):
    def setUp(self):
        super().setUp()
        self.server = ResearchServer(('127.0.0.1', 0), self.store,
                                     ArtifactStore(self.root / 'artifacts', self.store), self.protocol['id'])
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def request(self, path):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def get(self, **options):
        status, result = self.request('/api/candidates?' + urlencode(options))
        self.assertEqual(status, 200, result)
        return result

    def test_global_score_sort_happens_before_first_fifty_and_pagination(self):
        candidates = []
        for number in range(65):
            candidate = self.candidate()
            self.score(candidate, .999 if number == 0 else number / 100)
            candidates.append(candidate)
        newest = self.get(limit=50)['items']
        self.assertNotIn(candidates[0], [row['id'] for row in newest])
        first = self.get(sort='score_desc', limit=50)['items']
        second = self.get(sort='score_desc', limit=50, offset=50)['items']
        self.assertEqual(first[0]['id'], candidates[0])
        self.assertEqual(first[0]['assessment']['score'], .999)
        combined = [row['id'] for row in first + second]
        self.assertEqual(combined, [candidates[0]] + candidates[:0:-1])
        self.assertEqual(len(set(combined)), 65)

    def test_api_latest_score_and_registry_filters_match_visible_assessment(self):
        zero = self.candidate()
        old_high = self.candidate()
        for candidate in [zero, old_high]:
            self.registry(candidate, 'UNMATCHED')
        self.score(zero, 0.)
        self.score(old_high, .99)
        self.score(old_high, state='incomplete')
        self.registry(old_high, 'INCOMPLETE_LOOKUP')
        rows = self.get(sort='score_asc')['items']
        self.assertEqual([row['id'] for row in rows], [zero, old_high])
        self.assertIsNone(rows[1]['assessment']['score'])
        filtered = self.get(sort='score_desc', registry_status='UNMATCHED', cohort='archival_pilot')['items']
        self.assertEqual([row['id'] for row in filtered], [zero])
        self.assertEqual(filtered[0]['assessment']['registry_status'], 'UNMATCHED')

    def test_every_documented_sort_and_registry_status_is_accepted(self):
        self.candidate()
        for sort in ('score_desc', 'score_asc', 'newest', 'oldest', 'updated', 'period_asc', 'period_desc', 'target'):
            self.assertEqual(len(self.get(sort=sort)['items']), 1)
        for status in [item.value for item in AssessmentStatus] + ['NOT_RUN']:
            self.get(registry_status=status)

    def test_invalid_duplicate_injection_and_non_candidate_query_arguments_return_400(self):
        candidate = self.candidate()
        paths = ['/api/candidates?sort=score_desc&sort=newest',
                 '/api/candidates?registry_status=UNMATCHED&registry_status=KNOWN_PLANET',
                 '/api/candidates?sort=', '/api/candidates?registry_status=',
                 '/api/candidates?unknown=score_desc', '/api/candidates?offset=-1',
                 '/api/candidates?' + urlencode({'sort': 'score_desc; DROP TABLE candidates'}),
                 '/api/candidates?' + urlencode({'registry_status': "UNMATCHED' OR 1=1 --"})]
        paths += [f'/api/{table}?{query}' for table in ('jobs', 'releases', 'products')
                  for query in ('sort=newest', 'registry_status=UNMATCHED')]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 400)
        self.assertEqual([row['id'] for row in self.get()['items']], [candidate])


if __name__ == '__main__':
    unittest.main()
