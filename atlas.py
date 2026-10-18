"""Small, rebuildable session atlas. The preserved export is read-only.

atlas.sqlite is a separate derivative: complete summary text, conversation text,
recorded tag memberships, and explicitly detected project memberships.
"""
from __future__ import annotations
import itertools
import json
import os
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VERSION = '3'
SESSION_KINDS = ('workstreamSummaries', 'conversations')
PROFILE_ANNOTATIONS = ('HIERARCHICAL_PROFILE_SUMMARY', 'PROFILE_DESCRIPTION')
GENERIC = set('a an the and or of in on to for with from by at as ai code review analysis planning development research implementation technical project projects summary overview update updates system systems design engineering software discussion integration debugging deployment testing work workflow documentation meeting daily notes management setup configuration maintenance optimization investigation architecture audit security task tasks strategy strategic engine agentic model models infrastructure safety career legal coordination content release operational planning platform deployment protocol governance integration support reflection synthesis workflow automation enhancement performance systems discussion refinement exploration progress networking'.split())


class ReadConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, factory=ReadConnection)
    db.row_factory = sqlite3.Row
    db.execute('pragma query_only=on')
    return db


def references(document, field):
    value = document.get(field) or {}
    if not isinstance(value, dict):
        return []
    ids = list(value.get('indices', {})) if isinstance(value.get('indices'), dict) else []
    if isinstance(value.get('iterable'), list):
        ids.extend(item.get('id') for item in value['iterable'] if isinstance(item, dict))
    if isinstance(value.get('id'), str):
        ids.append(value['id'])
    return list(dict.fromkeys(identifier for identifier in ids if isinstance(identifier, str)))


