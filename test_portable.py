"""Portable notes preserve source identities and stay safe when moved."""
import hashlib
import contextlib
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import portable
from recovery_io import Cancelled, exclusive


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'saved' / 'export'
        self.source.mkdir(parents=True)
        self.output = self.root / 'notes'
        self.dbfile = self.source / 'knowledge.sqlite'
        self.db = sqlite3.connect(self.dbfile)
        self.addCleanup(self.db.close)
        self.db.executescript('''
            create table nodes(id text primary key,kind text,title text,body text,created text,updated text,json text);
            create table edges(src text,predicate text,dst text,primary key(src,predicate,dst));
            create index edges_dst on edges(dst);
        ''')
        self.add('summary', 'workstreamSummaries', 'Plan: spring/garden', 'Fallback', {
            'annotations': {'indices': {'narrative': 0, 'profile-old': 0, 'missing-content': 0}}})
        self.add('narrative', 'annotations', '', '', {'type': 'SUMMARY', 'text': '# Plan\n\nThe **complete** narrative.\n\n```python\nprint("<garden>")\n```'})
        self.add('profile-old', 'annotations', 'Garden profile', '', {'type': 'HIERARCHICAL_PROFILE_SUMMARY', 'text': 'Old retained profile prose.'}, created='2025-01-01T00:00:00Z')
        self.add('profile-new', 'annotations', 'Garden profile', '', {'type': 'HIERARCHICAL_PROFILE_SUMMARY', 'text': 'New retained profile prose.'}, created='2026-01-01T00:00:00Z')
        self.add('description', 'annotations', '', '', {'type': 'PROFILE_DESCRIPTION', 'text': 'Profile description prose.'})
        self.add('unrelated', 'annotations', '', '', {'type': 'DESCRIPTION', 'text': 'Unrelated capture.'})
        self.add('reverse', 'annotations', 'Reverse narrative', '', {'type': 'SUMMARY', 'text': 'Reverse attached narrative.', 'summaries': {'indices': {'summary': 0}}})
        self.add('chat', 'conversations', 'Garden discussion', '', {'messages': {'indices': {'message': 0}}})
        self.add('message', 'conversationMessages', '', '', {'role': 'USER', 'fragment': {'string': {'raw': 'Remember all the seedlings.'}}, 'conversation': {'id': 'chat'}})
        self.add('person', 'persons', 'Gardener', 'gardener@example.invalid', {})
        self.add('report', 'internalSummaryReports', 'Retained report', '', {'text': 'Report text.'})
        self.add('event', 'workstreamEvents', 'Capture', 'Raw event', {})
        self.add('evil-kind', '../../outside', 'Escape', 'Secret', {})
        for src, predicate, dst in [('summary', 'annotations', 'narrative'), ('summary', 'annotations', 'profile-old'),
                                     ('reverse', 'summaries', 'summary'), ('summary', 'events', 'event'),
                                     ('summary', 'missing', 'absent'), ('summary', 'persons', 'person'),
                                     ('person', 'annotations', 'profile-new')]:
            self.db.execute('insert into edges values(?,?,?)', (src, predicate, dst))
        self.db.commit()
        (self.source / 'manifest.json').write_text('{"status":"complete"}', encoding='utf-8')
        (self.source.parent / 'recovery.json').write_text('{"status":"complete","private":"original"}', encoding='utf-8')

    def add(self, identifier, kind, title, body, document, created='2026-07-01T12:00:00Z'):
        self.db.execute('insert into nodes values(?,?,?,?,?,?,?)', (identifier, kind, title, body, created, '', json.dumps(document)))

    def run_export(self, **kwargs):
        self.db.commit()
        # Permission behavior belongs to recovery_io; avoid a Windows process
        # for every synthetic fixture while still verifying this API uses it.
        with patch.object(portable, 'private_directory') as private:
            result = portable.export_markdown(self.source, self.output, **kwargs)
            private.assert_called_once_with(self.output)
        return result

    def read_map(self):
        data = json.loads((self.output / 'record-map.json').read_text(encoding='utf-8'))
        return {item['id']: item for item in data['records']}

    def note(self, identifier):
        return (self.output / self.read_map()[identifier]['path']).read_text(encoding='utf-8')

    def test_reconstructed_notes_profile_history_and_source_unchanged(self):
        self.db.close()
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.dbfile, self.source / 'manifest.json', self.source.parent / 'recovery.json')}
        result = portable.export_markdown(self.source.parent, self.output)
        self.assertEqual(result['status'], 'complete')
        notes = self.read_map()
        self.assertEqual(set(notes), {'summary', 'narrative', 'profile-old', 'profile-new', 'description', 'reverse', 'chat', 'person', 'report'})
        summary = self.note('summary')
        self.assertIn('The **complete** narrative.', summary)
        self.assertIn('Reverse attached narrative.', summary)
        self.assertNotIn('Old retained profile prose.', summary)
        self.assertNotIn('New retained profile prose.', summary)
        self.assertIn('Garden profile', summary)
        self.assertIn('Old retained profile prose.', self.note('profile-old'))
        self.assertIn('New retained profile prose.', self.note('profile-new'))
        self.assertNotEqual(notes['profile-old']['path'], notes['profile-new']['path'])
        self.assertIn('Remember all the seedlings.', self.note('chat'))
        self.assertIn('Report text.', self.note('report'))
        self.assertIn('1 missing content references', summary)
        self.assertIn('source record missing', summary)
        self.assertIn('outside compact export', summary)
        self.assertFalse((self.source / 'atlas.sqlite').exists())
        self.assertFalse((self.output / '.portable-work').exists())
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        manifest = json.loads((self.output / 'manifest.json').read_text())
        self.assertEqual(manifest['profile_versions'], 3)
        self.assertEqual(manifest['relationships']['missing_source_records'], 1)
        self.assertEqual(manifest['relationships']['out_of_scope_targets'], 1)
        self.assertEqual(manifest['relationships']['missing_content_references'], 1)

    def test_every_generated_link_survives_moving_the_folder(self):
        self.run_export()
        moved = self.root / 'moved'
        shutil.move(self.output, moved)
        self.output = moved
        links = 0
        for path in moved.rglob('*.md'):
            for target in re.findall(r'(?<!\\)\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                links += 1
                self.assertNotIn(':', target)
                destination = (path.parent / target).resolve()
                self.assertIn(moved, destination.parents)
                self.assertTrue(destination.is_file(), (path, target))
        self.assertGreater(links, 15)

    def test_hostile_non_uuid_ids_titles_metadata_and_case_collisions(self):
        titles = ['CON', 'con', '..\\..\\outside', '../outside', 'NUL. ', 'AUX', '[click](javascript:evil)', '"\n---\n<script>evil</script>']
        for number, title in enumerate(titles):
            self.add('../../id/' + str(number), 'tags', title, 'Tag', {})
        self.run_export()
        notes = self.read_map()
        paths = [record['path'] for record in notes.values()]
        self.assertEqual(len(paths), len(set(path.lower() for path in paths)))
        for path in paths:
            self.assertRegex(path, r'^[a-z-]+/[a-z0-9-]+-[0-9a-f]{20}\.md$')
            self.assertTrue((self.output / path).is_file())
        self.assertNotIn('title:', self.note('../../id/7').split('---')[1])
        self.assertNotIn('id:', self.note('../../id/7').split('---')[1])
        self.assertEqual(notes['../../id/7']['id'], '../../id/7')
        self.assertNotIn('\n<script>', self.note('../../id/7'))

    def test_source_markdown_is_inert_and_keeps_emphasis_with_literal_code(self):
        source = '**emphasis**\n<script>evil</script>\n![remote](https://evil.invalid/a.png)\n[evil](javascript:run())\n[x][ref]\n[ref]: data:text/html,evil\n\\![escaped](https://evil.invalid)\n<https://evil.invalid>\n`<code>[x](y)`\n`<script>not-code``\n```html\n<img src="https://evil.invalid">\n```\n```python\nprint("open fence")'
        rendered = portable.source_markdown(source)
        self.assertIn('**emphasis**', rendered)
        self.assertIn('&lt;script&gt;evil&lt;/script&gt;', rendered)
        self.assertIn('\\![', source)
        self.assertNotRegex(rendered, r'(?<!\\)!\[')
        self.assertNotRegex(rendered, r'(?<!\\)\]\(')
        self.assertIn('javascript\\:', rendered)
        self.assertIn('\\`&lt;code&gt;\\[x\\](y)\\`', rendered)
        self.assertIn('\\`&lt;script&gt;not-code\\`\\`', rendered)
        self.assertIn('\\`\\`\\`html\n&lt;img src="https\\://evil.invalid"&gt;\n\\`\\`\\`', rendered)
        self.assertNotIn('<img', rendered)

    def test_source_list_fences_cannot_expose_dedented_html_or_images(self):
        for marker in ('- item', '1. item', '- item\n  - nested'):
            for fence in ('```', '~~~'):
                source = marker + '\n   ' + fence + '\n<img src="https://example.invalid" onerror="evil()">\n![x](https://example.invalid/x.png)\n' + fence
                rendered = portable.source_markdown(source)
                self.assertIn('&lt;img src=', rendered)
                self.assertNotIn('<img', rendered)
                self.assertNotIn('\n   ' + fence, rendered)

    def test_existing_destination_and_source_subdirectory_are_refused(self):
        self.output.mkdir()
        sentinel = self.output / 'keep.txt'
        sentinel.write_text('keep', encoding='utf-8')
        with self.assertRaisesRegex(FileExistsError, 'fresh'):
            self.run_export()
        self.assertEqual(sentinel.read_text(), 'keep')
        with self.assertRaisesRegex(ValueError, 'outside'):
            portable.export_markdown(self.source, self.source / 'notes')
        sentinel.unlink()
        with self.assertRaises(FileExistsError):
            portable.export_markdown(self.source, self.output)

    def test_cancellation_leaves_explicit_receipt_and_refuses_retry(self):
        with self.assertRaisesRegex(Cancelled, 'fresh destination'):
            self.run_export(cancel=lambda: True)
        receipt = json.loads((self.output / 'portable.json').read_text())
        self.assertEqual(receipt['status'], 'cancelled')
        self.assertIn('fresh destination', receipt['next_step'])
        self.assertFalse((self.output / '.portable-work').exists())
        with self.assertRaises(FileExistsError):
            portable.export_markdown(self.source, self.output)

    def test_failure_after_partial_write_records_actual_progress(self):
        real_write = portable._write
        count = 0
        def fail(root, path, content):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError('synthetic failure')
            return real_write(root, path, content)
        with patch.object(portable, '_write', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                self.run_export()
        receipt = json.loads((self.output / 'portable.json').read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['counts']['notes'], 2)
        self.assertEqual(receipt['failure'], 'OSError')
        self.assertNotIn('synthetic', json.dumps(receipt))

    def test_source_lock_and_incomplete_receipt_are_respected(self):
        with exclusive(self.source):
            with self.assertRaises(RuntimeError):
                portable.export_markdown(self.source, self.output)
        self.assertFalse(self.output.exists())
        (self.source / 'manifest.json').write_text('{"status":"failed"}')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            portable.export_markdown(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_chronological_indexes_paginate_and_relationship_bounds_are_explicit(self):
        for number in range(67):
            identifier = f'tag-{number:03d}'
            self.add(identifier, 'tags', 'Topic ' + str(number), 'Topic', {}, created='invalid' if number == 0 else '2026-01-01T00:00:00Z')
            self.db.execute('insert into edges values(?,?,?)', ('summary', 'tags', identifier))
        with patch.object(portable, 'PAGE_SIZE', 10):
            self.run_export()
        self.assertEqual(len(list((self.output / 'tags').glob('index-*.md'))), 7)
        self.assertIn('Undated', (self.output / 'tags/index-0007.md').read_text())
        self.assertIn('Shown 60 of 72 outgoing relationships.', self.note('summary'))
        manifest = json.loads((self.output / 'manifest.json').read_text())
        self.assertEqual(manifest['relationships']['outgoing_entries_omitted'], 12)

    def test_incoming_relationship_navigation_is_bounded_and_counted(self):
        for number in range(65):
            identifier = f'tag-{number:03d}'
            self.add(identifier, 'tags', 'Topic ' + str(number), 'Topic', {})
            self.db.execute('insert into edges values(?,?,?)', (identifier, 'persons', 'person'))
        self.run_export()
        self.assertIn('Shown 60 of 66 incoming relationships from exported records.', self.note('person'))
        manifest = json.loads((self.output / 'manifest.json').read_text())
        self.assertEqual(manifest['relationships']['incoming_entries_omitted'], 6)

    def test_malformed_annotation_type_is_not_a_profile(self):
        self.add('malformed', 'annotations', 'Malformed enum', '', {'type': {'unexpected': True}, 'text': 'Linked narrative.'})
        self.db.execute('insert into edges values(?,?,?)', ('summary', 'annotations', 'malformed'))
        self.run_export()
        self.assertTrue(self.read_map()['malformed']['path'].startswith('annotations/'))
        self.assertIn('Linked narrative.', self.note('malformed'))

    def test_cancellation_during_writing_and_missing_generated_target_prevent_success(self):
        stopped = False
        def progress(message):
            nonlocal stopped
            if message.startswith('Writing Markdown notes:'):
                stopped = True
        with self.assertRaises(Cancelled):
            self.run_export(progress=progress, cancel=lambda: stopped)
        receipt = json.loads((self.output / 'portable.json').read_text())
        self.assertEqual(receipt['status'], 'cancelled')
        self.assertEqual(receipt['counts']['notes'], 1)
        self.output = self.root / 'broken-links'
        real_write = portable._write
        def omit_index(root, path, content):
            if path != 'index.md':
                real_write(root, path, content)
        with patch.object(portable, '_write', side_effect=omit_index):
            with self.assertRaisesRegex(ValueError, 'no exported target'):
                self.run_export()
        self.assertEqual(json.loads((self.output / 'portable.json').read_text())['status'], 'failed')

    def test_legacy_markdown_entry_point_uses_the_safe_exporter(self):
        import render
        self.db.commit()
        with self.assertRaisesRegex(ValueError, '--output'):
            render.render(self.source, ['markdown'])
        with self.assertRaisesRegex(ValueError, '--limit'):
            render.render(self.source, ['markdown'], limit=1, output=self.output)
        self.assertFalse(self.output.exists())
        with patch.object(portable, 'private_directory'), contextlib.redirect_stdout(io.StringIO()):
            render.render(self.source, ['markdown'], output=self.output)
        self.assertIn('The **complete** narrative.', self.note('summary'))
        self.assertNotIn('Old retained profile prose.', self.note('summary'))


if __name__ == '__main__':
    unittest.main()
