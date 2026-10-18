"""Portable release checks for preservation, failures and retries."""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import purefleece
import recovery
import rescue
from recovery_io import Cancelled, child, exclusive, sha256
from atlas import ReadConnection
from synthetic_store import create, encode, SHARED, SUMMARY


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pieces-beta-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = create(self.root / 'source with spaces/Pieces/couchbase.cblite2/db.sqlite3', auxiliary=True)
        self.output = self.root / 'saved'
        self.args = SimpleNamespace(source=self.source, output=self.output, limit=0, include_secrets=False,
                                    require_wal=True, allow_wal_omission=False, resume=False, fleece_library=None)

    def export(self):
        return rescue.export(self.args, progress=lambda _: None)

    def recover(self, **kwargs):
        return recovery.recover(self.source, self.output, True, progress=lambda _: None, **kwargs)

    def test_fleece_known_values_and_shared_keys(self):
        self.assertEqual(purefleece.decode(b'\x00\x2a'), 42)
        self.assertEqual(purefleece.decode(b'\x38\x00'), True)
        self.assertEqual(purefleece.decode(b'\x43cat\x80\x02'), 'cat')
        obj = {'title': 'A test', 'annotations': {'indices': {SUMMARY: 0}}, 'text': '\u96ea and caf\u00e9'}
        self.assertEqual(purefleece.decode(encode(obj, SHARED), dict(enumerate(SHARED))), obj)
        with self.assertRaises(ValueError):
            purefleece.decode(encode({'title': 'bad'}, SHARED), {})
        with self.assertRaises(ValueError):
            purefleece.decode(b'bad')

    def test_cancelled_collection_is_uncommitted_and_retry_is_complete(self):
        original = rescue.Fleece.decode
        calls = 0
        def interrupt(decoder, body):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt()
            return original(decoder, body)
        # Two records in the first collection reproduces the original interruption.
        with sqlite3.connect(self.source, factory=ReadConnection) as db:
            db.execute('insert into "kv_.annotations" values(?,?,?,?,?,?,?)', ('second', 2, 0, None, encode({'text': 'second'}, SHARED), None, None))
        before = sha256(self.source)
        with patch.object(rescue.Fleece, 'decode', interrupt), self.assertRaises(KeyboardInterrupt):
            self.export()
        receipt = json.loads((self.output / 'manifest.json').read_text())
        self.assertEqual(receipt['status'], 'cancelled')
        self.assertEqual(receipt['collections'], {})
        with sqlite3.connect(self.output / 'knowledge.sqlite', factory=ReadConnection) as db:
            self.assertEqual(db.execute('select count(*) from nodes').fetchone()[0], 0)
        self.assertFalse((self.output / 'raw/annotations.jsonl').exists())
        self.args.resume = True
        receipt = self.export()
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(receipt['collections']['annotations']['exported'], 2)
        self.assertEqual(sha256(self.source), before)

    def test_hard_process_exit_after_index_commit_replays_collection(self):
        script = """
import os, sys
from pathlib import Path
from types import SimpleNamespace
import rescue
original = rescue.os.replace
def die(src,dst):
    if str(dst).endswith('annotations.jsonl'):
        os._exit(79)
    original(src,dst)
rescue.os.replace = die
rescue.export(SimpleNamespace(source=sys.argv[1],output=sys.argv[2],limit=0,include_secrets=False,require_wal=True,resume=False,fleece_library=None))
"""
        run = subprocess.run([sys.executable, '-c', script, str(self.source), str(self.output)], capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 79, run.stderr)
        self.args.resume = True
        self.assertEqual(self.export()['status'], 'complete')
        with sqlite3.connect(self.output / 'knowledge.sqlite', factory=ReadConnection) as db:
            self.assertEqual(db.execute("select count(*) from search where search match 'seedlings'").fetchone()[0], 2)

    def test_resume_refuses_changed_source_and_changed_completed_file(self):
        self.export()
        self.args.resume = True
        raw = self.output / 'raw/annotations.jsonl'
        raw.write_text(raw.read_text() + '{}\n')
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            self.export()
        with sqlite3.connect(self.source, factory=ReadConnection) as db:
            db.execute('delete from "kv_.annotations"')
        with self.assertRaisesRegex(ValueError, 'Source or export options changed'):
            self.export()

    def test_wal_snapshot_includes_committed_records(self):
        db = sqlite3.connect(self.source, factory=ReadConnection)
        try:
            db.execute('pragma journal_mode=wal')
            db.execute('pragma wal_autocheckpoint=0')
            db.execute('insert into "kv_.annotations" values(?,?,?,?,?,?,?)', ('wal-record', 2, 0, None, encode({'text': 'WAL memory'}, SHARED), None, None))
            db.commit()
            snap = self.root / 'wal-snapshot.sqlite3'
            rescue.snapshot(self.source, snap)
            with sqlite3.connect(snap, factory=ReadConnection) as copy:
                self.assertEqual(copy.execute('select count(*) from "kv_.annotations"').fetchone()[0], 2)
        finally:
            db.close()

    def test_closed_wal_store_allows_sqlite_to_create_empty_read_sidecars(self):
        with sqlite3.connect(self.source, factory=ReadConnection) as db:
            db.execute('pragma journal_mode=wal')
        self.assertFalse(Path(str(self.source) + '-wal').exists())
        before = sha256(self.source)
        self.assertEqual(self.recover()['status'], 'complete')
        self.assertEqual(sha256(self.source), before)

    def test_cancel_snapshot_keeps_original_and_no_false_complete_copy(self):
        before = sha256(self.source)
        output = self.root / 'snapshot.sqlite3'
        with self.assertRaises(Cancelled):
            rescue.snapshot(self.source, output, cancel=lambda: True)
        self.assertFalse(output.exists())
        self.assertEqual(sha256(self.source), before)

    def test_complete_pipeline_preserves_auxiliary_excludes_credentials_from_reader(self):
        before = sha256(self.source)
        receipt = self.recover()
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(len(receipt['files']), 5)
        self.assertEqual(recovery.verify(self.output)['status'], 'verified')
        manifest = json.loads((self.output / 'export/manifest.json').read_text())
        self.assertEqual(manifest['excluded']['tokens']['records'], 1)
        self.assertFalse((self.output / 'export/raw/tokens.jsonl').exists())
        self.assertEqual(sha256(self.source), before)
        with sqlite3.connect(self.output / 'preserved/snapshot.sqlite3', factory=ReadConnection) as db:
            self.assertEqual(db.execute('select count(*) from "kv_.tokens"').fetchone()[0], 1)

    def test_retry_after_viewer_failure_does_not_need_original(self):
        with patch('prepare_viewer.build', side_effect=RuntimeError('viewer failed')), self.assertRaises(RuntimeError):
            self.recover()
        receipt = json.loads((self.output / 'recovery.json').read_text())
        self.assertEqual(receipt['preservation'], 'complete')
        self.source.unlink()
        receipt = recovery.recover(self.source.parent.parent, self.output, True, progress=lambda _: None)
        self.assertEqual(receipt['status'], 'complete')

    def test_low_disk_keeps_source_and_records_failure(self):
        before = sha256(self.source)
        with patch('recovery.shutil.disk_usage', return_value=SimpleNamespace(free=1)), self.assertRaisesRegex(OSError, 'free space'):
            self.recover()
        self.assertEqual(sha256(self.source), before)
        self.assertEqual(json.loads((self.output / 'recovery.json').read_text())['status'], 'failed')

    def test_decode_failure_keeps_snapshot_and_partial_receipt(self):
        with sqlite3.connect(self.source, factory=ReadConnection) as db:
            db.execute('update "kv_.annotations" set body=?', (b'bad',))
        with self.assertRaisesRegex(RuntimeError, 'decoded'):
            self.recover()
        receipt = json.loads((self.output / 'recovery.json').read_text())
        self.assertEqual(receipt['preservation'], 'complete')
        self.assertEqual(receipt['status'], 'failed')
        self.assertTrue((self.output / 'preserved/snapshot.sqlite3').exists())

    def test_changed_auxiliary_and_modified_saved_copy_are_rejected(self):
        original = rescue.snapshot
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.source.parent / 'Attachments/example.blob').write_text('Changed while copying')
            return result
        with patch('recovery.rescue.snapshot', changed), self.assertRaisesRegex(ValueError, 'changed'):
            self.recover()
        self.assertNotEqual(json.loads((self.output / 'recovery.json').read_text())['preservation'], 'complete')

    def test_verification_catches_tampering(self):
        self.recover()
        (self.output / 'preserved/auxiliary/Formats/example.piece').write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            recovery.verify(self.output)

    def test_diagnostics_are_allowlisted(self):
        self.recover()
        receipt = self.output / 'recovery.json'
        obj = json.loads(receipt.read_text())
        obj['failure'] = 'private memory secret'
        receipt.write_text(json.dumps(obj))
        report = json.dumps(recovery.diagnostics(self.output))
        for forbidden in ('private memory secret', str(self.root), 'Garden Club', SUMMARY, 'source_identity'):
            self.assertNotIn(forbidden, report)

    def test_lock_and_path_escape_are_rejected(self):
        with exclusive(self.output):
            with self.assertRaisesRegex(RuntimeError, 'already open'):
                with exclusive(self.output):
                    pass
        with self.assertRaises(ValueError):
            child(self.output, '../outside.txt')

    def test_checkpoint_recovers_from_brief_windows_rename_lock(self):
        from recovery_io import write_json
        destination = self.root / 'receipt.json'
        write_json(destination, {'status': 'in-progress'})
        import os
        original = os.replace
        attempts = []
        def locked_then_available(source, target):
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError('Transient sharing violation')
            return original(source, target)
        with patch('recovery_io.os.replace', locked_then_available):
            write_json(destination, {'status': 'complete'})
        self.assertEqual(json.loads(destination.read_text())['status'], 'complete')
        self.assertEqual(len(attempts), 3)

    def test_nonempty_destination_and_source_overlap_are_rejected(self):
        self.output.mkdir()
        (self.output / 'keep.txt').write_text('keep')
        with self.assertRaises(FileExistsError):
            self.recover()
        self.assertEqual((self.output / 'keep.txt').read_text(), 'keep')
        with self.assertRaisesRegex(ValueError, 'outside'):
            recovery.recover(self.source, self.source.parent / 'wrong', True, progress=lambda _: None)

    def test_unicode_paths(self):
        alternate = self.root / 'archive \u96ea \u00e9'
        receipt = recovery.recover(self.source, alternate, True, progress=lambda _: None)
        self.assertEqual(receipt['status'], 'complete')

    def test_standalone_snapshot_can_export_to_a_child_of_its_download_folder(self):
        snapshot = self.root / 'downloads/saved.sqlite3'
        snapshot.parent.mkdir()
        shutil.copyfile(self.source, snapshot)
        receipt = recovery.recover(snapshot, snapshot.parent / 'archive', True, progress=lambda _: None)
        self.assertEqual(receipt['status'], 'complete')
        self.assertTrue(receipt['scope']['standalone_database'])


if __name__ == '__main__':
    unittest.main()
