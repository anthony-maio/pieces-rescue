"""Offline Pieces Rescue explorer. Only binds loopback; read-only SQLite."""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import atlas

HERE = Path(__file__).resolve().parent
KINDS = {'workstreamEvents', 'workstreamSummaries', 'annotations', 'conversationMessages',
         'conversations', 'conversationMemories', 'persons', 'websites', 'assets', 'hints',
         'tags', 'ranges', 'sources', 'signals', 'internalSummaryReports'}
UUID = re.compile(r'^[0-9a-fA-F-]{36}$')


def connect(path):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5, factory=atlas.ReadConnection)
    db.row_factory = sqlite3.Row
    db.execute('pragma query_only=on')
    db.execute('pragma cache_size=-8192')
    return db


def row_node(r):
    return dict(r) if r else None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        host = self.headers.get('Host', '').split(':', 1)[0].lower()
        if host not in ('127.0.0.1', 'localhost', '[::1]'):
            return self.send_json(403, {'error': 'Local requests only'})
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send_json(403, {'error': 'Open the local viewer directly'})
        u = urllib.parse.urlsplit(self.path)
        if u.path in ('/', '/app'):
            return self.send_bytes(200, (HERE / 'viewer.html').read_bytes(), 'text/html; charset=utf-8')
        if u.path == '/viewer.js':
            return self.send_bytes(200, (HERE / 'viewer.js').read_bytes(), 'text/javascript; charset=utf-8')
        if u.path == '/viewer.css':
            return self.send_bytes(200, (HERE / 'viewer.css').read_bytes(), 'text/css; charset=utf-8')
        if not u.path.startswith('/api/'):
            return self.send_json(404, {'error': 'Not found'})
        p = urllib.parse.parse_qs(u.query)
        arg = lambda k, default='': p.get(k, [default])[0]
        try:
            if u.path in ('/api/atlas', '/api/sessions'):
                with atlas.connect(self.server.atlas_database) as adb:
                    if u.path == '/api/atlas':
                        return self.send_json(200, atlas.overview(adb, arg('from'), arg('to')))
                    first, last = atlas.bounds(adb)
                    return self.send_json(200, atlas.browse(adb, arg('from', first), arg('to', last),
                        topic=arg('topic'), project=arg('project'), day=arg('day'), query=arg('q')[:250],
                        page=min(max(int(arg('page', '0')), 0), 10000)))
            with connect(self.server.database) as db:
                if u.path == '/api/overview':
                    rows = db.execute('select collection, indexed from counts where indexed > 0 order by indexed desc').fetchall()
                    return self.send_json(200, {'collections': [dict(r) for r in rows],
                                                'source': self.server.source, 'status': self.server.status})
                if u.path == '/api/timeline':
                    kind = arg('kind')
                    if kind and kind not in KINDS:
                        return self.send_json(400, {'error': 'Unknown record type'})
                    rows = db.execute('select month,sum(records) as records from timeline_months ' + ('where kind=? ' if kind else '') + 'group by month order by month', (kind,) if kind else ()).fetchall()
                    return self.send_json(200, {'months': [dict(r) for r in rows]})
                if u.path == '/api/search':
                    q = arg('q').strip()[:250]
                    month = arg('month')
                    if month and (not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month) or month[:4] == '0000'):
                        return self.send_json(400, {'error': 'Invalid month'})
                    kind = arg('kind')
                    page = min(max(int(arg('page', '0')), 0), 10000)
                    if kind and kind not in KINDS:
                        return self.send_json(400, {'error': 'Unknown record type'})
                    if not q and not month:
                        return self.send_json(200, {'items': [], 'page': page, 'more': False})
                    if q:
                        sql = '''select n.id,n.kind,n.title,substr(n.body,1,320) as excerpt,n.created
                                 from search join nodes n on n.rowid=search.rowid where search match ?'''
                        terms = re.findall(r'\w+', q, re.UNICODE)
                        if not terms:
                            return self.send_json(200, {'items': [], 'page': page, 'more': False})
                        args = [' AND '.join('"' + word + '"' for word in terms)]
                    else:
                        sql = '''select n.id,n.kind,n.title,substr(n.body,1,320) as excerpt,n.created
                                 from nodes n where 1=1'''
                        args = []
                    if month:
                        sql += ' and n.created >= ? and n.created < ?'
                        year, number = map(int, month.split('-'))
                        next_month = '%04d-%02d' % (year + (number == 12), number % 12 + 1)
                        args.extend([month, next_month])
                    if kind:
                        sql += ' and n.kind=?'; args.append(kind)
                    sql += (' order by rank' if q else ' order by n.created desc, n.id') + ' limit 25 offset ?'; args.append(page * 24)
                    rows = [dict(r) for r in db.execute(sql, args)]
                    return self.send_json(200, {'items': rows[:24], 'page': page, 'more': len(rows) > 24})
                if u.path in ('/api/node', '/api/neighborhood'):
                    identifier = arg('id')
                    if not UUID.fullmatch(identifier):
                        return self.send_json(400, {'error': 'Invalid record ID'})
                    center = db.execute('select id,kind,title,body,created,updated,json from nodes where id=?', (identifier,)).fetchone()
                    if not center:
                        return self.send_json(404, {'error': 'Record not indexed'})
                    if u.path == '/api/node':
                        record = dict(center)
                        record['document'] = json.loads(record.pop('json'))
                        with atlas.connect(self.server.atlas_database) as adb:
                            session = atlas.read_session(adb, identifier)
                        if session:
                            record.update(session)
                        return self.send_json(200, record)
                    outgoing = db.execute('select predicate,dst as id from edges where src=? order by predicate,dst limit 61', (identifier,)).fetchall()
                    incoming = db.execute('select predicate,src as id from edges where dst=? order by predicate,src limit 61', (identifier,)).fetchall()
                    relationships = [{'predicate': r['predicate'], 'id': r['id'], 'direction': direction}
                                     for direction, rows in (('out', outgoing[:60]), ('in', incoming[:60])) for r in rows]
                    ids = list(dict.fromkeys(r['id'] for r in relationships))
                    matches = {}
                    for start in range(0, len(ids), 80):
                        part = ids[start:start+80]
                        for r in db.execute('select id,kind,title,created,substr(body,1,220) as excerpt from nodes where id in (' + ','.join('?'*len(part)) + ')', part):
                            matches[r['id']] = dict(r)
                    for r in relationships:
                        r.update(matches.get(r['id'], {'kind': 'unindexed', 'title': r['id'], 'created': '', 'excerpt': ''}))
                    return self.send_json(200, {'center': {k: center[k] for k in ('id','kind','title','created','body')},
                                                'relationships': relationships,
                                                'truncated': len(outgoing)>60 or len(incoming)>60})
                return self.send_json(404, {'error': 'Unknown endpoint'})
        except (ValueError, sqlite3.OperationalError) as e:
            return self.send_json(400, {'error': str(e)[:180]})

    def send_bytes(self, status, data, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data):
        self.send_bytes(status, json.dumps(data, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

    def log_message(self, *_):
        pass


def make_server(output, port=8765):
    root = Path(output).expanduser().resolve()
    dbfile = root / 'knowledge.sqlite'
    if not dbfile.is_file():
        raise FileNotFoundError(dbfile)
    with connect(dbfile) as check:
        ready = check.execute("select 1 from sqlite_master where type='table' and name='timeline_months'").fetchone()
    if not ready:
        from prepare_viewer import build
        print('Preparing local timeline and date indexes once; large archives may take several minutes...', flush=True)
        build(root)
    manifest = root / 'manifest.json'
    receipt = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    atlas_database = atlas.ensure(root)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.database = dbfile
    server.atlas_database = atlas_database
    server.source = Path(receipt.get('source', '')).name or root.name
    server.status = receipt.get('status', 'unverified legacy receipt')
    return server


def serve(output, port=8765):
    from recovery_io import exclusive
    with exclusive(Path(output).expanduser().resolve()):
        _serve(output, port)


def _serve(output, port):
    server = make_server(output, port)
    print('Local explorer: http://127.0.0.1:%s' % server.server_port, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output'); ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args(); serve(a.output, a.port)
