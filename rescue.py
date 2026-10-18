#!/usr/bin/env python3
"""Offline, read-only Pieces/Couchbase Lite recovery. No Pieces process or MCP."""
from __future__ import annotations
import argparse, base64, json, os, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import purefleece
from recovery_io import Cancelled, check_cancel, child, exclusive, private_directory, replace_file, sha256, write_json
from release import VERSION
SENSITIVE = re.compile(r'(oauth|token|pkce|password|secret|credential|users|subscriptions|sensitives)', re.I)
INDEXED = {'workstreamSummaries','workstreamEvents','annotations','conversations','conversationMessages','conversationMemories','persons','websites','assets','hints','tags','ranges','sources','signals','internalSummaryReports'}
UUID = re.compile(r'^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$', re.I)

def open_source(path):
    con = None
    try:
        con=sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=1)
        con.execute('pragma query_only=ON'); con.execute('select name from sqlite_master limit 1').fetchone()
        return con, 'live-readonly'
    except sqlite3.Error:
        if con is not None:
            con.close()
        # DrvFs/WSL rejects SQLite file locks. Immutable skips WAL: report the gap.
        con=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)
        con.execute('pragma query_only=ON'); con.execute('select name from sqlite_master limit 1').fetchone()
        return con, 'immutable-WAL-omitted'

def locate(folder):
    folder=Path(folder).expanduser().resolve()
    choices=[folder,folder/'Pieces'/'couchbase.cblite2'/'db.sqlite3',folder/'couchbase.cblite2'/'db.sqlite3',folder/'Pieces OS'/'com.pieces.os'/'production'/'Pieces'/'couchbase.cblite2'/'db.sqlite3',folder/'com.pieces.os'/'production'/'Pieces'/'couchbase.cblite2'/'db.sqlite3']
    for p in choices:
        if p.is_file():
            with p.open('rb') as f:
                if f.read(16)==b'SQLite format 3\0': return p
    raise FileNotFoundError('No Pieces Couchbase SQLite found under '+str(folder))

class Fleece:
    """Pure-Python decoder; drops the native-library dependency entirely."""
    def __init__(self, state, library=None):
        self.shared = purefleece.shared_keys_from_state(state)
    def decode(self, body):
        return purefleece.decode(body, self.shared) if body else None
    def close(self):
        pass

def collections_in(con):
    names=[n for (n,) in con.execute("select name from sqlite_master where type='table' and name like 'kv_._%' and instr(name,'::')=0")]
    out=[]
    for n in names:
        if n.startswith('kv_del_') or n.endswith('_expiration'):continue
        # kv_.camel\\Case in SQLite; its logical collection is camelCase.
        logical=n[4:].replace('\\','')
        cols={r[1] for r in con.execute('pragma table_info("'+n.replace('"','""')+'")')}
        if {'key','body','sequence'} <= cols:out.append((n,logical))
    return sorted(out,key=lambda x:x[1])

