"""Probability annotations agree across live API/export without rewriting evidence."""
import http.client
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest

from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import load_protocol
from scripts.research.scoring import CHECKPOINT_SHA, NORMALIZER_SHA
from scripts.research.server import ResearchServer
from scripts.research.store import Store


class ProbabilityHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / 'research.sqlite3').initialize()
        protocol = self.store.register_protocol(load_protocol())
        self.prov = self.store.register_provenance(kind='code', identity='probability-http-test',
            sha256_digest='a' * 64, retrieved_at='2026-01-01T00:00:00Z', details={'fixture': True})
        job = self.store.create_job(job_key='temporary-archival-test', cohort='archival_pilot',
            protocol_id=protocol['id'], code_provenance_id=self.prov['id'])
        candidate = self.store.put_candidate(job_id=job['id'], signal_key='test-1', target_id='TEST-ONLY',
            mission='TESS', period_days=3., epoch=1500., epoch_system='BTJD', duration_hours=2.,
            detection={'method':'test', 'ephemeris_origin':'blind_search', 'used_catalog_ephemeris':False},
            provenance_id=self.prov['id'])
        self.cid = candidate['id']
        self.score_payload = {'score':.7, 'logit':math.log(.7/.3), 'input_contract':'shared_v1',
            'model_sha256':CHECKPOINT_SHA, 'normalization_sha256':NORMALIZER_SHA}
        self.store.put_evidence(candidate_id=self.cid, evidence_key='original-score', kind='model_score',
            state='complete', summary='Temporary test score', payload=self.score_payload, provenance_id=self.prov['id'])
        self.store.review_candidate(self.cid, status='on_hold', reviewer='test reviewer',
            note='Preserve this review and original score.', expected_revision=0)
        self.server = ResearchServer(('127.0.0.1',0), self.store, ArtifactStore(root/'artifacts',self.store), protocol['id'])
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def get(self, path):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        try:
            connection.request('GET',path)
            response=connection.getresponse()
            payload=response.read()
            self.assertEqual(response.status,200)
            return json.loads(payload) if response.getheader('Content-Type','').startswith('application/json') else payload.decode()
        finally:
            connection.close()

    def record_counts(self):
        with self.store.connection() as db:
            return {table:db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                for table in ['evidence','events','reviews','provenance','candidates','jobs']}

    def test_annotated_api_and_exports_agree_without_changing_evidence_or_reviews(self):
        before=self.record_counts()
        detail=self.get('/api/candidates/'+self.cid)
        listed=self.get('/api/candidates?cohort=archival_pilot')['items'][0]
        exported=self.get('/api/candidates/'+self.cid+'/report.json')['candidate']
        report=self.get('/api/candidates/'+self.cid+'/report.md')
        p=detail['probability']
        self.assertIsNone(p['planet_probability'])
        self.assertEqual(p['planet_probability_status'],'unavailable')
        self.assertEqual(p['benchmark']['status'],'available')
        self.assertGreater(p['benchmark']['estimate'],0)
        self.assertLess(p['benchmark']['estimate'],1)
        self.assertNotAlmostEqual(p['benchmark']['estimate'],self.score_payload['score'])
        self.assertEqual(p['benchmark']['applicability'],'not_validated_for_blind_search')
        self.assertEqual(p,listed['assessment']['probability'])
        self.assertEqual(p,detail['assessment']['probability'])
        self.assertEqual(p,exported['probability'])
        self.assertEqual(detail['assessment']['score'],.7)
        self.assertFalse(detail['assessment']['confirmation_probability'])
        self.assertEqual(detail['evidence'][0]['payload'],self.score_payload)
        self.assertEqual(detail['review_status'],'on_hold')
        self.assertEqual(detail['revision'],1)
        self.assertEqual(detail['reviews'][0]['note'],'Preserve this review and original score.')
        self.assertIn('Planet probability: unavailable',report)
        self.assertIn('Experimental TESS benchmark estimate',report)
        self.assertIn("not this signal's probability of being a planet",report)
        self.assertIn(f"{100*p['benchmark']['estimate']:.1f}%",report)
        self.assertIn(p['benchmark']['calibration_id'],report)
        self.assertEqual(before,self.record_counts())

    def test_latest_incomplete_score_suppresses_old_estimate_in_all_exports(self):
        self.store.put_evidence(candidate_id=self.cid,evidence_key='later-score-failure',kind='model_score',
            state='incomplete',summary='Later input validation failed; old estimate must not be shown.',
            provenance_id=self.prov['id'])
        detail=self.get('/api/candidates/'+self.cid)
        listed=self.get('/api/candidates')['items'][0]
        report=self.get('/api/candidates/'+self.cid+'/report.md')
        self.assertIsNone(detail['assessment']['score'])
        self.assertIsNone(detail['probability']['planet_probability'])
        self.assertEqual(detail['probability']['benchmark']['status'],'unavailable')
        self.assertIsNone(detail['probability']['benchmark']['estimate'])
        self.assertEqual(detail['probability'],listed['assessment']['probability'])
        self.assertIn('Experimental benchmark estimate unavailable',report)
        self.assertEqual(len(detail['evidence_history']),2)
        self.assertEqual(detail['review_status'],'on_hold')


if __name__=='__main__':
    unittest.main()
