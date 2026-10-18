"""Pure-Python Fleece decoder.

Implements the Fleece binary format as published in the Couchbase fleece
repository's format documentation (Fleece.md) and verified against the
reference implementation's reading code: value tags, narrow/wide pointers,
dictionary inheritance (magic -2048 parent key), 11-bit collection counts
with varint overflow, shared integer keys, and the SharedKeys state blob
(which is itself a Fleece array of strings).

Decodes to Python values: dict / list / str / int / float / bool / None.
Fleece binary values decode to base64 ASCII strings (JSON-compatible).
External pointers are rejected; Couchbase Lite databases do not use them
in document bodies.
"""
from __future__ import annotations
import base64
import struct

class FleeceError(ValueError):
    pass

TAG_SHORT_INT = 0
TAG_INT = 1
TAG_FLOAT = 2
TAG_SPECIAL = 3
TAG_STRING = 4
TAG_BINARY = 5
TAG_ARRAY = 6
TAG_DICT = 7
# tags 8..15 are pointers (in narrow context) / wide-pointer fragments

class _Decoder:
    __slots__ = ('data', 'shared')

    def __init__(self, data: bytes, shared=None):
        self.data = data
        self.shared = shared

    # -- low-level helpers -------------------------------------------------

    def _uvarint(self, pos: int):
        result = 0; shift = 0; start = pos
        while pos < len(self.data) and pos - start < 10:
            b = self.data[pos]; pos += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result, pos
            shift += 7
        raise FleeceError('truncated varint at %d' % start)

    def _deref(self, pos: int, wide: bool) -> int:
        """Resolve a pointer at pos to the position of its target."""
        d = self.data
        if d[pos] & 0x40:
            raise FleeceError('external pointer not supported')
        if wide:
            if pos + 4 > len(d): raise FleeceError('truncated wide pointer')
            off = (struct.unpack_from('>I', d, pos)[0] & ~0xC0000000) << 1
        else:
            off = (struct.unpack_from('>H', d, pos)[0] & ~0xC000) << 1
        if off == 0 or pos - off < 0:
            raise FleeceError('bad pointer offset at %d' % pos)
        return pos - off

    # -- public entry points ------------------------------------------------

    def root(self):
        d = self.data
        if len(d) < 2 or len(d) % 2:
            raise FleeceError('bad document length %d' % len(d))
        # Spec: the value two bytes from the end is the root; if it is a
        # pointer, dereference narrow; if that is still a pointer, deref wide.
        pos = len(d) - 2
        if d[pos] >> 4 >= 8:
            pos = self._deref(pos, False)
            if d[pos] >> 4 >= 8:
                pos = self._deref(pos, True)
        if d[pos] >> 4 >= 8:
            raise FleeceError('root did not resolve')
        return self.value(pos, False)

    def value(self, pos: int, wide: bool):
        d = self.data
        if pos < 0 or pos + 2 > len(d):
            raise FleeceError('value out of range at %d' % pos)
        b0 = d[pos]; tag = b0 >> 4; tiny = b0 & 0x0F

        if tag >= 8:  # pointer, width given by containing collection
            return self.value(self._deref(pos, wide), wide)

        if tag == TAG_SHORT_INT:
            v = ((b0 << 8) | d[pos + 1]) & 0x0FFF
            return v - 0x1000 if v >= 0x800 else v

        if tag == TAG_INT:
            count = (tiny & 0x07) + 1
            raw = d[pos + 1: pos + 1 + count]
            if len(raw) < count: raise FleeceError('truncated int')
            u = int.from_bytes(raw, 'little')
            if tiny & 0x08:
                return u                      # unsigned
            if raw[-1] & 0x80:
                u -= 1 << (8 * count)         # sign-extend
            return u

        if tag == TAG_FLOAT:
            size = 8 if b0 & 0x08 else 4
            raw = d[pos + 2: pos + 2 + size]
            if len(raw) < size: raise FleeceError('truncated float')
            return struct.unpack('<d' if size == 8 else '<f', raw)[0]

        if tag == TAG_SPECIAL:
            # Reference enum: null=0x00, false=0x04, true=0x08, undefined=0x0C
            if tiny == 0x00: return None
            if tiny == 0x04: return False
            if tiny == 0x08: return True
            if tiny == 0x0C:
                raise FleeceError('undefined value at %d' % pos)
            raise FleeceError('bad special value 0x%02x at %d' % (b0, pos))

        if tag in (TAG_STRING, TAG_BINARY):
            if tiny == 0x0F:
                length, p = self._uvarint(pos + 1)
            else:
                length, p = tiny, pos + 1
            raw = d[p: p + length]
            if len(raw) < length: raise FleeceError('truncated string at %d' % pos)
            if tag == TAG_STRING:
                return raw.decode('utf-8')
            return base64.b64encode(bytes(raw)).decode('ascii')

        if tag == TAG_ARRAY:
            return self._collection(pos, False)
        if tag == TAG_DICT:
            return self._collection(pos, True)

        raise FleeceError('unknown tag %d at %d' % (tag, pos))

    def _collection(self, pos: int, is_dict: bool):
        d = self.data; b0 = d[pos]
        wide = bool(b0 & 0x08)
        count = ((b0 << 8) | d[pos + 1]) & 0x07FF
        items_at = pos + 2
        if count == 0x07FF:
            extra, p = self._uvarint(pos + 2)
            p += (p - (pos + 2)) & 1          # pad varint to 2-byte alignment
            count += extra
            items_at = p
        width = 4 if wide else 2

        if not is_dict:
            items = []
            end = items_at + count * width
            if end > len(d): raise FleeceError('truncated array at %d' % pos)
            for i in range(count):
                ip = items_at + i * width
                # Slots are either pointers (tag >= 8) or inline values
                # (e.g. small ints) which are already at the slot position.
                vp = self._deref(ip, wide) if d[ip] >> 4 >= 8 else ip
                items.append(self.value(vp, wide))
            return items

        result = {}
        parent = None
        deleted = set()
        end = items_at + count * 2 * width
        if end > len(d): raise FleeceError('truncated dict at %d' % pos)
        for i in range(count):
            base = items_at + i * 2 * width
            kpos = self._deref(base, wide) if d[base] >> 4 >= 8 else base
            vpos = self._deref(base + width, wide) if d[base + width] >> 4 >= 8 else base + width
            kb0 = d[kpos]
            if kb0 >> 4 == TAG_SHORT_INT and ((kb0 << 8) | d[kpos + 1]) & 0x0FFF == 0x800:
                parent = self.value(vpos, wide)   # magic -2048: inherited dict
                continue
            key = self.value(kpos, wide)
            if isinstance(key, int) and isinstance(self.shared, dict):
                if key not in self.shared:
                    raise FleeceError('unknown shared key at %d' % kpos)
                key = self.shared[key]
            elif isinstance(key, bytes):
                key = key.decode('utf-8', 'replace')
            vb0 = d[vpos]
            if vb0 == 0x3C:                     # special/undefined = deleted key
                deleted.add(key)
                continue
            result[key] = self.value(vpos, wide)
        if parent is not None:
            if not isinstance(parent, dict):
                raise FleeceError('dict parent is not a dict')
            merged = dict(parent)
            for key in deleted:
                merged.pop(key, None)
            merged.update(result)
            return merged
        return result

def shared_keys_from_state(state: bytes):
    """Decode a Couchbase SharedKeys state blob: a Fleece array of strings."""
    arr = decode(state)
    if not isinstance(arr, list):
        raise FleeceError('shared keys state is not an array')
    mapping = {}
    for i, key in enumerate(arr):
        if not isinstance(key, str):
            raise FleeceError('non-string shared key at %d' % i)
        mapping[i] = key
    return mapping

def decode(data: bytes, shared=None):
    """Decode a Fleece document to Python values."""
    return _Decoder(data, shared).root()
