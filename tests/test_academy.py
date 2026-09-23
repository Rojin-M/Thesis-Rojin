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

class JavaScriptGradingTests(unittest.TestCase):
    def test_actual_node_grader_and_math_labs(self):
        node=os.environ.get('NODE') or shutil.which('node')
        if not node: self.skipTest('Node is needed to execute the real grader; set NODE to its path.')
        result=subprocess.run([node,'--test',str(Path(__file__).with_name('test_academy_grading.cjs'))],capture_output=True,text=True,timeout=30)
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
