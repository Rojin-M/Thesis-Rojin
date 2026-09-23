import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import ConflictError, ValidationError, load_protocol
from scripts.research.store import Store, _one
from scripts.research.watcher import create_pilot, dispatch, load_config, poll_once, repin_failed_pilot
from scripts.research.watcher_store import WatchStore, exclusive_lock, later, status
from tests.test_research_watcher import ReplayClient


class WatcherRepinTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / 'research.sqlite3').initialize()
        self.ledger = WatchStore(self.store)
        self.protocol = self.store.register_protocol(load_protocol())
        self.artifacts = ArtifactStore(self.root / 'artifacts', self.store)
        self.client = ReplayClient(size=1000)
        poll = poll_once(self.store, {**load_config(), 'targets': ['123']}, client=self.client, force=True)
        self.product_id = poll['product_ids'][0]
        self.old_code = {'manifest_sha256': 'a' * 64, 'files': {'fixture.py': 'b' * 64}}
        self.new_code = {'manifest_sha256': 'c' * 64, 'files': {'fixture.py': 'd' * 64}}
        self.pilot_id = 'auto-v1:' + self.product_id
        self.replacement_id = self.pilot_id + ':repin1'
        with patch('scripts.research.watcher.code_snapshot', return_value=self.old_code):
            create_pilot(self.store, self.protocol['id'], pilot_id=self.pilot_id,
                         product_ids=[self.product_id], cohort='archival_pilot', max_bytes=5000, max_seconds=100)
        dispatch_id, _ = self.ledger.dispatch_start(self.pilot_id)
        self.ledger.dispatch_finish(dispatch_id, 7.25, 'failed')
        self.ledger.queue(self.product_id, state='failed', attempts=1, next_attempt_at=later(60),
                          error={'code': 'OSError', 'message': 'Fixture failed before acquisition', 'retryable': True})
        settled = self.ledger.reserve(200, 'science_product', self.pilot_id)
        self.ledger.settle(settled, 80, {'fixture': True})
        self.ledger.reserve(300, 'science_product', self.pilot_id)

    def repin(self):
        with patch('scripts.research.watcher.code_snapshot', return_value=self.new_code):
            return repin_failed_pilot(self.store, pilot_id=self.pilot_id,
                                      replacement_id=self.replacement_id, reason='Fixture downloader correction')

    def pilot(self, pilot_id):
        with self.store.connection() as connection:
            return _one(connection, 'SELECT * FROM watch_pilots WHERE id=?', (pilot_id,))

    def frozen_rows(self, table):
        with self.store.connection() as connection:
            return [tuple(row) for row in connection.execute('SELECT * FROM ' + table + ' ORDER BY id')]

    def test_repin_preserves_history_attempts_and_cumulative_allowances(self):
        old = self.pilot(self.pilot_id)
        spending = self.frozen_rows('watch_spending')
        dispatches = self.frozen_rows('watch_dispatches')
        before = status(self.store)
        result = self.repin()
        replacement = self.pilot(self.replacement_id)
        self.assertEqual(result['status'], 'repinned')
        self.assertEqual(replacement['spec']['max_bytes'], 4620)
        self.assertEqual(replacement['spec']['max_seconds'], 92)
        self.assertEqual(replacement['spec']['code'], self.new_code)
        for name in ('product_ids', 'cohort', 'protocol_id', 'catalog_mode', 'selection', 'workers'):
            self.assertEqual(replacement['spec'][name], old['spec'][name])
        original = self.pilot(self.pilot_id)
        self.assertEqual(original, {**old, 'status': 'superseded'})
        self.assertEqual(self.frozen_rows('watch_spending'), spending)
        self.assertEqual(self.frozen_rows('watch_dispatches'), dispatches)
        after = status(self.store)
        self.assertEqual(after['budget'], before['budget'])
        self.assertEqual(len(after['queue']), 1)
        previous_queue = before['queue'][0]
        new_queue = after['queue'][0]
        for name in ('state', 'attempts', 'next_attempt_at', 'receipt', 'job_id', 'error'):
            self.assertEqual(new_queue[name], previous_queue[name])
        self.assertEqual(new_queue['pilot_id'], self.replacement_id)
        provenance = self.store.get_provenance(result['provenance_id'])['document']
        self.assertEqual(provenance['kind'], 'pilot_repin')
        self.assertEqual(provenance['details']['old_code'], self.old_code)
        self.assertEqual(provenance['details']['new_code'], self.new_code)
        self.assertEqual(provenance['details']['reason'], 'Fixture downloader correction')
        with self.store.connection() as connection:
            audit = json.loads(connection.execute("SELECT payload_json FROM events WHERE kind='watch_pilot_repinned'").fetchone()[0])
        self.assertEqual(audit['provenance_id'], result['provenance_id'])
        self.assertEqual(audit['old_pilot_id'], self.pilot_id)
        self.assertEqual(audit['new_pilot_id'], self.replacement_id)
        with self.assertRaises(ConflictError):
            dispatch(self.store, self.artifacts, self.pilot_id, client=self.client)
        with self.assertRaises(ConflictError):
            self.repin()

    def test_repin_refuses_service_or_dispatch_lock(self):
        for lock in (self.store.path.with_suffix('.watch-service.lock'), self.ledger.lock_path):
            with self.subTest(lock=lock), exclusive_lock(lock), self.assertRaises(ConflictError):
                self.repin()

    def test_repin_refuses_acquired_or_exhausted_queue(self):
        for changes in ({'attempts': 3}, {'receipt': {}}, {'state': 'acquired'}):
            with self.subTest(changes=changes):
                self.ledger.queue(self.product_id, **changes)
                with self.assertRaises(ConflictError):
                    self.repin()
                self.ledger.queue(self.product_id, state='failed', attempts=1, receipt=None)

    def test_repin_refuses_published_sidecar_even_without_database_receipt(self):
        directory = self.root / 'watcher' / 'products' / self.product_id
        directory.mkdir(parents=True)
        (directory / 'receipt.json').write_text('{}')
        with self.assertRaisesRegex(ConflictError, 'published acquisition'):
            self.repin()

    def test_repin_refuses_missing_or_nonretryable_failure(self):
        for error in (None, {'code': 'ValidationError', 'message': 'Invalid fixture source', 'retryable': False}):
            with self.subTest(error=error):
                self.ledger.queue(self.product_id, error=error)
                with self.assertRaisesRegex(ConflictError, 'retryable acquisition failure'):
                    self.repin()

    def test_repin_refuses_existing_unlinked_job(self):
        with self.store.connection() as connection:
            provenance_id = connection.execute('SELECT id FROM provenance LIMIT 1').fetchone()[0]
        self.store.create_job(job_key='watch-bls-v1:' + self.product_id, cohort='archival_pilot',
                              protocol_id=self.protocol['id'], code_provenance_id=provenance_id)
        with self.assertRaisesRegex(ConflictError, 'existing processing job'):
            self.repin()

    def test_repin_refuses_active_dispatch_record_and_stage_lease(self):
        with self.store.connection(True) as connection:
            connection.execute("UPDATE watch_dispatches SET status='running'")
        with self.assertRaisesRegex(ConflictError, 'Active dispatches'):
            self.repin()
        with self.store.connection(True) as connection:
            connection.execute("UPDATE watch_dispatches SET status='failed'")
            provenance_id = connection.execute('SELECT id FROM provenance LIMIT 1').fetchone()[0]
        job = self.store.create_job(job_key='independent-fixture', cohort='synthetic_fixture',
                                    protocol_id=self.protocol['id'], code_provenance_id=provenance_id)
        self.store.claim_stage(job['id'], 'metadata', worker='fixture')
        with self.assertRaisesRegex(ConflictError, 'stage leases'):
            self.repin()

    def test_repin_refuses_exhausted_original_byte_budget(self):
        self.ledger.reserve(4000, 'science_product', self.pilot_id)
        with self.assertRaisesRegex(ValidationError, 'Remaining original'):
            self.repin()
        self.assertEqual(len(status(self.store)['pilots']), 1)

    def test_repin_refuses_exhausted_original_runtime_budget(self):
        with self.store.connection(True) as connection:
            connection.execute('UPDATE watch_pilots SET runtime_charged=99.5 WHERE id=?', (self.pilot_id,))
        with self.assertRaisesRegex(ValidationError, 'Remaining original'):
            self.repin()
        self.assertEqual(len(status(self.store)['pilots']), 1)

    def test_repin_refuses_unchanged_source_empty_reason_and_same_identity(self):
        with patch('scripts.research.watcher.code_snapshot', return_value=self.old_code), self.assertRaisesRegex(ConflictError, 'matches'):
            repin_failed_pilot(self.store, pilot_id=self.pilot_id, replacement_id=self.replacement_id, reason='Unchanged')
        with self.assertRaises(ValidationError):
            repin_failed_pilot(self.store, pilot_id=self.pilot_id, replacement_id=self.replacement_id, reason=' ')
        with self.assertRaises(ValidationError):
            repin_failed_pilot(self.store, pilot_id=self.pilot_id, replacement_id=self.pilot_id, reason='Same identity')

    def test_cli_repin_preserves_backoff_and_dispatch_attempt_cap(self):
        command = [sys.executable, '-m', 'scripts.research', '--db', str(self.store.path),
                   '--artifacts', str(self.root / 'artifacts'), 'watch-repin', '--pilot-id', self.pilot_id,
                   '--replacement-id', self.replacement_id, '--reason', 'Explicit CLI fixture recovery']
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['attempts'], 1)
        self.client.fail = True
        dispatch(self.store, self.artifacts, self.replacement_id, client=self.client)
        self.assertEqual(self.client.downloads, 0)
        for _ in range(3):
            self.ledger.queue(self.product_id, next_attempt_at=None)
            dispatch(self.store, self.artifacts, self.replacement_id, client=self.client)
        self.assertEqual(self.client.downloads, 2)
        self.assertEqual(status(self.store)['queue'][0]['attempts'], 3)


if __name__ == '__main__':
    unittest.main()
