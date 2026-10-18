"""Deterministic checks for readable sessions and the atlas drill-down."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import atlas


class AtlasDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'knowledge.sqlite'
        db = sqlite3.connect(self.source)
        db.execute('create table nodes(id text primary key,kind text,title text,body text,created text,json text)')
        self.summary = '00000000-0000-0000-0000-000000000001'
        self.annotation = '00000000-0000-0000-0000-000000000002'
        self.tag = '00000000-0000-0000-0000-000000000003'
        self.chat = '00000000-0000-0000-0000-000000000004'
        self.message = '00000000-0000-0000-0000-000000000005'
        rows = [
            (self.summary, 'workstreamSummaries', 'Garden Club planning', 'Garden Club planning', '2026-07-01T12:00:00Z',
             {'annotations': {'indices': {self.annotation: 0}}, 'tags': {'indices': {self.tag: 0}}}),
            (self.annotation, 'annotations', '', '', '', {'text': '# Plans\n\nThe recovered **full summary**.'}),
            (self.tag, 'tags', '', '', '', {'text': 'Garden-Planning'}),
            (self.chat, 'conversations', 'Garden Club chat', '', '2026-07-02T12:00:00Z', {'messages': {'indices': {self.message: 0}}}),
            (self.message, 'conversationMessages', '', '', '2026-07-02T13:00:00Z',
             {'role': 'USER', 'fragment': {'string': {'raw': 'Remember the seedlings.'}}, 'conversation': {'id': self.chat}}),
            ('00000000-0000-0000-0000-000000000006', 'workstreamSummaries', 'Undated', 'Undated', 'bad timestamp', {}),
        ]
        db.executemany('insert into nodes values(?,?,?,?,?,?)', [(i,k,t,b,c,json.dumps(d)) for i,k,t,b,c,d in rows])
        db.commit(); db.close()
        self.before = self.source.read_bytes()
        self.cache = atlas.build(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_recovers_linked_summary_and_chat_without_changing_source(self):
        with atlas.connect(self.cache) as db:
            summary = atlas.read_session(db, self.summary)
            chat = atlas.read_session(db, self.chat)
        self.assertIn('The recovered **full summary**.', summary['body'])
        self.assertEqual(summary['content_sources'][0]['id'], self.annotation)
        self.assertIn('User', chat['body'])
        self.assertIn('Remember the seedlings.', chat['body'])
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_calendar_and_topic_filters_return_the_records_they_count(self):
        with atlas.connect(self.cache) as db:
            data = atlas.overview(db, '2026-07-01', '2026-07-02')
            records = atlas.browse(db, '2026-07-01', '2026-07-02', topic='garden planning')
        self.assertEqual(data['sessions'], 2)
        self.assertEqual(sum(row['sessions'] for row in data['days']), 2)
        self.assertEqual(data['undated'], 1)
        self.assertEqual(records['total'], 1)
        self.assertEqual(records['items'][0]['id'], self.summary)
        self.assertIn('full summary', records['items'][0]['excerpt'])

    def test_bad_dates_and_unknown_filters_do_not_expand_scope(self):
        with atlas.connect(self.cache) as db:
            with self.assertRaises(ValueError):
                atlas.overview(db, '2026-02-30', '2026-07-02')
            with self.assertRaises(ValueError):
                atlas.overview(db, '2026-08-01', '2026-07-02')
            self.assertEqual(atlas.browse(db, '2026-07-01', '2026-07-02', topic='missing')['total'], 0)
            self.assertEqual(atlas.browse(db, '2026-07-01', '2026-07-02', day='2026-07-02')['items'][0]['id'], self.chat)

    def test_cache_reuse_and_missing_annotations_are_explicit(self):
        self.assertEqual(atlas.ensure(self.root), self.cache)
        db = sqlite3.connect(self.source)
        db.execute('delete from nodes where id=?', (self.annotation,)); db.commit(); db.close()
        self.cache = atlas.ensure(self.root)
        with atlas.connect(self.cache) as db:
            record = atlas.read_session(db, self.summary)
        self.assertEqual(record['missing_content'], 1)
        self.assertEqual(record['body'], 'Garden Club planning')

    def test_profile_annotations_remain_separate_from_summary_narrative(self):
        profiles = [
            ('profile-report', 'HIERARCHICAL_PROFILE_SUMMARY', 'Separate profile report.'),
            ('profile-description', 'PROFILE_DESCRIPTION', 'Separate profile description.'),
        ]
        stamp = '2026-07-01T12:00:00.123456+04:00'
        with sqlite3.connect(self.source, factory=atlas.ReadConnection) as db:
            summary = json.loads(db.execute('select json from nodes where id=?', (self.summary,)).fetchone()[0])
            for identifier, kind, text in profiles:
                summary['annotations']['indices'][identifier] = 0
                document = {'type': kind, 'text': text, 'created': {'value': stamp}}
                db.execute('insert into nodes values(?,?,?,?,?,?)',
                           (identifier, 'annotations', kind, text, stamp, json.dumps(document)))
            db.execute('update nodes set json=? where id=?', (json.dumps(summary), self.summary))
        before = self.source.read_bytes()
        with atlas.connect(atlas.ensure(self.root)) as db:
            summary = atlas.read_session(db, self.summary)
        self.assertIn('The recovered **full summary**.', summary['body'])
        self.assertEqual([item['id'] for item in summary['content_sources']], [self.annotation])
        self.assertEqual(summary['missing_content'], 0)
        with atlas.connect(self.source) as db:
            for identifier, kind, text in profiles:
                self.assertNotIn(text, summary['body'])
                record = db.execute('select * from nodes where id=?', (identifier,)).fetchone()
                self.assertEqual(record['created'], stamp)
                self.assertEqual(json.loads(record['json'])['text'], text)
        self.assertEqual(self.source.read_bytes(), before)

    def test_reverse_annotation_references_recover_only_recorded_attachments(self):
        with sqlite3.connect(self.source, factory=atlas.ReadConnection) as db:
            summary = json.loads(db.execute('select json from nodes where id=?', (self.summary,)).fetchone()[0])
            summary['annotations']['indices']['missing-annotation'] = 0
            db.execute('update nodes set json=? where id=?', (json.dumps(summary), self.summary))
            annotation = json.loads(db.execute('select json from nodes where id=?', (self.annotation,)).fetchone()[0])
            annotation['summaries'] = {'id': self.summary}
            db.execute('update nodes set json=? where id=?', (json.dumps(annotation), self.annotation))
            for identifier, document in [
                ('inverse-body', {'type': 'SUMMARY', 'text': 'Narrative linked from the annotation.',
                                  'summaries': {'iterable': [{'id': self.summary}]}}),
                ('inverse-profile', {'type': 'HIERARCHICAL_PROFILE_SUMMARY', 'text': 'Retained profile prose.',
                                     'summaries': {'indices': {self.summary: 0}}}),
                ('unrelated', {'type': 'SUMMARY', 'text': 'Matching title alone is not an attachment.'}),
            ]:
                db.execute('insert into nodes values(?,?,?,?,?,?)',
                           (identifier, 'annotations', 'Garden Club planning', '', '2026-07-01T12:00:00Z', json.dumps(document)))
        before = self.source.read_bytes()
        with atlas.connect(atlas.ensure(self.root)) as db:
            summary = atlas.read_session(db, self.summary)
        self.assertEqual(summary['body'].count('The recovered **full summary**.'), 1)
        self.assertIn('Narrative linked from the annotation.', summary['body'])
        self.assertNotIn('Retained profile prose.', summary['body'])
        self.assertNotIn('Matching title alone', summary['body'])
        self.assertEqual(summary['missing_content'], 1)
        sources = {item['id']: item for item in summary['content_sources']}
        self.assertEqual(set(sources), {self.annotation, 'inverse-body'})
        self.assertEqual(sources[self.annotation]['provenance'], 'summary.annotations')
        self.assertEqual(sources['inverse-body']['provenance'], 'annotation.summaries')
        self.assertEqual(self.source.read_bytes(), before)

    def test_previous_atlas_version_rebuilds_session_text(self):
        with sqlite3.connect(self.cache, factory=atlas.ReadConnection) as db:
            old = '2:' + atlas.signature(self.source).partition(':')[2]
            db.execute("update meta set value=? where key='signature'", (old,))
            db.execute('update sessions set body=? where id=?', ('Old combined profile prose.', self.summary))
        with atlas.connect(atlas.ensure(self.root)) as db:
            summary = atlas.read_session(db, self.summary)
            signature = db.execute("select value from meta where key='signature'").fetchone()[0]
        self.assertIn('The recovered **full summary**.', summary['body'])
        self.assertNotIn('Old combined profile prose.', summary['body'])
        self.assertEqual(signature, atlas.signature(self.source))
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_external_atlas_output_leaves_source_archive_unchanged(self):
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        with tempfile.TemporaryDirectory() as output:
            cache = atlas.ensure(self.root, output_root=output)
            self.assertEqual(cache, Path(output).resolve() / 'atlas.sqlite')
            with atlas.connect(cache) as db:
                self.assertIn('full summary', atlas.read_session(db, self.summary)['body'])
            cache_before = cache.read_bytes()
            self.assertEqual(atlas.ensure(self.root, output_root=output), cache)
            self.assertEqual(cache.read_bytes(), cache_before)
        self.assertEqual({path.name: path.read_bytes() for path in self.root.iterdir()}, before)

    def test_search_uses_recovered_text_and_week_axis_preserves_gaps(self):
        with atlas.connect(self.cache) as db:
            matches = atlas.browse(db, '2026-07-01', '2026-07-02', query='recovered-full')
            self.assertEqual(matches['items'][0]['id'], self.summary)
            self.assertEqual(atlas.browse(db, '2026-07-01', '2026-07-02', query='"')['total'], 0)
            data = atlas.overview(db, '2026-07-01', '2026-08-02')
        self.assertEqual(len(data['weeks']), 5)
        self.assertEqual(data['topics'][0]['weeks'], [1, 0, 0, 0, 0])

    def test_preparation_builds_both_indexes_without_rewriting_records(self):
        from prepare_viewer import build
        with atlas.connect(self.source) as db:
            before = [tuple(row) for row in db.execute('select * from nodes order by id')]
        build(self.root)
        with atlas.connect(self.source) as db:
            self.assertTrue(db.execute('select count(*) from timeline_months').fetchone()[0])
            self.assertEqual([tuple(row) for row in db.execute('select * from nodes order by id')], before)
        with atlas.connect(atlas.ensure(self.root)) as db:
            self.assertIn('full summary', atlas.read_session(db, self.summary)['body'])


if __name__ == '__main__':
    unittest.main()
