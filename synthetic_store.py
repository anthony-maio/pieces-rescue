"""Small, invented stores for portable tests. No customer data or reference binary."""
import sqlite3
import struct
from pathlib import Path

SUMMARY = '00000000-0000-0000-0000-000000000001'
ANNOTATION = '00000000-0000-0000-0000-000000000002'
TAG = '00000000-0000-0000-0000-000000000003'
CHAT = '00000000-0000-0000-0000-000000000004'
MESSAGE = '00000000-0000-0000-0000-000000000005'
SHARED = ['title', 'text', 'created', 'value', 'annotations', 'indices', 'tags', 'messages', 'role', 'fragment', 'string', 'raw', 'conversation', 'id']


def encode(value, shared=None):
    """Minimal test-only Fleece writer: aligned wide containers and backward pointers."""
    data = bytearray()
    def emit(item):
        if isinstance(item, (dict, list)):
            values = []
            if isinstance(item, dict):
                for key, val in item.items():
                    values.extend([shared.index(key) if shared and key in shared else key, val])
            else:
                values = item
            offsets = [emit(val) for val in values]
            pos = len(data)
            count = len(item)
            data.extend(struct.pack('>H', (0x7800 if isinstance(item, dict) else 0x6800) | count))
            for target in offsets:
                data.extend(struct.pack('>I', 0x80000000 | ((len(data) - target) // 2)))
            return pos
        pos = len(data)
        if item is None:
            data.extend(b'\x30\x00')
        elif isinstance(item, bool):
            data.extend(b'\x38\x00' if item else b'\x34\x00')
        elif isinstance(item, int) and -2048 <= item < 2048:
            data.extend(struct.pack('>H', item & 0xfff))
        elif isinstance(item, str):
            raw = item.encode('utf-8')
            if len(raw) < 15:
                data.append(0x40 | len(raw))
            else:
                data.append(0x4f)
                size = len(raw)
                while size >= 128:
                    data.append((size & 127) | 128); size >>= 7
                data.append(size)
            data.extend(raw)
            if len(data) % 2:
                data.append(0)
        else:
            raise ValueError('Unsupported synthetic value')
        return pos
    root = emit(value)
    data.extend(struct.pack('>H', 0x8000 | ((len(data) - root) // 2)))
    return bytes(data)


def create(path, broken=False, auxiliary=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = {
        'annotations': [(ANNOTATION, {'text': '# Garden Club\n\nThe recovered **full summary** about Pieces seedlings.'})],
        'tags': [(TAG, {'text': 'Garden Planning'})],
        'workstreamSummaries': [(SUMMARY, {'title': 'Garden Club planning', 'created': {'value': '2026-07-01T12:00:00Z'},
                                         'annotations': {'indices': {ANNOTATION: 0}}, 'tags': {'indices': {TAG: 0}}})],
        'conversations': [(CHAT, {'title': 'Garden Club chat', 'created': {'value': '2026-07-02T12:00:00Z'}, 'messages': {'indices': {MESSAGE: 0}}})],
        'conversationMessages': [(MESSAGE, {'role': 'USER', 'fragment': {'string': {'raw': 'Remember the seedlings.'}},
                                           'created': {'value': '2026-07-02T12:01:00Z'}, 'conversation': {'id': CHAT}})],
        'tokens': [('private-test-id', {'text': 'synthetic-secret-excluded'})],
    }
    db = sqlite3.connect(path)
    try:
        db.execute('create table kv_info(key text primary key,body blob)')
        db.execute('insert into kv_info values(?,?)', ('SharedKeys', encode(SHARED)))
        for name, items in rows.items():
            db.execute('create table "kv_.' + name + '" (key text primary key,sequence integer,flags integer,version blob,body blob,extra blob,expiration integer)')
            for number, (key, body) in enumerate(items):
                db.execute('insert into "kv_.' + name + '" values(?,?,?,?,?,?,?)', (key, number + 1, 0, b'v1', encode(body, SHARED), None, None))
        if broken:
            db.execute('insert into "kv_.annotations" values(?,?,?,?,?,?,?)', ('broken-id', 2, 0, None, b'bad', None, None))
        db.commit()
    finally:
        db.close()
    if auxiliary:
        root = path.parent.parent
        for rel in ('couchbase.cblite2/Attachments/example.blob', 'Formats/example.piece', 'vector_db/example.vec', 'vector_db/metadata-wal'):
            item = root / rel
            item.parent.mkdir(parents=True, exist_ok=True)
            item.write_bytes(b'Synthetic supporting file. No personal data.')
    return path
