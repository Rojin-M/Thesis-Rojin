"""Course, grading and real HTTP checks for the shareable Academy."""
from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import threading
import unittest
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

APP_DIR=Path(__file__).resolve().parents[1]/'academy'

def load_curriculum():
    text=(APP_DIR/'curriculum.js').read_text()
    return json.loads(text.removeprefix('window.ACADEMY_CURRICULUM = ').rstrip().removesuffix(';'))

class CourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=load_curriculum()
        cls.modules={m['id']:m for m in cls.data['modules']}
        cls.questions=[q for m in cls.modules.values() for q in m['quiz']]+[q for u in cls.data['units'] for q in u['exam']]

    def test_ordered_prerequisites_and_unit_membership(self):
        self.assertEqual(len(self.modules),36)
        units={u['id'] for u in self.data['units']}
        self.assertEqual(len(units),9)
        prior=None
        for i,m in enumerate(self.modules.values(),1):
            self.assertEqual(m['order'],i)
            self.assertEqual(m['prerequisite'],prior)
            self.assertIn(m['unit'],units)
            prior=m['id']
        for unit in units:
            self.assertEqual(sum(m['unit']==unit for m in self.modules.values()),4)

    def test_no_open_response_or_self_grading_assessments(self):
        self.assertEqual(len(self.questions),252)
        self.assertEqual(len({q['id'] for q in self.questions}),252)
        self.assertTrue({'single','multi','number'}.issubset({q['type'] for q in self.questions}))
        for q in self.questions:
            self.assertIn(q['type'],{'single','multi','number'})
            self.assertIn(q['lesson'],self.modules)
            self.assertTrue(q['explanation'].strip())
            if q['type']=='number':
                self.assertIsInstance(q['answer'],(int,float))
                self.assertGreaterEqual(q['tolerance'],0)
                self.assertTrue(q['unit'])
            else:
                self.assertEqual(len(q['options']),4)
                self.assertEqual(len(set(q['options'])),4)
                answers=q['answer'] if q['type']=='multi' else [q['answer']]
                self.assertEqual(len(answers),len(set(answers)))
                self.assertTrue(all(0<=a<len(q['options']) for a in answers))
                self.assertLess(len(answers),4)

    def test_each_lesson_teaches_then_applies_then_assesses(self):
        for m in self.modules.values():
            with self.subTest(lesson=m['id']):
                self.assertEqual(len(m['objectives']),3)
                self.assertGreaterEqual(len(m['sections']),3)
                words=' '.join(p for s in m['sections'] for p in s['paragraphs']).split()
                self.assertGreaterEqual(len(words),190)
                self.assertGreaterEqual(len(m['example']['steps']),3)
                self.assertGreater(len(m['example']['answer']),40)
                self.assertEqual(len(m['quiz']),6)
                self.assertGreater(len(m['project']),70)

    def test_explicit_ml_mechanics_and_current_papers(self):
        for lid in ['neurons','gradients','training','seeds','cnn','alternatives','attention','representation','transfer','dann','uncertainty','frontier']:
            self.assertIn(lid,self.modules)
        text=json.dumps(self.data,ensure_ascii=False)
        for term in ['backpropagation','pseudo-random','gradient reversal','120','82','0.6934','EXOVEIL','Astro-Hunters','2026-09-23','not a planet probability']:
            self.assertIn(term.lower(),text.lower())
        self.assertIn('0.01458',text)
        self.assertNotIn('does not yet perform a blind search',text)

    def test_sources_and_glossary_have_valid_lesson_links(self):
        sources={s['id']:s for s in self.data['sources']}
        self.assertEqual(len(sources),len(self.data['sources']))
        for s in sources.values():
            self.assertTrue(s['url'].startswith('https://'))
            self.assertTrue(s['status'])
        for m in self.modules.values():
            for sid in m['sources']: self.assertIn(sid,sources)
        terms=set()
        for g in self.data['glossary']:
            self.assertNotIn(g['term'],terms)
            terms.add(g['term'])
            self.assertIn(g['lesson'],self.modules)
        self.assertGreater(len(terms),40)

    def test_optional_research_has_traceable_sources_and_bounded_claims(self):
        from datetime import date
        r=self.data['researchExtension'];sources={s['id']:s for s in self.data['sources']}
        cards={c['id']:c for c in r['cards']}
        self.assertEqual(len(cards),len(r['cards']))
        self.assertTrue(set(cards).isdisjoint(self.modules))
        used=set()
        for card in cards.values():
            self.assertRegex(card['id'],r'^[a-z][a-z0-9-]+$')
            for key in ['input','mechanism','evidence','limit','connection','status']:
                self.assertTrue(card[key].strip(),(card['id'],key))
            for lid in card['lessons']: self.assertIn(lid,self.modules)
            used.update(card['sources'])
            for related in card.get('related',[]): used.update(related['sources'])
        for workflow in r['workflows']:
            used.update(workflow['sources'])
            self.assertTrue(workflow['boundary'])
        self.assertEqual(len(used),16)
        for sid in used:
            s=sources[sid]
            self.assertEqual(date.fromisoformat(s['accessed']),date(2026,9,28))
            self.assertEqual(s['checked'],s['accessed'])
            self.assertTrue(s['evidenceType'])
            self.assertTrue(any(s.get(k) for k in ['submitted','published','updated']))
            for key in ['url','fullText','publicationUrl']:
                if key in s:self.assertTrue(s[key].startswith('https://'))
        # Guard against conflating news/publication/event dates or evidence levels.
        self.assertEqual(sources['btsbot-nearby']['eventDate'],'2024-05-28')
        self.assertEqual(sources['btsbot-nearby']['submitted'],'2025-01-30')
        self.assertEqual(sources['exominer']['submitted'],'2025-02-13')
        self.assertEqual(sources['exominer-nasa']['published'],'2026-01-22')
        # Journal records can establish publication even when arXiv comments lag.
        for sid in ['btsbot','btsbot-nearby','raven26','exominer']:
            self.assertIn('Published',sources[sid]['status'])
            self.assertTrue(sources[sid]['publicationUrl'])
        self.assertEqual(sources['btsbot-nearby']['published'],'2025-05-29')
        self.assertEqual(sources['raven26']['published'],'2026-03-25')
        self.assertEqual(sources['desi-vae']['published'],'2026-01-07')
        self.assertEqual(sources['desi-vae']['issueDate'],'2026-04')
        self.assertIn('not the measured rate',cards['brokers']['evidence'])
        self.assertIn('unvalidated candidates',cards['raven']['evidence'])
        self.assertIn('31 newly detected',cards['raven']['evidence'])
        self.assertIn('not survey-wide completeness',cards['reading-claims']['limit'])
        self.assertIn('proposed framework',cards['next-decisions']['status'])
        for sid in ['exoveil','hunters']:self.assertIn('Preprint',sources[sid]['status'])
        self.assertIn('white paper',sources['desc-ai']['status'])
        self.assertEqual(sources['exofop']['checked'],'2026-09-23')
        self.assertIn('unsuccessful',sources['exofop']['accessNote'])

    def test_authored_source_reproduces_the_shipped_curriculum(self):
        result=runpy.run_path(str(APP_DIR/'source/build_course.py'))['D']
        prior=None
        for m in result['modules']:
            m['prerequisite']=prior
            prior=m['id']
        self.assertEqual(result,self.data)

    def test_runnable_python_examples(self):
        for lid in ['arrays','gradients','seeds','cnn','attention','dann']:
            with self.subTest(lesson=lid):
                result=subprocess.run([sys.executable,'-c',self.modules[lid]['code']],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_local_runtime_and_preserved_legacy_storage(self):
        html=(APP_DIR/'index.html').read_text()
        self.assertIn('href="#main-content"',html)
        self.assertEqual(html.count('<main '),1)
        order=['curriculum.js','grading.js','labs.js','app.js']
        positions=[html.index('src="'+s+'"') for s in order]
        self.assertEqual(positions,sorted(positions))
        js='\n'.join((APP_DIR/s).read_text() for s in order[1:])
        for forbidden in ['fetch(','XMLHttpRequest','new WebSocket','eval(','localStorage.clear','localStorage.removeItem(OLD_KEY']:
            self.assertNotIn(forbidden,js)
        self.assertIn('exoplanet-academy:v1',js)
        self.assertIn('exoplanet-academy:v2',js)
        self.assertNotIn('<textarea',js)

    def test_content_refresh_preserves_frozen_assessment_contract(self):
        import hashlib
        contract=json.loads((Path(__file__).parent/'fixtures/academy/assessment_v2.json').read_text())
        self.assertEqual(self.data['version'],contract['version'])
        self.assertEqual(self.data['revision'],contract['assessment_revision'])
        self.assertEqual([m['id'] for m in self.data['modules']],contract['ordered_lesson_ids'])
        self.assertEqual([u['id'] for u in self.data['units']],contract['ordered_unit_ids'])
        self.assertEqual([q['id'] for q in self.questions],contract['ordered_question_ids'])
        fields=contract['grading_contract_fields']
        canonical=[{k:q[k] for k in fields if k in q} for q in self.questions]
        digest=hashlib.sha256(json.dumps(canonical,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(digest,contract['grading_contract_sha256'])
        self.assertRegex(self.data['contentRevision'],r'^\d{4}-\d{2}-\d{2}\.\d+$')
        self.assertNotEqual(self.data['contentRevision'],self.data['revision'])
        self.assertIn('23 September 2026',self.modules['missions']['quiz'][5]['prompt'])

    def test_public_evidence_accounting_and_caveats(self):
        p=self.data['project'];f=p['fresh_classifier'];r=p['fresh_recovery'];h=p['physical_benchmark']
        self.assertEqual(f['registered_candidates'],295)
        self.assertEqual(f['accepted_candidates']+f['acquisition']['rejection_reasons']['no_public_120s_product'],295)
        self.assertEqual(f['acquisition']['available_passed_unchanged_preparation'],14)
        self.assertEqual((f['positive'],f['negative']),(3,11))
        for k,m in f['methods'].items():
            counts=m['at_0_5']
            self.assertEqual(counts['tp']+counts['fn'],3)
            self.assertEqual(counts['tn']+counts['fp'],11)
            self.assertEqual(m['correct_at_0_5'],counts['tp']+counts['tn'])
            self.assertEqual(m['n'],14)
            self.assertTrue(m['calibration'])
        self.assertIn('Frozen temperature',f['methods']['crossfit_supermodel']['calibration'])
        self.assertIn('Raw logits',f['methods']['v4_static']['calibration'])
        self.assertEqual((h['registered_hosts'],h['observable_hosts'],h['injected_events']),(90,85,330))
        self.assertEqual((r['registered_hosts'],r['observable_hosts'],r['injected_events']),(99,96,326))
        for cohort in [h,r]:
            self.assertEqual(cohort['calibration_hosts'],78)
            for method in cohort['methods'].values():
                self.assertAlmostEqual(method['inverted_alerts']/method['control_exposure_days_recomputed']*27,method['inverted_alerts_per_27_days'],places=12)
        old,new=r['methods']['v3_original'],r['methods']['v3_calibrated']
        self.assertEqual(new['incremental_hosts'],old['incremental_hosts'])
        self.assertEqual(new['incremental_events']-old['incremental_events'],-5)
        self.assertAlmostEqual(r['derived_comparison']['inverted_control_relative_reduction'],1-new['inverted_alerts']/old['inverted_alerts'])
        for m in r['by_depth']['0.0005'].values():self.assertEqual((m['incremental_hosts'],m['registered_hosts']),(0,25))
        self.assertEqual(r['by_mode']['single']['tls_exact']['incremental_hosts'],3)
        self.assertFalse(h['claims']['watcher_deployed']);self.assertFalse(r['claims']['deployed']);self.assertFalse(f['claims']['deployed'])
        self.assertEqual(p['watcher']['selected_target_count'],18)
        self.assertFalse(p['watcher']['archive_wide_complete'])
        self.assertEqual(p['deployment']['calibration'],'not_calibrated_for_blind_search')
        self.assertTrue(p['deployment']['latest_completed_score_at'].startswith('2026-09-26'))

    def test_public_tables_match_original_machine_readable_reports(self):
        # Optional local evidence verification in a clone without ignored run artifacts;
        # the public accounting and grading-contract tests above always run.
        p=self.data['project'];root=APP_DIR.parent
        required=[p[k]['source'] for k in ['historical_dann','reused_classifier','fresh_classifier','physical_benchmark','fresh_recovery']]
        if not all((root/path).is_file() for path in required):
            self.skipTest('Full local research summaries are not present in this checkout')
        load=lambda key:json.loads((root/p[key]['source']).read_text())
        historical=load('historical_dann')['by_arm']
        for k,m in p['historical_dann']['methods'].items():self.assertEqual(m,historical[k]['raw_average_precision'])
        reused=load('reused_classifier')['audit']
        for k,m in p['reused_classifier']['methods'].items():
            for field,value in m.items():self.assertEqual(value,reused[k][field])
        fresh=load('fresh_classifier')
        for field in ['registered_candidates','accepted_candidates','positive','negative']:self.assertEqual(p['fresh_classifier'][field],fresh[field])
        for k,m in p['fresh_classifier']['methods'].items():
            for field,value in m.items():
                if field not in ['calibration','correct_at_0_5']:self.assertEqual(value,fresh['metrics'][k][field])
        for key in ['physical_benchmark','fresh_recovery']:
            report=load(key)
            self.assertEqual(p[key]['registered_hosts'],report['registered_hosts'])
            for k,m in p[key]['methods'].items():
                for field,value in m.items():
                    if field!='control_exposure_days_recomputed':self.assertEqual(value,report['methods'][k][field])
            for m in report['methods'].values():
                self.assertEqual(p[key]['observable_hosts'],m['hosts_with_observable_injection'])
                self.assertEqual(p[key]['injected_events'],m['injected_events'])


class JavaScriptGradingTests(unittest.TestCase):
    def test_actual_node_grader_and_math_labs(self):
        node=os.environ.get('NODE') or shutil.which('node')
        if not node: self.skipTest('Node is needed to execute the real grader; set NODE to its path.')
        result=subprocess.run([node,'--test',str(Path(__file__).with_name('test_academy_grading.cjs')),str(Path(__file__).with_name('test_academy_progress.cjs'))],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


class ServerBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("academy_server", APP_DIR / "serve.py")
        assert spec and spec.loader
        cls.server_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.server_module)
        handler = partial(cls.server_module.AcademyHandler, directory=str(APP_DIR))
        try:
            cls.server = cls.server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        except PermissionError as error:
            raise unittest.SkipTest("Local sockets are disabled in this sandbox") from error
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    @classmethod
    def request(cls, path: str, method: str = "GET"):
        request = Request(cls.base_url + path, method=method)
        with contextlib.redirect_stderr(io.StringIO()):
            return cls.opener.open(request, timeout=3)

    def test_assets_return_expected_types(self) -> None:
        expected = {
            "/": "text/html",
            "/styles.css": "text/css",
            "/curriculum.js": "javascript",
            "/app.js": "javascript",
            "/grading.js": "javascript",
            "/labs.js": "javascript",
        }
        for path, mime in expected.items():
            with self.subTest(path=path):
                with self.request(path) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(mime, response.headers["Content-Type"])

    def test_head_has_no_body(self) -> None:
        with self.request("/", method="HEAD") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"")

    def test_missing_and_parent_traversal_are_blocked(self) -> None:
        for path in ("/not-a-real-file", "/%2e%2e/AGENTS.md"):
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as context:
                    self.request(path)
                self.assertEqual(context.exception.code, 404)

    def test_security_headers_on_success_and_error(self) -> None:
        responses = []
        responses.append(self.request("/"))
        try:
            self.request("/missing")
        except HTTPError as error:
            responses.append(error)
        for response in responses:
            with self.subTest(status=getattr(response, "status", response.code)):
                headers = response.headers
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")
                self.assertEqual(headers["X-Frame-Options"], "DENY")
                self.assertIn("camera=()", headers["Permissions-Policy"])
                csp = headers["Content-Security-Policy"]
                self.assertIn("default-src 'self'", csp)
                self.assertIn("connect-src 'none'", csp)
                self.assertIn("object-src 'none'", csp)
                self.assertIn("frame-ancestors 'none'", csp)
            response.close()

    def test_default_binding_is_localhost(self) -> None:
        with mock.patch.object(sys, "argv", ["serve.py"]):
            args = self.server_module.parse_args()
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)


if __name__ == "__main__":
    unittest.main(verbosity=2)
