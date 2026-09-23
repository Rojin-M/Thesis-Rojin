"""Preservation and safe restoration of frozen research records; no network."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import sqlite3

from scripts.analysis import vetting_snapshot
from scripts.analysis.vetting_snapshot import ARCHIVE, DATABASE, checksum, create, restore, save_json, verify
from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import load_protocol
from scripts.research.store import Store


class VettingSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.store = Store(self.root / DATABASE).initialize()
        protocol = self.store.register_protocol(load_protocol())
        provenance = self.store.register_provenance(kind='fixture', identity='backup-test',
            sha256_digest='a' * 64, retrieved_at='2026-01-01T00:00:00Z', details={'synthetic': True})
        self.input = self.root / 'data/raw/fixture.npz'
        self.input.parent.mkdir(parents=True)
        self.input.write_bytes(b'Backup-only synthetic input, not a scientific NPZ')
        job = self.store.create_job(job_key='backup-fixture', cohort='archival_pilot',
            protocol_id=protocol['id'], code_provenance_id=provenance['id'],
            inputs={'paths': [str(self.input)], 'sha256': {str(self.input): checksum(self.input)}})
        candidate = self.store.put_candidate(job_id=job['id'], signal_key='fixture', target_id='123', mission='TESS',
            period_days=3, epoch=1500, epoch_system='BTJD', duration_hours=2,
            detection={'method': 'backup_test_fixture', 'ephemeris_origin': 'blind_search',
                       'used_catalog_ephemeris': False, 'fixture_only': True}, provenance_id=provenance['id'])
        self.cid = candidate['id']
        self.artifacts = ArtifactStore(self.root / 'outputs/research/artifacts', self.store)
        plot = {'kind': 'time_series', 'title': 'Synthetic backup test', 'x_label': 'Time', 'y_label': 'Flux',
                'time_system': 'BTJD', 'x': [1, 2, 3], 'y': [1, .9, 1]}
        for key in ('plot-1', 'plot-2'):
            self.artifacts.put_plot(plot, candidate_id=self.cid, artifact_key=key, filename=key + '.json')
        self.store.review_candidate(self.cid, status='in_review', reviewer='fixture reviewer',
            note='First preserved review', expected_revision=0)
        self.store.review_candidate(self.cid, status='on_hold', reviewer='fixture reviewer',
            note='Second preserved review', expected_revision=1)
        self.snapshot = self.base / 'snapshot'

    def test_roundtrip_preserves_database_reviews_deduplicated_artifacts_and_inputs(self):
        manifest = create(self.root, self.snapshot)
        self.assertEqual(manifest['counts']['artifacts'], 2)
        self.assertEqual(manifest['file_counts_by_kind']['artifact'], 1)
        self.assertEqual(manifest['counts']['reviews'], 2)
        self.assertEqual(verify(self.snapshot), manifest)
        restored = self.base / 'restored'
        restore(self.snapshot, restored)
        store = Store(restored / DATABASE)
        c = store.get_candidate(self.cid)
        self.assertEqual(c['review_status'], 'on_hold')
        self.assertEqual([r['note'] for r in c['reviews']], ['First preserved review', 'Second preserved review'])
        blobs = ArtifactStore(restored / 'outputs/research/artifacts', store)
        for a in c['artifacts']:
            self.assertEqual(blobs.read(a['id'])[1], self.artifacts.read(a['id'])[1])
        self.assertEqual((restored / 'data/raw/fixture.npz').read_bytes(), self.input.read_bytes())
        db_record = next(r for r in manifest['files'] if r['path'] == DATABASE)
        self.assertEqual(checksum(restored / DATABASE), db_record['sha256'])
        public = json.loads((self.snapshot / 'vetting.json').read_text())
        self.assertEqual(len(public['candidates'][0]['reviews']), 2)

    def test_changed_source_fails_without_publishing_snapshot(self):
        self.input.write_bytes(b'changed after processing')
        with self.assertRaisesRegex(ValueError, 'recorded hash'):
            create(self.root, self.snapshot)
        self.assertFalse(self.snapshot.exists())

    def test_database_handles_close_before_temporary_directory_cleanup(self):
        connections = []
        original = vetting_snapshot.read_database

        def record(path):
            db = original(path)
            connections.append(db)
            return db

        with patch.object(vetting_snapshot, 'read_database', side_effect=record):
            create(self.root, self.snapshot)
            restore(self.snapshot, self.base / 'restored')
        for db in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')

    def test_corrupt_archive_fails_without_publishing_restore(self):
        create(self.root, self.snapshot)
        with (self.snapshot / ARCHIVE).open('ab') as stream:
            stream.write(b'corruption')
        destination = self.base / 'restored'
        with self.assertRaisesRegex(ValueError, 'checksum or size'):
            restore(self.snapshot, destination)
        self.assertFalse(destination.exists())

    def test_existing_destinations_are_never_overwritten(self):
        create(self.root, self.snapshot)
        with self.assertRaises(FileExistsError):
            create(self.root, self.snapshot)
        destination = self.base / 'restored'
        destination.mkdir()
        sentinel = destination / 'keep.txt'
        sentinel.write_text('existing user data')
        with self.assertRaises(FileExistsError):
            restore(self.snapshot, destination)
        self.assertEqual(sentinel.read_text(), 'existing user data')

    def test_traversal_in_checksumming_valid_archive_is_rejected(self):
        manifest = create(self.root, self.snapshot)
        path = self.snapshot / ARCHIVE
        with tarfile.open(path, 'w:gz') as archive:
            info = tarfile.TarInfo('../escaped.txt')
            info.size = 4
            archive.addfile(info, io.BytesIO(b'evil'))
        manifest['archive'].update(bytes=path.stat().st_size, sha256=checksum(path))
        save_json(self.snapshot / 'manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'Unsafe archive path'):
            restore(self.snapshot, self.base / 'restored')
        self.assertFalse((self.base / 'escaped.txt').exists())


if __name__ == '__main__':
    unittest.main()