def recorded_day(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.date().isoformat()
    except (ValueError, TypeError, AttributeError):
        return ''


def normalize(value):
    return re.sub(r'[\s_-]+', ' ', value.strip().lower()) if isinstance(value, str) else ''


def signature(source):
    info = source.stat()
    return f'{VERSION}:{info.st_size}:{info.st_mtime_ns}'


def related_nodes(db, identifiers):
    result = {}
    ids = list(dict.fromkeys(identifiers))
    for offset in range(0, len(ids), 300):
        batch = ids[offset:offset + 300]
        rows = db.execute('select id,kind,title,body,created,json from nodes where id in (' + ','.join('?' for _ in batch) + ')', batch)
        for row in rows:
            result[row['id']] = dict(row)
    return result


def detect_projects(sessions):
    """Repeated capitalized title phrases, never claimed as recorded tags."""
    frequency = Counter()
    per_session = {}
    for session in sessions:
        words = re.findall(r"[A-Za-z][A-Za-z0-9.'+-]*", session['title'] or '')
        phrases = set()
        for size in (2, 3):
            for start in range(len(words) - size + 1):
                part = words[start:start + size]
                if not all(word[0].isupper() or word.lower() in {'of', 'and', 'for'} for word in part):
                    continue
                if part[0].lower() in GENERIC or part[-1].lower() in GENERIC:
                    continue
                if not any(word.lower() not in GENERIC and len(word) >= 3 for word in part):
                    continue
                phrases.add(' '.join(part))
        per_session[session['id']] = phrases
        frequency.update(phrases)
    selected = []
    for phrase, count in sorted(frequency.items(), key=lambda pair: (-pair[1], -len(pair[0]), pair[0])):
        if count < 3 or len(selected) >= 8:
            break
        if any(phrase.lower() in other.lower() or other.lower() in phrase.lower() for other in selected):
            continue
        selected.append(phrase)
    return [(session_id, phrase) for session_id, phrases in per_session.items() for phrase in selected if phrase in phrases]


def build(root, output_root=None):
    """Build derived sessions, optionally keeping every output outside the archive."""
    root = Path(root).resolve()
    source = root / 'knowledge.sqlite'
    destination = Path(output_root).resolve() if output_root is not None else root
    destination.mkdir(parents=True, exist_ok=True)
    cache = destination / 'atlas.sqlite'
    source_signature = signature(source)
    with connect(source) as db:
        sessions = [dict(row) for row in db.execute('select id,kind,title,body,created,json from nodes where kind in (?,?)', SESSION_KINDS)]
        documents = {row['id']: json.loads(row['json']) for row in sessions}
        ids = [identifier for document in documents.values() for field in ('annotations', 'tags', 'messages') for identifier in references(document, field)]
        related = related_nodes(db, ids)
        # An annotation may record its summary attachment only on its own side.
        # Use that recorded reference without adding edges to the source index.
        summary_ids = {row['id'] for row in sessions if row['kind'] == 'workstreamSummaries'}
        by_summary = defaultdict(list)
        for item in db.execute("select id,kind,title,body,created,json from nodes where kind='annotations' order by id"):
            parents = [parent for parent in references(json.loads(item['json']), 'summaries') if parent in summary_ids]
            if parents:
                related[item['id']] = dict(item)
                for parent in parents:
                    by_summary[parent].append(item['id'])
        # Also include messages whose parent is recorded only on the message.
        messages = [dict(row) for row in db.execute("select id,kind,title,body,created,json from nodes where kind='conversationMessages'")]
    by_conversation = defaultdict(list)
    for row in messages:
        document = json.loads(row['json'])
        for parent in references(document, 'conversation'):
            by_conversation[parent].append(row['id'])
        related[row['id']] = row
    topic_rows = []
    for row in sessions:
        document = documents[row['id']]
        row['day'] = recorded_day(row['created'])
        day = date.fromisoformat(row['day']) if row['day'] else None
        row['week'] = date.fromordinal(day.toordinal() - day.weekday()).isoformat() if day else ''
        row['content_sources'] = []
        row['missing_content'] = 0
        content = []
        if row['kind'] == 'workstreamSummaries':
            direct_annotations = references(document, 'annotations')
            identifiers = list(dict.fromkeys(direct_annotations + by_summary[row['id']]))
        else:
            identifiers = list(dict.fromkeys(references(document, 'messages') + by_conversation[row['id']]))
            identifiers.sort(key=lambda identifier: (related.get(identifier, {}).get('created') or '', identifier))
        for identifier in identifiers:
            item = related.get(identifier)
            if not item:
                row['missing_content'] += 1
                continue
            doc = json.loads(item['json'])
            if row['kind'] == 'workstreamSummaries':
                if item['kind'] != 'annotations':
                    row['missing_content'] += 1
                    continue
                # Profile reports remain separate source records, not summary prose.
                if doc.get('type') in PROFILE_ANNOTATIONS:
                    continue
                text = doc.get('text')
            else:
                fragment = doc.get('fragment') or {}
                string = fragment.get('string') or {} if isinstance(fragment, dict) else {}
                text = string.get('raw') if isinstance(string, dict) else ''
            text = text if isinstance(text, str) and text else item['body']
            if text:
                if row['kind'] == 'conversations':
                    role = doc.get('role') or 'Message'
                    role = role if isinstance(role, str) else 'Message'
                    content.append('### ' + role.capitalize() + '\n\n' + text)
                else:
                    content.append(text)
                content_source = {'id': identifier, 'kind': item['kind']}
                if row['kind'] == 'workstreamSummaries':
                    content_source['provenance'] = ('summary.annotations' if identifier in direct_annotations
                                                    else 'annotation.summaries')
                row['content_sources'].append(content_source)
        if content:
            row['body'] = '\n\n'.join(content)
        topic_labels = set()
        for identifier in references(document, 'tags'):
            item = related.get(identifier)
            if item and item['kind'] == 'tags':
                label = normalize(json.loads(item['json']).get('text'))
                if label and len(label) <= 100:
                    topic_labels.add(label)
        topic_rows.extend((row['id'], label) for label in topic_labels)
    project_rows = detect_projects(sessions)
    temp = destination / ('atlas-' + uuid.uuid4().hex + '.tmp.sqlite')
    try:
        db = sqlite3.connect(temp)
        try:
            db.executescript('''
                create table meta(key text primary key,value text);
                create table sessions(id text primary key,kind text,title text,body text,created text,day text,week text,content_sources text,missing_content integer);
                create index session_days on sessions(day,created);
                create table topics(session_id text,topic text,primary key(session_id,topic));
                create index topics_label on topics(topic,session_id);
                create table projects(session_id text,project text,primary key(session_id,project));
                create index projects_label on projects(project,session_id);
                create virtual table session_search using fts5(title,body,content='sessions',content_rowid='rowid');
            ''')
            db.executemany('insert into sessions values(?,?,?,?,?,?,?,?,?)',
                [(r['id'],r['kind'],r['title'],r['body'],r['created'],r['day'],r['week'],json.dumps(r['content_sources']),r['missing_content']) for r in sessions])
            db.executemany('insert into topics values(?,?)', topic_rows)
            db.executemany('insert into projects values(?,?)', project_rows)
            db.execute("insert into session_search(session_search) values('rebuild')")
            db.execute('insert into meta values(?,?)', ('signature', source_signature))
            db.commit()
        finally:
            db.close()
        if signature(source) != source_signature:
            raise RuntimeError('The export index changed during atlas preparation; retry with a stable export.')
        os.replace(temp, cache)
    finally:
        if temp.exists():
            temp.unlink()
    return cache


def ensure(root, output_root=None):
    root = Path(root).resolve()
    destination = Path(output_root).resolve() if output_root is not None else root
    cache = destination / 'atlas.sqlite'
    if cache.exists():
        with connect(cache) as db:
            row = db.execute("select value from meta where key='signature'").fetchone()
            current = signature(root / 'knowledge.sqlite')
            if row and row['value'] == current:
                return cache
    return build(root, output_root=output_root)


def bounds(db):
    row = db.execute("select min(day) as first,max(day) as last from sessions where day<>''").fetchone()
    return row['first'] or '', row['last'] or ''


def validate_range(start, end):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', start or '') or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', end or ''):
        raise ValueError('Choose a valid date range.')
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('The start date must precede the end date.')


