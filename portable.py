"""Compact, movable Markdown notes from a saved offline export."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import unicodedata

import atlas
from recovery_io import Cancelled, exclusive, private_directory, write_json
from release import VERSION


KINDS = {
    'workstreamSummaries': ('summaries', 'Summaries'),
    'conversations': ('conversations', 'Conversations'),
    'persons': ('people', 'People'),
    'tags': ('tags', 'Tags'),
    'websites': ('websites', 'Websites'),
    'sources': ('sources', 'Sources'),
    'internalSummaryReports': ('profile-reports', 'Internal summary reports'),
    'annotations': ('annotations', 'Linked annotations'),
}
BASE_KINDS = tuple(kind for kind in KINDS if kind != 'annotations')
PROFILE_TYPES = {'HIERARCHICAL_PROFILE_SUMMARY', 'PROFILE_DESCRIPTION'}
PAGE_SIZE = 200
RELATIONSHIP_LIMIT = 60


def _check_cancel(cancel):
    if cancel and cancel():
        raise Cancelled('Markdown export stopped. Keep this incomplete output and choose a fresh destination.')


def _text(value):
    return value if isinstance(value, str) else ''


def _plain(value):
    """Literal inline text, including hostile link labels and HTML."""
    value = html.escape(_text(value).replace('\x00', ''), quote=False)
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~:-])', r'\\\1', value)


def _source_prose(value):
    # Source links, images and raw HTML are deliberately displayed as text.
    # Keep ordinary emphasis/headings; do not interpret source destinations.
    value = html.escape(value.replace('\x00', ''), quote=False)
    value = value.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`').replace('~', '\\~')
    return re.sub(r'(?i)\b([a-z][a-z0-9+.-]*):', r'\1\\:', value)


def source_markdown(value):
    """Escape active source syntax uniformly, including inside source code."""
    # Do not guess Markdown code containers: a dedented list fence can expose
    # supposedly fenced HTML. Literal code delimiters are an intentional tradeoff.
    return _source_prose(_text(value))


def _slug(title):
    normalized = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', normalized).strip('-').lower()[:64].rstrip('-')
    return slug or 'untitled'


def _path(record):
    identity = json.dumps([record['kind'], record['id']], ensure_ascii=True, separators=(',', ':'))
    digest = hashlib.sha256(identity.encode('ascii')).hexdigest()[:20]
    directory = 'profiles' if record.get('annotation_type') in PROFILE_TYPES else KINDS[record['kind']][0]
    return f'{directory}/{_slug(record["title"])}-{digest}.md'


def _link(current, target, label, links):
    links.add((current, target))
    relative = os.path.relpath(target, start=Path(current).parent).replace('\\', '/')
    return '[' + _plain(label).replace('\n', ' ') + '](' + relative + ')'


def _write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(content)


def _document(row):
    document = json.loads(row['json'])
    return document if isinstance(document, dict) else {}


def _record(row, document=None):
    result = {key: _text(row[key]) for key in ('id', 'kind', 'title', 'created')}
    if document is not None:
        result['annotation_type'] = _text(document.get('type'))
        if not result['title']:
            text = _text(document.get('text'))
            first = next((line.strip(' #*`') for line in text.splitlines() if line.strip(' #*`')), '')
            result['title'] = first[:160] or result['annotation_type'] or 'Annotation'
    if not result['title']:
        result['title'] = KINDS[result['kind']][1]
    return result


def _select(db, cancel):
    slots = ','.join('?' for _ in BASE_KINDS)
    records = {}
    for row in db.execute(f'select id,kind,title,created from nodes where kind in ({slots})', BASE_KINDS):
        _check_cancel(cancel)
        records[row['id']] = _record(row)
    for row in db.execute("select id,kind,title,created,json from nodes where kind='annotations'"):
        _check_cancel(cancel)
        document = _document(row)
        if _text(document.get('type')) in PROFILE_TYPES:
            records[row['id']] = _record(row, document)
    # Include directly recorded annotation targets and reverse attachments.
    # Do not recursively pull the capture/event graph into the note collection.
    included = set(records)
    annotation_ids = set()
    for column, other in (('dst', 'src'), ('src', 'dst')):
        query = f"select e.{column},e.{other} from edges e join nodes n on n.id=e.{column} where n.kind='annotations'"
        for identifier, owner in db.execute(query):
            _check_cancel(cancel)
            if owner in included:
                annotation_ids.add(identifier)
    identifiers = sorted(annotation_ids - included)
    for offset in range(0, len(identifiers), 300):
        batch = identifiers[offset:offset + 300]
        rows = db.execute('select id,kind,title,created,json from nodes where id in (' + ','.join('?' for _ in batch) + ')', batch)
        for row in rows:
            records[row['id']] = _record(row, _document(row))
    seen = set()
    for record in records.values():
        record['path'] = _path(record)
        if record['path'].casefold() in seen:
            raise ValueError('Record paths collided. No files were overwritten; use a fresh destination.')
        seen.add(record['path'].casefold())
    return records


def _body(row, document):
    if row['kind'] == 'annotations':
        return _text(document.get('text')) or _text(row['body'])
    # Read original strings, since the search index deliberately limits bodies.
    parts = []
    for field in ('text', 'readable', 'name', 'title', 'url', 'description', 'summary', 'content'):
        value = document.get(field)
        if isinstance(value, str) and value and value not in parts:
            parts.append(value)
    # The indexed person body also carries email and extracted aliases.
    body = _text(row['body'])
    if row['kind'] == 'persons' and body and body not in parts:
        parts.append(body)
    return '\n\n'.join(parts) or body


def _relationships(db, record, records, totals, links, cancel):
    lines = ['## Recorded relationships', '']
    shown = []
    total = missing = outside = 0
    query = 'select e.predicate,e.dst,n.id as found,n.kind from edges e left join nodes n on n.id=e.dst where e.src=? order by e.predicate,e.dst'
    for row in db.execute(query, (record['id'],)):
        _check_cancel(cancel)
        total += 1
        target = records.get(row['dst'])
        if not target:
            missing += row['found'] is None
            outside += row['found'] is not None
        if len(shown) < RELATIONSHIP_LIMIT:
            if target:
                text = _link(record['path'], target['path'], target['title'], links)
            else:
                reason = 'source record missing' if row['found'] is None else 'outside compact export'
                text = _plain(row['dst']) + ' (' + reason + ')'
            shown.append('- ' + _plain(row['predicate']) + ': ' + text)
    totals['outgoing_relationships'] += total
    totals['missing_source_records'] += missing
    totals['out_of_scope_targets'] += outside
    totals['outgoing_entries_omitted'] += max(0, total - RELATIONSHIP_LIMIT)
    lines.extend(shown or ['No outgoing relationships recorded.'])
    lines.extend(('', f'Shown {len(shown)} of {total} outgoing relationships. Unavailable targets: {missing} missing source records, {outside} outside this export.', ''))
    incoming = []
    count = 0
    for row in db.execute('select src,predicate from edges where dst=? order by predicate,src', (record['id'],)):
        _check_cancel(cancel)
        source = records.get(row['src'])
        if source:
            count += 1
            if len(incoming) < RELATIONSHIP_LIMIT:
                incoming.append('- ' + _plain(row['predicate']) + ': ' + _link(record['path'], source['path'], source['title'], links))
    totals['incoming_entries_omitted'] += max(0, count - RELATIONSHIP_LIMIT)
    if count:
        lines.extend(('### Incoming from exported records', '', *incoming, '', f'Shown {len(incoming)} of {count} incoming relationships from exported records.', ''))
    return '\n'.join(lines)


def _note(db, sessions, record, records, totals, links, cancel):
    row = db.execute('select * from nodes where id=?', (record['id'],)).fetchone()
    document = _document(row)
    session = atlas.read_session(sessions, record['id']) if record['kind'] in atlas.SESSION_KINDS else None
    body = session['body'] if session else _body(row, document)
    missing = session['missing_content'] if session else 0
    totals['missing_content_references'] += missing
    # Untrusted titles/IDs stay out of Obsidian properties, where wiki syntax
    # can become a link even inside a quoted YAML string. Preserve exact IDs in
    # record-map.json and show their escaped text below the title.
    metadata = {'kind': record['kind'], 'created_day': atlas.recorded_day(record['created'])}
    if record.get('annotation_type') in PROFILE_TYPES:
        metadata['annotation_type'] = record['annotation_type']
    lines = ['---', *(key + ': ' + json.dumps(value, ensure_ascii=True) for key, value in metadata.items()), '---', '', '# ' + _plain(record['title']).replace('\n', ' '), '', 'Original ID: ' + _plain(record['id']), '', 'Created: ' + _plain(record['created']), '']
    if 'updated' in row.keys() and row['updated']:
        lines.extend(('Updated: ' + _plain(row['updated']), ''))
    lines.extend((source_markdown(body) or 'No readable text was recovered for this record.', ''))
    if missing:
        lines.extend((f'Reconstructed text has {missing} missing content references.', ''))
    lines.extend((_relationships(db, record, records, totals, links, cancel), '', _link(record['path'], 'index.md', 'Back to index', links), ''))
    return '\n'.join(lines)


def _indexes(root, records, links, cancel):
    groups = defaultdict(list)
    for record in records.values():
        groups[record['path'].split('/')[0]].append(record)
    labels = {folder: label for folder, label in KINDS.values()}
    labels['profiles'] = 'Profile history'
    start = ['# Pieces memories', '', 'Open this folder in a Markdown reader or Obsidian. Keep the entire folder together when moving it.', '', 'These are readable notes derived from your saved export. Keep that original export for the full records and captured files.', '', 'Source links, images and code delimiters are displayed as text. Source HTML is escaped; headings and emphasis are kept where possible.', '', '## Browse', '']
    page_count = 0
    for folder, entries in sorted(groups.items()):
        entries.sort(key=lambda r: (not bool(atlas.recorded_day(r['created'])), atlas.recorded_day(r['created']), r['created'], r['id']))
        pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
        start.append('- ' + _link('index.md', folder + '/index-0001.md', labels[folder], links) + f' ({len(entries)} notes)')
        for page in range(pages):
            _check_cancel(cancel)
            current = f'{folder}/index-{page + 1:04d}.md'
            lines = ['# ' + labels[folder], '', f'Page {page + 1} of {pages}. Oldest first; undated records follow dated records.', '']
            previous_day = None
            for record in entries[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
                day = atlas.recorded_day(record['created']) or 'Undated'
                if day != previous_day:
                    lines.extend(('', '## ' + day, ''))
                    previous_day = day
                lines.append('- ' + _link(current, record['path'], record['title'], links))
            lines.append('')
            if page:
                lines.append(_link(current, f'{folder}/index-{page:04d}.md', 'Previous page', links))
            if page + 1 < pages:
                lines.append(_link(current, f'{folder}/index-{page + 2:04d}.md', 'Next page', links))
            lines.extend(('', _link(current, 'index.md', 'Back to index', links), ''))
            _write(root, current, '\n'.join(lines))
            page_count += 1
    if not groups:
        start.append('No records in the compact note scope were found.')
    start.extend(('', 'Relationship sections show at most 60 entries in each direction and report any omitted entries. Missing records and records outside the compact export remain visible as text.', '', 'See manifest.json for scope, counts and limitations. record-map.json maps original identities to note paths.', ''))
    _write(root, 'index.md', '\n'.join(start))
    return page_count + 1


def _source(source):
    source = Path(source).expanduser().resolve()
    if (source / 'export' / 'knowledge.sqlite').is_file():
        return source, source / 'export'
    if (source / 'knowledge.sqlite').is_file():
        recovery = source.parent if (source.parent / 'recovery.json').is_file() and source.name == 'export' else None
        return recovery, source
    raise FileNotFoundError('Choose a saved recovery folder or its export folder containing knowledge.sqlite.')


def _validate_receipt(path):
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('status') != 'complete':
            raise ValueError('The source export is incomplete. Finish recovery before exporting Markdown.')
        return {'status': data['status'], 'format': _text(data.get('format')), 'version': _text(data.get('version'))}
    return {'status': 'receipt-unavailable'}


def _validate_links(root, links, cancel):
    for current, target in links:
        _check_cancel(cancel)
        for relative in (current, target):
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                raise ValueError('A generated Markdown link has no exported target. Choose a fresh destination.')


def _remove_work(work):
    if work.is_dir():
        for path in work.iterdir():
            if path.is_file():
                path.unlink()
        work.rmdir()


def export_markdown(source, output, progress=None, cancel=None):
    """Write a new compact export; never resume or overwrite an old destination."""
    progress = progress or (lambda message: None)
    recovery, export = _source(source)
    output = Path(output).expanduser().resolve()
    source_root = recovery or export
    if output == source_root or source_root in output.parents:
        raise ValueError('Choose a destination outside the saved source archive.')
    if output.exists():
        raise FileExistsError('Markdown export needs a new destination. Existing files were kept; choose a fresh folder.')
    receipt = {'format': 'pieces-portable-markdown-v1', 'version': VERSION, 'status': 'in-progress',
               'created': datetime.now(timezone.utc).isoformat(), 'counts': {'notes': 0}}
    with ExitStack() as locks:
        if recovery:
            locks.enter_context(exclusive(recovery, '.recovery.lock'))
        locks.enter_context(exclusive(export))
        if recovery:
            _validate_receipt(recovery / 'recovery.json')
        receipt['source'] = _validate_receipt(export / 'manifest.json')
        output.mkdir(parents=True, exist_ok=False)
        private_directory(output)
        work = output / '.portable-work'
        work.mkdir()
        try:
            write_json(output / 'portable.json', receipt)
            _check_cancel(cancel)
            progress('Preparing readable summaries and conversations for Markdown export.')
            sessions_path = atlas.ensure(export, output_root=work)
            _check_cancel(cancel)
            with atlas.connect(export / 'knowledge.sqlite') as db, atlas.connect(sessions_path) as sessions:
                db.execute('begin')
                records = _select(db, cancel)
                links = set()
                totals = Counter({'outgoing_relationships': 0, 'missing_source_records': 0,
                                  'out_of_scope_targets': 0, 'outgoing_entries_omitted': 0,
                                  'incoming_entries_omitted': 0, 'missing_content_references': 0})
                for number, record in enumerate(sorted(records.values(), key=lambda r: r['path']), 1):
                    _check_cancel(cancel)
                    _write(output, record['path'], _note(db, sessions, record, records, totals, links, cancel))
                    receipt['counts']['notes'] = number
                    if number == 1 or number % 100 == 0:
                        progress(f'Writing Markdown notes: {number} of {len(records)}.')
                index_count = _indexes(output, records, links, cancel)
                _validate_links(output, links, cancel)
                counts = dict(Counter(record['kind'] for record in records.values()))
                profile_count = sum(record.get('annotation_type') in PROFILE_TYPES for record in records.values())
                write_json(output / 'record-map.json', {'format': receipt['format'], 'records': [
                    {key: record[key] for key in ('id', 'kind', 'path')} for record in sorted(records.values(), key=lambda r: (r['kind'], r['id']))]})
                manifest = {'format': receipt['format'], 'version': VERSION, 'source': receipt['source'], 'status': 'complete', 'counts': counts,
                            'notes': len(records), 'index_pages': index_count, 'profile_versions': profile_count,
                            'validated_links': len(links),
                            'relationships': dict(totals), 'relationship_limit_per_direction': RELATIONSHIP_LIMIT,
                            'scope': {'collections': list(BASE_KINDS), 'annotations': 'All retained HIERARCHICAL_PROFILE_SUMMARY and PROFILE_DESCRIPTION records, plus annotations directly linked to included records by recorded edges.',
                                      'excluded': 'Other captures, events, message sidecars, raw JSON and captured files remain in the saved source export.',
                                      'source_markdown': 'Source links, images and code delimiters are displayed as text, and HTML is escaped throughout. Headings and emphasis are retained where possible.',
                                      'coverage': 'Counts describe this saved export only; absent source records or profile versions cannot be recovered by this conversion.'}}
            _remove_work(work)
            _check_cancel(cancel)
            write_json(output / 'manifest.json', manifest)
            receipt.update(status='complete', counts={'notes': len(records), 'index_pages': index_count,
                                                    'profile_versions': profile_count, 'by_kind': counts})
            write_json(output / 'portable.json', receipt)
            progress(f'Markdown export complete: {len(records)} notes. Open index.md in the destination.')
            return receipt
        except BaseException as error:
            receipt['status'] = 'cancelled' if isinstance(error, (Cancelled, KeyboardInterrupt)) else 'failed'
            receipt['failure'] = type(error).__name__
            receipt['next_step'] = 'Keep this incomplete output and choose a fresh destination.'
            for name in ('portable.json', 'manifest.json'):
                try:
                    write_json(output / name, receipt)
                except OSError:
                    # Preserve the original failure when the destination itself
                    # cannot accept a diagnostic receipt (for example, full disk).
                    pass
            raise
        finally:
            try:
                _remove_work(work)
            except OSError:
                pass
