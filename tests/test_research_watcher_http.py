"""Actual loopback archive HTTP -> download -> blind pipeline -> research API.

The archive fixture lives only in a temporary store, labelled by the fixture
README; its generated photometry is not scientific release evidence.
"""
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from scripts.research import mast
from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import load_protocol
from scripts.research.scoring import CHECKPOINT, NORMALIZER
from scripts.research.server import ResearchServer
from scripts.research.store import Store
from scripts.research.watcher import create_pilot, dispatch, load_config, poll_once
from scripts.research.watcher_store import WatchStore, status
from tests.support import ReplayClient, write_fits


@unittest.skipUnless(CHECKPOINT.is_file() and NORMALIZER.is_file(),'Locally retained model required for whole-pipeline integration')
class WatcherHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.source=cls.root/'fixture.fits';write_fits(cls.source)
        cls.fixture=ReplayClient(cls.source,size=cls.source.stat().st_size)
        cls.download_requests=0
        fixture=cls.fixture
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                raw=fixture.query(json.loads(data['request'][0]))
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                cls.download_requests+=1
                uri=parse_qs(urlsplit(self.path).query)['uri'][0]
                if not uri.startswith('mast:TESS/product/'):raise AssertionError('unbounded download')
                raw=cls.source.read_bytes()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        cls.archive=HTTPServer(('127.0.0.1',0),Handler)
        cls.archive_thread=threading.Thread(target=cls.archive.serve_forever,kwargs={'poll_interval':.02},daemon=True);cls.archive_thread.start()
        cls.store=Store(cls.root/'research.sqlite3').initialize();cls.protocol=cls.store.register_protocol(load_protocol())
        cls.artifacts=ArtifactStore(cls.root/'artifacts',cls.store)
        config={**load_config(),'targets':['123']}
        base='http://127.0.0.1:'+str(cls.archive.server_port)
        # Fixed endpoints are changed only in this isolated test process.
        with patch.object(mast,'INVOKE',base+'/invoke'),patch.object(mast,'DOWNLOAD',base+'/file'):
            cls.poll=poll_once(cls.store,config,force=True)
            if cls.poll['status']!='succeeded':raise AssertionError(cls.poll)
            cls.pilot=create_pilot(cls.store,cls.protocol['id'],pilot_id='http-fixture',product_ids=cls.poll['product_ids'],
                cohort='known_object_control',max_bytes=4*1024**2,max_seconds=300)
            cls.result=dispatch(cls.store,cls.artifacts,cls.pilot['id'])
        if cls.result['status']!='complete':raise AssertionError(cls.result)
        cls.jid=cls.result['outcomes'][0]['job_id']
        cls.ids=[c['id'] for c in sorted(cls.store.list_records('candidates'),key=lambda c:c['detection']['rank'])]
        cls.server=ResearchServer(('127.0.0.1',0),cls.store,cls.artifacts,cls.protocol['id'])
        cls.thread=threading.Thread(target=cls.server.serve_forever,kwargs={'poll_interval':.02},daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(5)
        cls.archive.shutdown();cls.archive.server_close();cls.archive_thread.join(5);cls.tmp.cleanup()
    def request(self,path,method='GET',headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        self.addCleanup(c.close);c.request(method,path,headers=headers or {});r=c.getresponse();raw=r.read()
        return r.status,json.loads(raw) if r.getheader('Content-Type','').startswith('application/json') else raw
    def test_public_pipeline_real_http_sources_scores_ephemeris_and_report(self):
        code,w=self.request('/api/watcher');self.assertEqual(code,200)
        self.assertEqual(w['queue'][0]['state'],'complete');self.assertGreater(w['budget']['charged_bytes'],self.source.stat().st_size)
        self.assertEqual(self.download_requests,1)
        job=self.store.get_job(self.jid)
        self.assertTrue(all(s['status']=='succeeded' and s['attempts']==1 for s in job['stages']))
        self.assertIsNotNone(job['product_id']);self.assertIsNotNone(job['release_id'])
        self.assertGreater(len(self.ids),0)
        _,c=self.request('/api/candidates/'+self.ids[0])
        self.assertEqual(c['detection']['used_catalog_ephemeris'],False)
        self.assertAlmostEqual(c['ephemeris']['period_days'],3.22,delta=.02)
        self.assertGreater(c['ephemeris']['epoch_bjd_tdb'],2457000)
        self.assertIsNotNone(c['assessment']['score']);self.assertEqual(c['assessment']['registry_status'],'INCOMPLETE_LOOKUP')
        self.assertIn('registry',c['incomplete_evidence']);self.assertIsNotNone(c['product'])
        _,report=self.request('/api/candidates/'+self.ids[0]+'/report.md');self.assertIn(b'Model ranking score',report)
        self.assertEqual(self.request('/api/health')[0],200)
    def test_actual_cli_restart_does_not_redownload_duplicate_or_reprocess(self):
        command=[sys.executable,'-m','scripts.research','--db',str(self.store.path),'--artifacts',str(self.root/'artifacts'),
                 'watch-dispatch','--pilot-id',self.pilot['id']]
        before=status(self.store)['budget']['charged_bytes']
        result=subprocess.run(command,capture_output=True,text=True,timeout=20,
            env={**os.environ,'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['already_complete'])
        self.assertEqual(status(self.store)['budget']['charged_bytes'],before)
        self.assertEqual(len(self.store.list_records('jobs')),1);self.assertEqual(len(self.store.list_records('candidates')),len(self.ids))
        self.assertEqual(self.download_requests,1)
        self.assertEqual(len(self.store.get_job(self.jid)['attempt_history']),8)
    def test_watcher_endpoint_has_no_mutation_launch_route_and_host_protection(self):
        self.assertEqual(self.request('/api/watcher','POST')[0],403)
        self.assertEqual(self.request('/api/watcher',headers={'Host':'evil.example'})[0],403)
        code,html=self.request('/');self.assertEqual(code,200);self.assertIn(b'#watcher',html)
    def test_failed_poll_is_visible_in_actual_api_and_health(self):
        fixture=ReplayClient();fixture.fail=True
        config={**load_config(),'targets':['999']}
        for attempt in range(3):
            poll_once(self.store,config,client=fixture,force=True)
        code,document=self.request('/api/watcher');self.assertEqual(code,200)
        failed=next(c for c in document['configs'] if c['config']['targets']==['999'])
        self.assertEqual(failed['health'],'circuit_open')
        self.assertEqual(failed['failures'],3)
        self.assertIn('simulated MAST outage',failed['last_error']['message'])
        _,health=self.request('/api/health')
        self.assertTrue(any(c['health']=='circuit_open' for c in health['watcher']))


class WatcherCheckHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'research.sqlite3').initialize()
        self.protocol = self.store.register_protocol(load_protocol())
        self.artifacts = ArtifactStore(self.root / 'artifacts', self.store)
        self.ledger = WatchStore(self.store)
        self.server = ResearchServer(('127.0.0.1', 0), self.store, self.artifacts, self.protocol['id'])
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.temporary.cleanup()

    def request(self, path='/api/watcher/check', method='POST', body='{}', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        connection.request(method, path, body if method == 'POST' else None, headers or {})
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def mutation_headers(self):
        code, session = self.request('/api/session', method='GET')
        self.assertEqual(code, 200)
        return {'Origin': self.origin, 'X-CSRF-Token': session['csrf_token'], 'Content-Type': 'application/json'}

    def start_worker(self):
        from scripts.research.automation import load_config as load_automatic_config
        self.ledger.start_automation({**load_automatic_config(), 'targets': ['123'], 'cohort': 'archival_pilot'})

    def test_check_requires_same_origin_and_csrf(self):
        self.start_worker()
        valid = self.mutation_headers()
        for headers in ({}, {**valid, 'Origin': 'https://attacker.invalid'},
                        {**valid, 'X-CSRF-Token': 'incorrect'}, {**valid, 'Sec-Fetch-Site': 'cross-site'},
                        {key: value for key, value in valid.items() if key != 'Origin'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(headers=headers)[0], 403)
        self.assertIsNone(self.request('/api/watcher', method='GET')[1]['automation']['check_request'])

    def test_check_requires_exact_empty_json_object(self):
        self.start_worker()
        headers = self.mutation_headers()
        for body in ('[]', 'null', '{"targets":["999"]}', '{"shell":"anything"}', '{broken', '{} {}'):
            with self.subTest(body=body):
                self.assertEqual(self.request(body=body, headers=headers)[0], 400)
        self.assertEqual(self.request(headers={**headers, 'Content-Type': 'text/plain'})[0], 400)
        self.assertEqual(self.request('/api/watcher/check?force=true', headers=headers)[0], 400)
        self.assertIsNone(self.request('/api/watcher', method='GET')[1]['automation']['check_request'])

    def test_check_queues_durably_and_coalesces_duplicate_clicks(self):
        self.start_worker()
        headers = self.mutation_headers()
        code, first = self.request(headers=headers)
        self.assertEqual(code, 202)
        self.assertEqual(first['status'], 'queued')
        self.assertTrue(first['id'])
        self.assertTrue(first['created_at'])
        code, repeated = self.request(headers=headers)
        self.assertEqual(code, 202)
        self.assertEqual(repeated['id'], first['id'])
        self.ledger.claim_check()
        code, running = self.request(headers=headers)
        self.assertEqual(code, 202)
        self.assertEqual(running['id'], first['id'])
        self.assertEqual(running['status'], 'running')
        _, watcher = self.request('/api/watcher', method='GET')
        self.assertEqual(watcher['automation']['check_request']['id'], first['id'])
        self.assertEqual(watcher['automation']['targets'], ['123'])
        self.assertEqual(self.store.list_records('jobs'), [])
        self.assertEqual(self.store.list_records('candidates'), [])

    def test_check_refuses_absent_stopped_and_stale_workers(self):
        headers = self.mutation_headers()
        self.assertEqual(self.request(headers=headers)[0], 409)
        self.start_worker()
        self.ledger.automation_update(state='stopped')
        self.assertEqual(self.request(headers=headers)[0], 409)
        self.start_worker()
        with self.store.connection(True) as connection:
            connection.execute("UPDATE watch_automation SET heartbeat_at='2000-01-01T00:00:00.000000Z'")
        self.assertEqual(self.request(headers=headers)[0], 409)
        _, watcher = self.request('/api/watcher', method='GET')
        self.assertEqual(watcher['automation']['service_state'], 'stale')
        self.assertIsNone(watcher['automation']['check_request'])
