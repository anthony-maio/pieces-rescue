"""HTTP smoke tests for the bundled offline atlas, without Pieces or MCP."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class AtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from synthetic_store import create
        from recovery import recover
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        source = create(root / 'Pieces/couchbase.cblite2/db.sqlite3')
        recover(source, root / 'recovered', source_closed=True, progress=lambda _: None)
        archive = root / 'recovered/export'
        cls.proc = subprocess.Popen([sys.executable, str(ROOT/'rescue.py'), 'serve', str(archive), '--port', '0'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = cls.proc.stdout.readline().strip()
        if not line.startswith('Local explorer: '):
            raise RuntimeError(line)
        cls.base = line.split('Local explorer: ')[1]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.proc.stdout.close()
        cls.proc.stderr.close()

    def fetch(self, route):
        with urllib.request.urlopen(self.base + route, timeout=90) as response:
            return response.status, response.headers, response.read()

    def test_bundled_app_and_receipt(self):
        status, _, html = self.fetch('/')
        self.assertEqual(status, 200)
        self.assertIn(b'/viewer.js', html)
        self.assertNotIn(b'https://', html)
        status, headers, js = self.fetch('/viewer.js')
        self.assertEqual(status, 200)
        self.assertIn(b'renderGraph', js)
        self.assertIn('script-src', headers['Content-Security-Policy'])
        status, headers, css = self.fetch('/viewer.css')
        self.assertEqual(status, 200)
        self.assertIn('text/css', headers['Content-Type'])
        self.assertTrue(css)
        _, _, payload = self.fetch('/api/overview')
        self.assertEqual(json.loads(payload)['status'], 'complete')
        _, _, payload = self.fetch('/api/timeline')
        self.assertTrue(json.loads(payload)['months'])

    def test_search_node_and_bounded_neighborhood(self):
        _, _, payload = self.fetch('/api/search?q=Pieces')
        records = json.loads(payload)['items']
        self.assertTrue(records)
        self.assertLessEqual(len(records), 24)
        identifier = records[0]['id']
        _, _, raw = self.fetch('/api/node?id=' + identifier)
        self.assertEqual(json.loads(raw)['id'], identifier)
        _, _, raw = self.fetch('/api/neighborhood?id=' + identifier)
        graph = json.loads(raw)
        self.assertEqual(graph['center']['id'], identifier)
        self.assertLessEqual(len(graph['relationships']), 120)
        _, _, raw = self.fetch('/api/search?month=2026-07')
        month_results = json.loads(raw)['items']
        self.assertTrue(month_results)
        self.assertTrue(all(r['created'].startswith('2026-07') for r in month_results))

    def test_invalid_id_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.fetch('/api/node?id=../../etc/passwd')
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_host_cross_site_and_framing_boundaries(self):
        for headers in ({'Host': 'malicious.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            request = urllib.request.Request(self.base + '/api/overview', headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
        _, headers, _ = self.fetch('/')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Cross-Origin-Resource-Policy'], 'same-origin')

    def test_punctuation_search_is_safe(self):
        _, _, payload = self.fetch('/api/search?q=' + urllib.parse.quote('Pieces-seedlings'))
        self.assertTrue(json.loads(payload)['items'])
        _, _, payload = self.fetch('/api/search?q=' + urllib.parse.quote('"'))
        self.assertEqual(json.loads(payload)['items'], [])

    def test_atlas_drill_down_and_recovered_reader(self):
        _, _, raw = self.fetch('/api/atlas')
        overview = json.loads(raw)
        self.assertGreater(overview['sessions'], 0)
        day = overview['days'][0]
        query = urllib.parse.urlencode({'from': overview['from'], 'to': overview['to'], 'day': day['day']})
        _, _, raw = self.fetch('/api/sessions?' + query)
        sessions = json.loads(raw)
        self.assertEqual(sessions['total'], day['sessions'])
        self.assertTrue(all(r['day'] == day['day'] for r in sessions['items']))
        _, _, raw = self.fetch('/api/node?id=' + sessions['items'][0]['id'])
        node = json.loads(raw)
        self.assertTrue(node['content_sources'])
        self.assertGreater(len(node['body']), len(node['title']))


if __name__ == '__main__':
    unittest.main()
