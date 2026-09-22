"""Replay public API shapes offline; assert accounting, failures and restart safety."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import signal
import unittest
from unittest.mock import patch

from scripts.research import mast
from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import ConflictError, ValidationError, load_protocol, utc_now
from scripts.research.store import Store, _one
from scripts.research.watcher import load_config, poll_once, create_pilot, acquire, dispatch
from scripts.research.watcher_store import WatchStore, exclusive_lock, status
from tests.test_research_detection import write_fits

FIXTURES = Path(__file__).parent / 'fixtures/mast'


class ReplayClient:
    def __init__(self, path=None, scenario='initial', size=None):
        self.path=path; self.scenario=scenario; self.size=size
        self.calls=[]; self.downloads=0; self.fail=False
    def query(self, request):
        self.calls.append(request)
        if self.fail:
            raise OSError('fixture simulated MAST outage')
        kind='observations' if request['service']=='Mast.Caom.Filtered' else 'products'
        scenario=self.scenario
        if scenario=='reprocessed' and kind=='observations': scenario='initial'
        value=json.loads((FIXTURES/(kind+'_'+scenario+'.json')).read_text())
        if kind=='products' and self.size:
            for row in value['data']: row['size']=self.size
        return json.dumps(value).encode()
    def download(self, product, path, pilot_id):
        self.downloads+=1
        if self.fail: raise OSError('fixture simulated download outage')
        raw=self.path.read_bytes(); Path(path).write_bytes(raw)
        return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'source_uri':product['source_uri'],
                'retrieved_at':utc_now(),'fixture_only':True}


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.source=self.root/'source.fits'; write_fits(self.source)
        self.store=Store(self.root/'research.sqlite3').initialize()
        self.ledger=WatchStore(self.store)
        self.protocol=self.store.register_protocol(load_protocol())
        self.artifacts=ArtifactStore(self.root/'artifacts',self.store)
        self.config={**load_config(),'targets':['123']}
        self.client=ReplayClient(self.source,size=self.source.stat().st_size)
    def poll(self):
        result=poll_once(self.store,self.config,client=self.client,force=True)
        self.assertEqual(result['status'],'succeeded',result)
        return result
    def pilot(self, ids=None, max_bytes=10000000, max_seconds=60):
        ids=ids or self.poll()['product_ids']
        return create_pilot(self.store,self.protocol['id'],pilot_id='fixture-pilot',product_ids=ids,
                           cohort='known_object_control',max_bytes=max_bytes,max_seconds=max_seconds)
    def product(self,pid):
        with self.store.connection() as db:
            return _one(db,'SELECT * FROM products WHERE id=?',(pid,))
    def test_release_replay_duplicates_and_reprocessing_are_immutable(self):
        first=self.poll(); pid=first['product_ids'][0]; product=self.product(pid)
        self.client.scenario='duplicate'
        duplicate=self.poll(); self.assertEqual(duplicate['product_ids'],[pid]); self.assertEqual(duplicate['new_product_ids'],[])
        self.assertEqual(product,self.product(pid))
        self.client.scenario='reprocessed'; revised=self.poll()
        self.assertNotEqual(revised['product_ids'],[pid]); self.assertEqual(self.store.summary()['release_count'],1)
        self.client.scenario='new_release'; new=self.poll()
        self.assertNotEqual(new['product_ids'],[pid]); self.assertEqual(self.store.summary()['release_count'],2)
        self.assertEqual(self.store.summary()['product_count'],3)
        self.assertEqual(self.store.summary()['jobs_by_status'],{})
        self.assertEqual(len(status(self.store)['polls']),4)
    def test_metadata_only_never_downloads_or_creates_pilots(self):
        self.poll();self.poll()
        self.assertEqual(self.client.downloads,0);self.assertEqual(status(self.store)['queue'],[])
        self.assertEqual(status(self.store)['pilots'],[])
        result=poll_once(self.store,self.config,client=self.client)
        self.assertEqual(result['status'],'not_due');self.assertEqual(len(self.client.calls),4)
    def test_outage_backoff_three_failure_circuit_and_explicit_reset(self):
        self.client.fail=True
        for attempt in range(1,4):
            r=poll_once(self.store,self.config,client=self.client,force=True)
            self.assertEqual(r['status'],'failed')
            c=status(self.store)['configs'][0];self.assertEqual(c['failures'],attempt)
            self.assertGreater(c['next_poll_at'],utc_now())
        with self.assertRaises(ConflictError): poll_once(self.store,self.config,client=self.client,force=True)
        self.assertEqual(len(self.client.calls),3)
        self.assertEqual(status(self.store)['configs'][0]['health'],'circuit_open')
        self.ledger.reset(c['id']);self.client.fail=False;self.poll()
        self.assertEqual(status(self.store)['configs'][0]['failures'],0)
    def test_pagination_remains_visibly_incomplete_and_does_not_scan(self):
        orig=self.client.query
        def truncated(request):
            page=json.loads(orig(request));page['paging']['pagesFiltered']=40
            return json.dumps(page).encode()
        self.client.query=truncated
        result=self.poll();self.assertFalse(result['metadata_pages_complete']);self.assertEqual(len(self.client.calls),2)
    def test_future_private_wrong_target_and_fast_products_are_not_selected(self):
        rows=json.loads((FIXTURES/'observations_initial.json').read_text())['data']
        variants=[{**rows[0],'t_obs_release':90000},{**rows[0],'dataRights':'EXCLUSIVE_ACCESS'},
            {**rows[0],'target_name':'999'},{**rows[0],'dataURL':'https://127.0.0.1/secret'},
            {**rows[0],'dataURL':rows[0]['dataURL'].replace('-s_lc','-a_fast-lc')}]
        selected,details=mast.select_observations(variants,['123'],2)
        self.assertEqual(selected,[]);self.assertEqual(details['excluded_observations'],5)
        self.assertEqual(mast.public_release_time(51544),'2000-01-01T00:00:00.000000Z')
        for bad in (None,float('nan'),90000):
            with self.assertRaises(ValidationError):mast.public_release_time(bad)
        for bad in ('mast:TESS/product/../../x','https://evil/tess.fits'):
            with self.assertRaises(ValidationError):mast.filename(bad)
    def test_reservations_survive_restart_prior_import_is_idempotent(self):
        self.ledger.account('previous-catalog',5392591,'prior stage catalog response bytes')
        self.ledger.account('previous-catalog',5392591,'prior stage catalog response bytes')
        self.ledger.reserve(1000,'metadata')
        restarted=Store(self.store.path).initialize();budget=status(restarted)['budget']
        self.assertEqual(budget['charged_bytes'],5393591);self.assertEqual(budget['unsettled_reservations'],1)
        with self.assertRaises(ConflictError):self.ledger.account('previous-catalog',2,'changed')
        with self.assertRaises(ValidationError):self.ledger.reserve(2*1024**3,'science_product')
        with self.assertRaises(ValidationError):self.ledger.reserve(-1,'metadata')
    def test_pilot_selection_frozen_no_queue_growth_on_future_release(self):
        pilot=self.pilot();self.client.scenario='new_release';new=self.poll()
        self.assertEqual(len(status(self.store)['queue']),1)
        self.assertEqual(self.pilot(pilot['spec']['product_ids'])['spec'],pilot['spec'])
        with self.assertRaises(ConflictError):self.pilot(new['product_ids'])
        with self.assertRaises(ValidationError):create_pilot(self.store,self.protocol['id'],pilot_id='bad',product_ids=new['product_ids'],cohort='prospective_search',max_bytes=100000,max_seconds=60)
        with self.assertRaises(ValidationError):create_pilot(self.store,self.protocol['id'],pilot_id='small',product_ids=new['product_ids'],cohort='archival_pilot',max_bytes=1,max_seconds=60)
    def test_completed_download_receipts_reuse_after_database_restart(self):
        pilot=self.pilot();pid=pilot['spec']['product_ids'][0]
        receipt=acquire(self.store,self.product(pid),pilot['id'],self.client)
        self.assertEqual(self.client.downloads,1)
        self.store=Store(self.store.path).initialize()
        repeated=acquire(self.store,self.product(pid),pilot['id'],self.client)
        self.assertEqual(receipt,repeated);self.assertEqual(self.client.downloads,1)
        path=Path(receipt['path']);raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
        with self.assertRaisesRegex(ValidationError,'corrupt'):acquire(self.store,self.product(pid),pilot['id'],self.client)
        self.assertEqual(self.client.downloads,1)
    def test_crash_after_file_publication_recovers_receipt_without_redownload(self):
        pilot=self.pilot();pid=pilot['spec']['product_ids'][0]
        real=WatchStore.queue
        def fail(store,pid,**values):
            if 'receipt' in values:raise OSError('crash before database receipt')
            return real(store,pid,**values)
        with patch.object(WatchStore,'queue',fail):
            with self.assertRaises(OSError):acquire(self.store,self.product(pid),pilot['id'],self.client)
        acquired=acquire(self.store,self.product(pid),pilot['id'],self.client)
        self.assertEqual(self.client.downloads,1);self.assertTrue(Path(acquired['path']).is_file())
    def test_dispatch_failure_backoff_attempt_cap_and_no_redownload_after_processing_failure(self):
        pilot=self.pilot();self.client.fail=True
        first=dispatch(self.store,self.artifacts,pilot['id'],client=self.client,processor=lambda *a:None)
        self.assertEqual(first['status'],'failed');self.assertEqual(self.client.downloads,1)
        dispatch(self.store,self.artifacts,pilot['id'],client=self.client,processor=lambda *a:None)
        self.assertEqual(self.client.downloads,1)
        pid=pilot['spec']['product_ids'][0];self.client.fail=False
        self.ledger.queue(pid,next_attempt_at=None)
        def broken(*args):raise OSError('downstream failure')
        dispatch(self.store,self.artifacts,pilot['id'],client=self.client,processor=broken)
        self.assertEqual(self.client.downloads,2)
        self.ledger.queue(pid,next_attempt_at=None)
        dispatch(self.store,self.artifacts,pilot['id'],client=self.client,processor=broken)
        self.assertEqual(self.client.downloads,2)
        self.ledger.queue(pid,next_attempt_at=None)
        dispatch(self.store,self.artifacts,pilot['id'],client=self.client,processor=broken)
        self.assertEqual(status(self.store)['queue'][0]['attempts'],3)
    def test_dispatch_replay_and_finite_runtime(self):
        pilot=self.pilot(max_seconds=2)
        def stall(*a):time.sleep(5)
        start=time.monotonic();r=dispatch(self.store,self.artifacts,pilot['id'],client=self.client,processor=stall)
        self.assertLess(time.monotonic()-start,3);self.assertIn(r['status'],('failed','runtime_exhausted'))
        with self.assertRaisesRegex(ValidationError,'runtime exhausted'):dispatch(self.store,self.artifacts,pilot['id'],client=self.client,processor=stall)
    def test_hard_crash_runtime_reservation_is_conservatively_charged(self):
        pilot=self.pilot(max_seconds=10)
        self.ledger.dispatch_start(pilot['id'])
        with self.assertRaisesRegex(ValidationError,'runtime exhausted'):WatchStore(Store(self.store.path).initialize()).dispatch_start(pilot['id'])
    def test_hard_crash_preserves_larger_remaining_allowance_and_active_lease_waits(self):
        pilot=self.pilot(max_seconds=900)
        key,seconds=self.ledger.dispatch_start(pilot['id'])
        self.assertEqual(seconds,600)
        key2,remaining=self.ledger.dispatch_start(pilot['id'])
        self.assertEqual(remaining,300)
        self.ledger.dispatch_finish(key2,0,'paused')
        pid=pilot['spec']['product_ids'][0]
        product=self.product(pid)
        job=self.store.create_job(job_key='watch-bls-v1:'+pid,cohort='known_object_control',
            protocol_id=self.protocol['id'],code_provenance_id=product['provenance_id'])
        claim=self.store.claim_stage(job['id'],'metadata',worker='interrupted-fixture',lease_seconds=900)
        r=dispatch(self.store,self.artifacts,pilot['id'],client=self.client,processor=lambda *a:None)
        q=status(self.store)['queue'][0]
        self.assertEqual(q['state'],'waiting_for_lease');self.assertEqual(q['attempts'],0)
        self.assertEqual(q['next_attempt_at'],claim['lease_until']);self.assertEqual(self.client.downloads,0)
    def test_nested_deadline_does_not_interrupt_failure_cleanup_twice(self):
        with self.assertRaises(TimeoutError):
            with mast.wall_deadline(.08):
                with mast.wall_deadline(1):
                    time.sleep(.2)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)
        time.sleep(.02)
    def test_lock_prevents_duplicate_workers_and_preserves_active_stages(self):
        with exclusive_lock(self.ledger.lock_path):
            with self.assertRaises(ConflictError):self.poll()
        self.poll()
    def test_interrupted_polls_count_toward_circuit_and_preserve_history(self):
        record=self.ledger.config(self.config)
        for number in range(3):
            poll=self.ledger.begin_poll(record['id'],21600,force=True)
            self.assertIsInstance(poll,str)
        with self.assertRaises(ConflictError):poll_once(self.store,self.config,client=self.client,force=True)
        snapshot=status(self.store)
        self.assertEqual(snapshot['configs'][0]['failures'],3)
        self.assertTrue(all(p['status']=='interrupted' for p in snapshot['polls']))
        self.assertEqual(self.client.calls,[])
    def test_stale_heartbeat_and_pilot_product_ownership_are_visible(self):
        record=self.ledger.config(self.config)
        self.ledger.service(record['id'],'running')
        with self.store.connection(True) as db:
            db.execute("UPDATE watch_configs SET heartbeat_at='2000-01-01T00:00:00.000000Z'")
        self.assertEqual(status(self.store)['configs'][0]['health'],'stale')
        pilot=self.pilot()
        with self.assertRaisesRegex(ConflictError,'already belongs'):
            create_pilot(self.store,self.protocol['id'],pilot_id='second-fixture',product_ids=pilot['spec']['product_ids'],
                cohort='known_object_control',max_bytes=1000000,max_seconds=30)
    def test_missing_paging_is_incomplete_and_ambiguous_product_fails(self):
        rows,complete=mast.decode_page(b'{"status":"COMPLETE","data":[]}')
        self.assertFalse(complete)
        observation=json.loads((FIXTURES/'observations_initial.json').read_text())['data'][0]
        row=json.loads((FIXTURES/'products_initial.json').read_text())['data'][0]
        with self.assertRaisesRegex(ValidationError,'unambiguous'):
            mast.select_product([row,{**row,'prvversion':'different'}],observation)
    def test_queue_cap_does_not_reset_for_additional_pilots(self):
        first=self.poll()['product_ids'][0]
        product=self.product(first)
        all_ids=[]
        for number in range(21):
            row=self.store.register_product(release_id=product['release_id'],product_key='cap-fixture-'+str(number),
                target_id='123',source_uri=product['source_uri'],provenance_id=product['provenance_id'],metadata=product['metadata'])
            all_ids.append(row['id'])
            with self.store.connection(True) as db:
                poll=db.execute('SELECT id FROM watch_polls LIMIT 1').fetchone()[0]
                db.execute('INSERT INTO watch_seen VALUES(?,?)',(poll,row['id']))
        self.pilot(all_ids[:20])
        with self.assertRaisesRegex(ValidationError,'Cumulative initial selection'):
            create_pilot(self.store,self.protocol['id'],pilot_id='overflow',product_ids=all_ids[20:],
                cohort='known_object_control',max_bytes=1000000,max_seconds=30)
    def test_byte_budget_per_pilot_counts_retries(self):
        pilot=self.pilot(max_bytes=self.source.stat().st_size)
        spend=self.ledger.reserve(self.source.stat().st_size,'science_product',pilot['id'])
        with self.assertRaises(ValidationError):self.ledger.reserve(1,'science_product',pilot['id'])
        self.ledger.settle(spend,self.source.stat().st_size,{'retry_failure':True})
        with self.assertRaises(ValidationError):self.ledger.reserve(1,'science_product',pilot['id'])
    def test_config_requires_safe_metadata_only_bounds(self):
        for field,value in [('metadata_only',False),('max_products_per_poll',20),('targets',['123','123']),('poll_seconds',1),('targets',['../data'])]:
            p=self.root/'config.json';p.write_text(json.dumps({**self.config,field:value}))
            with self.assertRaises(ValidationError):load_config(p)


class RawBytes(io.BytesIO):
    def read(self, size=-1, decode_content=False):
        return super().read(size)


class FakeResponse:
    def __init__(self,raw,headers=None,status=200):
        self.raw=RawBytes(raw);self.headers=headers or {'Content-Length':str(len(raw))};self.status_code=status
    def __enter__(self):return self
    def __exit__(self,*args):pass


class TransferTests(unittest.TestCase):
    setUp = WatcherTests.setUp
    def test_exact_bytes_receipt_and_oversize_failure_are_charged(self):
        class Session:
            headers={}
            response=FakeResponse(b'abcdef')
            def request(self,*args,**kwargs):return self.response
        session=Session();client=mast.MastClient(self.ledger,session)
        raw,receipt=client._transfer('POST',mast.INVOKE,10)
        self.assertEqual(raw,b'abcdef');self.assertEqual(receipt['bytes'],6)
        self.assertEqual(status(self.store)['budget']['charged_bytes'],6)
        session.response=FakeResponse(b'abcdef',{'Content-Length':'100'})
        with self.assertRaises(ValidationError):client._transfer('POST',mast.INVOKE,10)
        self.assertEqual(status(self.store)['budget']['charged_bytes'],16)
        session.response=FakeResponse(b'ab',{'Content-Length':'6'})
        with self.assertRaises(OSError):client._transfer('POST',mast.INVOKE,10)
        self.assertEqual(status(self.store)['budget']['charged_bytes'],26)
    def test_http_redirect_and_compressed_bytes_are_rejected(self):
        class Session:
            headers={}
            response=FakeResponse(b'',status=302)
            def request(self,*args,**kwargs):
                assert kwargs['allow_redirects'] is False
                return self.response
        session=Session();client=mast.MastClient(self.ledger,session)
        with self.assertRaises(OSError):client._transfer('POST',mast.INVOKE,10)
        session.response=FakeResponse(b'a',{'Content-Encoding':'gzip'})
        with self.assertRaises(ValidationError):client._transfer('POST',mast.INVOKE,10)
