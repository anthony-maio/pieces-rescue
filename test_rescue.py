"""Black-box checks of the offline CLI on a tiny synthetic Couchbase store."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class RescueExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'db.sqlite3'
        from synthetic_store import create
        create(self.db)

    def invoke(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'rescue.py'), *map(str, args)], capture_output=True, text=True)

    def test_complete_export_has_verified_receipt(self):
        out = self.root / 'good'
        result = self.invoke('export', self.db, out)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((out / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(manifest['collections']['annotations']['decode_errors'], 0)

    def test_decode_error_is_not_success(self):
        db = sqlite3.connect(self.db)
        db.execute('insert into "kv_.annotations" values (?,?,?,?,?,?,?)', ('broken-id', 2, 0, None, b'bad', None, None))
        db.commit()
        db.close()
        out = self.root / 'bad'
        result = self.invoke('export', self.db, out)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        manifest = json.loads((out / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'incomplete')
        self.assertEqual(manifest['collections']['annotations']['exported'], 2)
        self.assertEqual(manifest['collections']['annotations']['decode_errors'], 1)
        with (out / 'raw' / 'annotations.jsonl').open() as stream:
            self.assertEqual(sum(1 for _ in stream), 2)


if __name__ == '__main__':
    unittest.main()