def safe_table(n):return '"'+n.replace('"','""')+'"'
def compact(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
def value_date(obj,k):
    v=obj.get(k) if isinstance(obj,dict) else None
    return (v.get('value') or '') if isinstance(v,dict) else (v if isinstance(v,str) else '')
def links(obj):
    if not isinstance(obj,dict):return
    for field,val in obj.items():
        if not isinstance(val,dict):continue
        ids=[]
        if isinstance(val.get('indices'),dict):ids.extend(val['indices'])
        if isinstance(val.get('id'),str):ids.append(val['id'])
        if isinstance(val.get('iterable'),list):ids.extend(item.get('id') for item in val['iterable'] if isinstance(item,dict))
        for ref in dict.fromkeys(ids):
            if isinstance(ref,str) and UUID.fullmatch(ref):yield field,ref

def searchable(obj,kind):
    if not isinstance(obj,dict):return '', ''
    title=obj.get('name') or obj.get('title') or obj.get('url') or obj.get('readable') or ''
    if kind=='persons':
        basic=(obj.get('type') or {}).get('basic') or {}
        title=basic.get('name') or title
        if basic.get('email'):parts=[basic['email']]
        else:parts=[]
        extraction=obj.get('extraction') or {}
        parts.extend(str(v) for v in extraction.get('aliases',[]) if isinstance(v,str))
    else:parts=[]
    if isinstance(title,dict):title=title.get('value','')
    for field in ('text','readable','name','title','url','description','summary','content'):
        v=obj.get(field)
        if isinstance(v,str):parts.append(v)
    if kind=='conversationMessages':
        frag=obj.get('fragment') or {}
        if isinstance(frag,dict):
            string=frag.get('string') or {}
            if isinstance(string,dict):parts.extend(v for v in string.values() if isinstance(v,str))
    return str(title)[:500], '\n'.join(parts)[:1000000]

def schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT, body TEXT, created TEXT, updated TEXT, json TEXT NOT NULL, source TEXT NOT NULL);
      CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(title,body,content='nodes',content_rowid='rowid');
      CREATE TABLE IF NOT EXISTS edges(src TEXT NOT NULL, predicate TEXT NOT NULL, dst TEXT NOT NULL, PRIMARY KEY(src,predicate,dst));
      CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
      CREATE INDEX IF NOT EXISTS nodes_source ON nodes(source);
      CREATE TABLE IF NOT EXISTS counts(collection TEXT PRIMARY KEY, expected INTEGER, exported INTEGER, indexed INTEGER, errors INTEGER);
    ''')

def snapshot(source, output, progress=None, cancel=None):
    src = locate(source)
    dst = Path(output).expanduser().resolve()
    if dst.exists():
        raise FileExistsError(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    temporary = dst.with_name(dst.name + '.partial')
    # Only our own temporary file may be replaced on retry.
    temporary.unlink(missing_ok=True)
    inp = sqlite3.connect(src.as_uri() + '?mode=ro', uri=True, timeout=10)
    target = None
    try:
        inp.execute('pragma query_only=ON')
        target = sqlite3.connect(temporary)
        def update(status, remaining, total):
            check_cancel(cancel)
            if progress:
                progress('Preserving database: %d%%' % (100 * (total - remaining) // max(1, total)))
        inp.backup(target, pages=1024, progress=update, sleep=0.25)
        target.close(); target = None
        replace_file(temporary, dst)
        return dst
    finally:
        if target is not None:
            target.close()
        inp.close()
        temporary.unlink(missing_ok=True)


def scan(source):
    path=locate(source);con,mode=open_source(path)
    print('Source:',path,'\nRead mode:',mode)
    if mode.startswith('immutable'):print('WARNING: SQLite WAL sidecar is not read; run on Windows or export from a closed, checkpointed copy.')
    total=0
    for table,name in collections_in(con):
        n=con.execute('select count(*) from '+safe_table(table)).fetchone()[0]
        if n:print(f'{name:46} {n:>9}'+(' [secrets excluded by default]' if SENSITIVE.search(name) else ''))
        total+=n
    print('Total collection records:',total)
    con.close()

def export(args, progress=None, cancel=None):
    target = Path(args.output).expanduser().resolve()
    resume = getattr(args, 'resume', False)
    if target.exists() and any(target.iterdir()) and not resume:
        raise FileExistsError('Output directory must be empty. Use --resume for an interrupted beta export.')
    if not target.exists() or not any(target.iterdir()):
        private_directory(target)
    with exclusive(target):
        return _export(args, target, progress or (lambda message: print(message, flush=True)), cancel)


def _export(args, target, progress, cancel):
    source = locate(args.source)
    if args.limit < 0:
        raise ValueError('The test limit must be zero or positive')
    receipt = target / 'manifest.json'
    identity = {'sha256': sha256(source, cancel), 'bytes': source.stat().st_size}
    wal = Path(str(source) + '-wal')
    identity['wal_sha256'] = sha256(wal, cancel) if wal.exists() and wal.stat().st_size else None
    options = {'per_collection': args.limit, 'include_secrets': args.include_secrets}
    if receipt.exists():
        manifest = json.loads(receipt.read_text(encoding='utf-8'))
        if (manifest.get('format') != 'pieces-rescue-v2' or manifest.get('identity') != identity
                or manifest.get('options') != options):
            raise ValueError('Source or export options changed. Choose a new destination.')
        # Verify completed files before trusting a checkpoint.
        for item in manifest['collections'].values():
            path = child(target, item['file'])
            if not path.is_file() or sha256(path, cancel) != item['sha256']:
                raise ValueError('A completed raw file is missing or changed. Keep this archive and choose a new destination.')
    else:
        if any(p.name != '.rescue.lock' for p in target.iterdir()):
            raise ValueError('No beta receipt found. Choose an empty destination; existing files were kept.')
        manifest = {'format': 'pieces-rescue-v2', 'version': VERSION, 'source': str(source),
                    'identity': identity, 'source_size': identity['bytes'], 'options': options,
                    'limits': {'per_collection': args.limit}, 'include_secrets': args.include_secrets,
                    'collections': {}, 'excluded': {}, 'errors': []}
    manifest['status'] = 'in-progress'
    manifest.pop('failure', None)
    write_json(receipt, manifest)
    con = index = decoder = None
    active = None
    rawdir = target / 'raw'
    rawdir.mkdir(exist_ok=True)
    try:
        con, mode = open_source(source)
        manifest['read_mode'] = mode
        manifest['wal_bytes'] = wal.stat().st_size if wal.exists() else 0
        if mode.startswith('immutable') and not getattr(args, 'allow_wal_omission', False):
            raise RuntimeError('SQLite could not read the WAL safely. Run on the source OS or use a closed snapshot. Advanced use requires --allow-wal-omission.')
        if mode.startswith('immutable') and getattr(args, 'require_wal', False):
            raise RuntimeError('Cannot prove WAL inclusion; --require-wal requested')
        con.execute('begin')  # One consistent read transaction across collections.
        state = con.execute("select body from kv_info where key='SharedKeys'").fetchone()
        if not state:
            raise ValueError('Couchbase SharedKeys missing; source snapshot is still usable for future recovery.')
        decoder = Fleece(state[0], getattr(args, 'fleece_library', None))
        index = sqlite3.connect(target / 'knowledge.sqlite')
        schema(index)
        # A collection is the atomic checkpoint. A crash after DB commit but before
        # receipt publication leaves this collection untrusted; remove and replay it.
        completed = set(manifest['collections'])
        for (name,) in index.execute('select distinct source from nodes').fetchall():
            if name not in completed:
                index.execute("insert into search(search,rowid,title,body) select 'delete',rowid,title,body from nodes where source=?", (name,))
                index.execute('delete from edges where src in (select id from nodes where source=?)', (name,))
                index.execute('delete from nodes where source=?', (name,))
                index.execute('delete from counts where collection=?', (name,))
        index.commit()
        for table, name in collections_in(con):
            check_cancel(cancel)
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
                raise ValueError('Unsupported collection name; refusing unsafe output path')
            expected = con.execute('select count(*) from ' + safe_table(table)).fetchone()[0]
            if SENSITIVE.search(name) and not args.include_secrets:
                manifest['excluded'][name] = {'records': expected, 'reason': 'account or credential collection'}
                continue
            if name in completed:
                actual = index.execute('select count(*) from nodes where source=?', (name,)).fetchone()[0]
                if actual != manifest['collections'][name]['indexed']:
                    raise ValueError('Completed index checkpoint changed; choose a new destination.')
                progress('Already recovered: ' + name)
                continue
            active = name
            count = indexed = errors = 0
            out = rawdir / (name + '.jsonl')
            partial = out.with_suffix('.jsonl.partial')
            manifest['active_collection'] = name
            write_json(receipt, manifest)
            progress('Recovering %s: %d records' % (name, expected))
            index.execute('begin')
            with partial.open('w', encoding='utf-8', newline='\n') as stream:
                query = 'select key,sequence,flags,version,body,extra,expiration from ' + safe_table(table) + ' order by key'
                if args.limit:
                    query += ' limit ' + str(args.limit)
                for key, seq, flags, version, body, extra, expiration in con.execute(query):
                    check_cancel(cancel)
                    record = {'collection': name, 'id': key, 'sequence': seq, 'flags': flags, 'expiration': expiration,
                              'version_b64': base64.b64encode(version or b'').decode(),
                              'body_b64': base64.b64encode(body or b'').decode(),
                              'extra_b64': base64.b64encode(extra or b'').decode()}
                    obj = None
                    try:
                        obj = decoder.decode(body)
                    except (ValueError, TypeError, IndexError, RecursionError):
                        errors += 1
                        record['decode_error'] = 'Unsupported or malformed Fleece body'
                    if obj is not None:
                        record['document'] = obj
                    stream.write(compact(record) + '\n')
                    count += 1
                    if obj is not None and name in INDEXED and isinstance(obj, dict):
                        title, text = searchable(obj, name)
                        index.execute('insert into nodes values(?,?,?,?,?,?,?,?)',
                                      (key, name, title, text, value_date(obj, 'created'), value_date(obj, 'updated'), compact(obj), name))
                        rowid = index.execute('select rowid from nodes where id=?', (key,)).fetchone()[0]
                        index.execute('insert into search(rowid,title,body) values(?,?,?)', (rowid, title, text))
                        index.executemany('insert or ignore into edges values(?,?,?)', ((key, pred, ref) for pred, ref in links(obj)))
                        indexed += 1
                    if count % 1000 == 0:
                        progress('Recovering %s: %d / %d' % (name, count, expected))
                stream.flush()
                os.fsync(stream.fileno())
            # Commit, rename, then publish receipt. Any interruption before receipt
            # publication is replayed as an entire collection on the next run.
            index.execute('insert or replace into counts values(?,?,?,?,?)', (name, expected, count, indexed, errors))
            index.commit()
            replace_file(partial, out)
            digest = sha256(out, cancel)
            manifest['collections'][name] = {'expected': expected, 'exported': count, 'indexed': indexed,
                                             'decode_errors': errors, 'file': out.relative_to(target).as_posix(),
                                             'bytes': out.stat().st_size, 'sha256': digest}
            manifest.pop('active_collection', None)
            write_json(receipt, manifest)
            active = None
        check_cancel(cancel)
        index.execute("insert into search(search) values('optimize')")
        index.commit()
        issues = mode.startswith('immutable') or any(v['decode_errors'] or (not args.limit and v['expected'] != v['exported']) for v in manifest['collections'].values())
        manifest['status'] = 'test-limited' if args.limit else ('incomplete' if issues else 'complete')
        write_json(receipt, manifest)
        progress('Recovery: ' + manifest['status'])
        if issues:
            raise RuntimeError('Some records could not be decoded, or WAL was omitted. Raw files and source are preserved. See manifest.json.')
        return manifest
    except BaseException as error:
        if index:
            index.rollback()
        if manifest['status'] == 'in-progress':
            manifest['status'] = 'cancelled' if isinstance(error, (Cancelled, KeyboardInterrupt)) else 'failed'
            manifest['failure'] = type(error).__name__
            # If the filesystem is full, the previous in-progress receipt remains.
            try:
                write_json(receipt, manifest)
            except OSError:
                pass
        raise
    finally:
        if decoder:
            decoder.close()
        if con:
            con.close()
        if index:
            index.close()


def search(dbpath,term,limit=20):
    db=sqlite3.connect(Path(dbpath).resolve().as_uri()+'?mode=ro',uri=True)
    try:return db.execute('select n.id,n.kind,n.title,snippet(search,1,"[","]","...",16) from search join nodes n on n.rowid=search.rowid where search match ? order by rank limit ?', (term,min(limit,100))).fetchall()
    finally:db.close()


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace')
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    s=sub.add_parser('scan');s.add_argument('source')
    snap=sub.add_parser('snapshot');snap.add_argument('source');snap.add_argument('output')
    e=sub.add_parser('export');e.add_argument('source');e.add_argument('output');e.add_argument('--limit',type=int,default=0,help='TEST ONLY: max records per collection');e.add_argument('--fleece-library');e.add_argument('--include-secrets',action='store_true');e.add_argument('--require-wal',action='store_true');e.add_argument('--allow-wal-omission',action='store_true');e.add_argument('--resume',action='store_true')
    q=sub.add_parser('search');q.add_argument('output');q.add_argument('query');q.add_argument('--limit',type=int,default=20)
    v=sub.add_parser('serve');v.add_argument('output');v.add_argument('--port',type=int,default=8765)
    a=ap.parse_args()
    if a.command=='scan':scan(a.source)
    elif a.command=='snapshot':snapshot(a.source,a.output)
    elif a.command=='export':export(a)
    elif a.command=='search':
        for row in search(Path(a.output)/'knowledge.sqlite',a.query,a.limit):print('\t'.join(str(x or '') for x in row))
    else:
        from viewer import serve
        serve(a.output,a.port)
if __name__=='__main__':main()
