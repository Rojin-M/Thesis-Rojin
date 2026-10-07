"""Offline new-target discovery, bounded sampling and durable exclusion audit."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.research.discovery import discover_targets, validate_discovery
from scripts.research.protocol import ConflictError, ValidationError, load_protocol
from scripts.research.store import Store
from scripts.research.watcher_store import WatchStore


def observation(tic, **changes):
    now_mjd = (datetime.now(timezone.utc) - datetime(1858, 11, 17, tzinfo=timezone.utc)).total_seconds() / 86400
    return {'obsid': str(10000 + tic), 'obs_collection': 'TESS', 'provenance_name': 'SPOC',
            'dataproduct_type': 'timeseries', 'target_name': str(tic), 'dataRights': 'PUBLIC',
            'dataURL': f'mast:TESS/product/tess2025001000000-s0090-{tic:016d}-0001-s_lc.fits',
            't_obs_release': now_mjd - 1, 't_min': now_mjd - 30, 'sequence_number': 90, **changes}


class Archive:
    def __init__(self, pages, total_pages=None):
        self.pages = pages
        self.total_pages = total_pages or len(pages)
        self.calls = []

    def query(self, request):
        self.calls.append(deepcopy(request))
        rows = self.pages[request['page'] - 1]
        return json.dumps({'status': 'COMPLETE', 'data': rows,
                           'paging': {'page': request['page'], 'pagesFiltered': self.total_pages,
                                      'rowsFiltered': max(sum(map(len, self.pages)), len(rows))}}).encode()


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'state' / 'research.sqlite3').initialize()
        self.protocol = self.store.register_protocol(load_protocol())
        self.settings = {'lookback_days': 365, 'max_pages': 3, 'page_size': 100,
                         'max_targets': 18, 'poll_seconds': 21600}
        self.addCleanup(patch.stopall)
        patch('requests.sessions.Session.request', side_effect=AssertionError('Live network forbidden')).start()

    def discover(self, archive, **kwargs):
        return discover_targets(self.store, self.settings, client=archive, root=self.root, **kwargs)

    def csv(self, path, targets):
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text('tic_id,period\n' + ''.join(f'{target},999\n' for target in targets))

    def provenance(self):
        return self.store.register_provenance(kind='fixture', identity='offline', sha256_digest='0' * 64,
                                              retrieved_at='2026-01-01T00:00:00Z', details={})['id']

    def product(self, tic, number=0):
        provenance = self.provenance()
        release = self.store.register_release(mission='TESS', release_key='fixture',
                                             available_at='2026-01-01T00:00:00Z', provenance_id=provenance)
        return self.store.register_product(release_id=release['id'], product_key=f'{tic}-{number}',
                                           target_id=str(tic), source_uri='fixture', provenance_id=provenance)

    def test_sampled_incomplete_page_selects_new_identities_and_persists_receipts(self):
        self.settings['max_targets'] = 2
        archive = Archive([[observation(333), observation(111), observation(222)]], total_pages=900)
        result = self.discover(archive)
        self.assertEqual(result['targets'], ['111', '222'])
        self.assertEqual(result['status'], 'succeeded')
        self.assertFalse(result['archive_wide_complete'])
        self.assertEqual(len(archive.calls), 1)
        filters = {entry['paramName']: entry['values'] for entry in archive.calls[0]['params']['filters']}
        self.assertNotIn('target_name', filters)
        self.assertEqual(filters['dataRights'], ['PUBLIC'])
        self.assertEqual(filters['provenance_name'], ['SPOC'])
        self.assertAlmostEqual(filters['t_obs_release'][0]['max'] - filters['t_obs_release'][0]['min'], 365)
        self.assertEqual(filters['t_min'], filters['t_obs_release'])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM watch_snapshots').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM watch_queue').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM products').fetchone()[0], 0)
        receipt = result['selected_observations'][0]
        self.assertEqual(receipt['cohort'], 'archival_pilot')
        self.assertTrue(receipt['source_exclusions_sha256'])
        self.assertEqual(json.loads((self.store.path.parent / 'discovery/state.json').read_text())['targets'], result['targets'])

    def test_recent_rerelease_of_old_observations_is_not_new_data(self):
        archive = Archive([[observation(111, t_min=55000), observation(222)]])
        result = self.discover(archive)
        self.assertEqual(result['targets'], ['222'])
        self.assertIn('observation_start_mjd', result['selected_observations'][0])

    def test_manifests_overlap_and_prior_zero_candidate_jobs_are_excluded(self):
        self.csv('data/raw/tess/metadata/manifest.csv', [101])
        self.csv('data/processed/tess/v0/manifest_tess_v0.csv', [102])
        self.csv('data/processed/tess/v0/selection.csv', [103])
        self.csv('data/processed/tess/v0/kepler_overlap.csv', [104])
        self.product(105)
        self.store.create_job(job_key='old-zero-candidate', cohort='archival_pilot',
                              protocol_id=self.protocol['id'], code_provenance_id=self.provenance(),
                              inputs={'mission': 'TESS', 'target_id': '106'})
        archive = Archive([[observation(tic) for tic in range(101, 108)]])
        result = self.discover(archive)
        self.assertEqual(result['targets'], ['107'])
        self.assertEqual(result['source_exclusions']['targets'], 6)
        self.assertTrue(all(source.get('sha256') for source in result['source_exclusions']['sources']))

    def test_restart_retains_own_selected_targets_after_product_registration(self):
        first = self.discover(Archive([[observation(111)]]))
        self.product(111)
        self.store = Store(self.store.path).initialize()
        archive = Archive([[observation(111), observation(222)]])
        not_due = self.discover(archive)
        self.assertEqual(not_due['status'], 'not_due')
        self.assertEqual(not_due['targets'], ['111'])
        self.assertEqual(archive.calls, [])
        result = self.discover(archive, force=True)
        self.assertEqual(result['targets'], ['111', '222'])
        self.assertEqual(result['new_targets'], ['222'])
        self.assertEqual(result['selected_observations'][0], first['selected_observations'][0])
        self.assertEqual(result['config_id'], first['config_id'])

    def test_invalid_private_future_old_fast_and_other_mission_rows_are_ignored(self):
        rows = [observation(111, dataRights='PRIVATE'), observation(222, t_obs_release=90000),
                observation(333, t_obs_release=55000), observation(444, obs_collection='Kepler'),
                observation(555, dataproduct_type='image'),
                observation(666, dataURL=observation(666)['dataURL'].replace('-s_lc', '-a_fast-lc')),
                observation(777, target_name='000777'), observation(888)]
        result = self.discover(Archive([rows]))
        self.assertEqual(result['targets'], ['888'])

    def test_bounded_pages_deduplicate_tics_without_global_completeness_claim(self):
        archive = Archive([[observation(111)], [observation(111), observation(222)], [observation(333)]], total_pages=99)
        result = self.discover(archive)
        self.assertEqual(result['targets'], ['111', '222', '333'])
        self.assertEqual([request['page'] for request in archive.calls], [1, 2, 3])
        self.assertFalse(result['archive_wide_complete'])

    def test_wrong_page_and_overlarge_page_fail_with_audited_raw_snapshot(self):
        archive = Archive([[observation(111)]])
        original = archive.query

        def wrong_page(request):
            value = json.loads(original(request))
            value['paging']['page'] = 2
            return json.dumps(value).encode()

        archive.query = wrong_page
        failed = self.discover(archive)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['targets'], [])
        self.assertEqual(len(failed['snapshots']), 1)
        self.settings['page_size'] = 1
        failed = self.discover(Archive([[observation(111), observation(222)]]), force=True)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['targets'], [])

    def test_three_failures_persist_circuit_and_force_cannot_bypass(self):
        archive = Archive([])
        archive.query = lambda request: (_ for _ in ()).throw(OSError('archive unavailable'))
        for _ in range(3):
            self.assertEqual(self.discover(archive, force=True)['status'], 'failed')
        self.store = Store(self.store.path).initialize()
        self.assertEqual(self.discover(archive, force=True)['status'], 'circuit_open')

    def test_budget_exhaustion_prevents_requests_and_keeps_cached_selection(self):
        first = self.discover(Archive([[observation(111)]]))
        WatchStore(self.store).account('prior', 2 * 1024**3, 'offline exhausted budget')
        archive = Archive([[observation(222)]])
        result = self.discover(archive, force=True)
        self.assertEqual(result['targets'], first['targets'])
        self.assertEqual(result['exhausted_reason'], 'network_budget')
        self.assertEqual(archive.calls, [])

    def test_product_cap_prevents_requests(self):
        products = [self.product(111, number)['id'] for number in range(20)]
        WatchStore(self.store).pilot('fixture-cap', {'product_ids': products})
        archive = Archive([[observation(222)]])
        result = self.discover(archive, force=True)
        self.assertEqual(result['exhausted_reason'], 'cumulative_product_or_target_cap')
        self.assertEqual(archive.calls, [])

    def test_existing_unqueued_selection_reserves_remaining_capacity(self):
        self.discover(Archive([[observation(111)]]))
        products = [self.product(999, number)['id'] for number in range(19)]
        WatchStore(self.store).pilot('fixture-cap', {'product_ids': products})
        archive = Archive([[observation(222)]])
        result = self.discover(archive, force=True)
        self.assertEqual(result['targets'], ['111'])
        self.assertEqual(archive.calls, [])

    def test_strict_settings_and_no_shrinking_persisted_selection(self):
        for key in self.settings:
            with self.assertRaises(ValidationError):
                validate_discovery({**self.settings, key: True})
        for key, value in [('max_targets', 19), ('max_pages', 4), ('page_size', 101), ('lookback_days', 731)]:
            with self.assertRaises(ValidationError):
                validate_discovery({**self.settings, key: value})
        self.discover(Archive([[observation(111), observation(222)]]))
        self.settings['max_targets'] = 1
        with self.assertRaises(ConflictError):
            self.discover(Archive([]))


if __name__ == '__main__':
    unittest.main()