def read_session(db, identifier):
    row = db.execute('select body,content_sources,missing_content from sessions where id=?', (identifier,)).fetchone()
    if not row:
        return None
    return {'body': row['body'], 'content_sources': json.loads(row['content_sources']), 'missing_content': row['missing_content']}


def overview(db, start='', end=''):
    first, last = bounds(db)
    if not first:
        return {'first':'','last':'','from':'','to':'','sessions':0,'days':[],'topics':[],'projects':[],'weeks':[],'connections':[], 'undated':db.execute('select count(*) from sessions').fetchone()[0]}
    start, end = start or first, end or last
    validate_range(start, end)
    days = [dict(row) for row in db.execute('select day,count(*) as sessions from sessions where day between ? and ? group by day order by day', (start,end))]
    first_week = date.fromisoformat(start)
    first_week -= timedelta(days=first_week.weekday())
    weeks = [(first_week + timedelta(days=offset)).isoformat() for offset in range(0, (date.fromisoformat(end)-first_week).days+1, 7)]
    def groups(table, field, limit):
        rows = db.execute(f'select g.{field} as name,count(*) as sessions from {table} g join sessions s on s.id=g.session_id where s.day between ? and ? group by g.{field} order by sessions desc,name limit ?', (start,end,limit)).fetchall()
        result = []
        for row in rows:
            counts = dict(db.execute(f'select s.week,count(*) from {table} g join sessions s on s.id=g.session_id where g.{field}=? and s.day between ? and ? group by s.week', (row['name'],start,end)))
            result.append({'name':row['name'],'sessions':row['sessions'],'weeks':[counts.get(week,0) for week in weeks]})
        return result
    topics = groups('topics','topic',10)
    projects = groups('projects','project',8)
    # A project map describes detected co-mentions; fallback tags are recorded memberships.
    table, field, nodes = ('projects','project',projects) if len(projects)>1 else ('topics','topic',topics[:8])
    selected = {row['name'] for row in nodes}
    per_session = defaultdict(set)
    for row in db.execute(f'select g.session_id,g.{field} from {table} g join sessions s on s.id=g.session_id where s.day between ? and ?', (start,end)):
        if row[1] in selected:
            per_session[row[0]].add(row[1])
    pairs = Counter(pair for labels in per_session.values() for pair in itertools.combinations(sorted(labels),2))
    return {'first':first,'last':last,'from':start,'to':end,'sessions':sum(row['sessions'] for row in days),
        'days':days,'weeks':weeks,'topics':topics,'projects':projects,
        'map_kind':field,'map_nodes':nodes,
        'connections':[{'source':a,'target':b,'sessions':count} for (a,b),count in pairs.most_common(16)],
        'undated':db.execute("select count(*) from sessions where day='' ").fetchone()[0],
        'tagged_sessions':db.execute('select count(distinct s.id) from sessions s join topics t on t.session_id=s.id where s.day between ? and ?', (start,end)).fetchone()[0]}


def browse(db, start, end, topic='', project='', day='', query='', page=0):
    validate_range(start,end)
    where = ['s.day between ? and ?']; args = [start,end]
    if day:
        date.fromisoformat(day)
        where.append('s.day=?'); args.append(day)
    for table, field, value in [('topics','topic',topic),('projects','project',project)]:
        if value:
            where.append(f'exists(select 1 from {table} g where g.session_id=s.id and g.{field}=?)'); args.append(value)
    if query:
        # The primary reader accepts ordinary text, including hyphenated names.
        terms = re.findall(r'\w+', query, re.UNICODE)
        if terms:
            where.append('s.rowid in (select rowid from session_search where session_search match ?)')
            args.append(' AND '.join('"'+term+'"' for term in terms))
        else:
            where.append('0')
    clause=' and '.join(where)
    total=db.execute('select count(*) from sessions s where '+clause,args).fetchone()[0]
    rows=[dict(row) for row in db.execute('select s.id,s.kind,s.title,s.created,s.day,substr(s.body,1,320) as excerpt from sessions s where '+clause+' order by s.created desc,s.id limit 25 offset ?',args+[max(0,int(page))*24])]
    return {'items':rows[:24],'page':page,'more':len(rows)>24,'total':total}
