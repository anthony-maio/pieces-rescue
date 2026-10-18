"""Preserve, recover, verify and prepare a local Pieces archive."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import rescue
from auxiliary import CATEGORIES
from recovery_io import Cancelled, check_cancel, child, exclusive, private_directory, replace_file, sha256, write_json
from release import VERSION


def discover():
    """Bounded discovery under known application roots; never scan a whole disk."""
    home = Path.home()
    bases = [Path(os.environ.get('LOCALAPPDATA', home / 'AppData/Local')) / 'Mesh Intelligent Technologies, Inc',
             home / 'Library' / 'Application Support' / 'com.pieces.os',
             home / 'Library' / 'com.pieces.os',
             home / '.local/share' / 'com.pieces.os']
    found = []
    for base in bases:
        if not base.is_dir():
            continue
        for parent, dirs, names in os.walk(base):
            depth = len(Path(parent).relative_to(base).parts)
            dirs[:] = [d for d in dirs if depth < 6 and d not in {'vector_db', 'Attachments', 'Formats'}
                       and not Path(parent, d).is_symlink()]
            if 'db.sqlite3' in names and Path(parent).name == 'couchbase.cblite2':
                found.append(str(Path(parent, 'db.sqlite3').resolve()))
    return sorted(set(found))


def fingerprint(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def wal_fingerprint(path):
    # A read-only SQLite connection can create an empty WAL/SHM pair. No
    # committed data was added in that case; a nonempty WAL is still monitored.
    if not path.exists():
        return None
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns] if stat.st_size else None


def source_files(source):
    """Collect auxiliary files with strict containment, retaining vector WALs."""
    if source.parent.name != 'couchbase.cblite2':
        return None, []
    root = source.parent.parent
    files = []
    for category in CATEGORIES:
        folder = root / category
        if not folder.exists():
            continue
        for parent, dirs, names in os.walk(folder, followlinks=False):
            if Path(parent).is_symlink() or root not in Path(parent).resolve().parents:
                raise ValueError('An auxiliary directory points outside the source. Preserve it separately.')
            if any(Path(parent, name).is_symlink() for name in dirs):
                raise ValueError('An auxiliary link needs separate preservation.')
            for name in names:
                path = Path(parent, name)
                if path.is_symlink() or root not in path.resolve().parents:
                    raise ValueError('An auxiliary link needs separate preservation.')
                if not path.is_file() or name.endswith(('-shm', '-lock', '.lock', '.lock_info')):
                    continue
                files.append(path)
    return root, sorted(files)


def estimate(source):
    source = rescue.locate(source)
    _, files = source_files(source)
    auxiliary_bytes = sum(p.stat().st_size for p in files)
    wal = Path(str(source) + '-wal')
    db_bytes = source.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
    # Snapshot + base64 JSONL + decoded text + indexes + temporary transactions.
    return {'database_bytes': db_bytes, 'auxiliary_bytes': auxiliary_bytes,
            'recommended_bytes': db_bytes * 8 + auxiliary_bytes + 1024 ** 3,
            'auxiliary_files': len(files), 'source': str(source)}


def check_space(output, required):
    parent = Path(output).resolve()
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free < required:
        raise OSError('Not enough free space. Choose a larger destination drive. The estimate includes temporary files.')


def verify_files(root, files, progress=lambda message: None, cancel=None):
    for number, item in enumerate(files, 1):
        check_cancel(cancel)
        progress('Verifying saved file %d / %d' % (number, len(files)))
        path = child(root, item['path'])
        if not path.is_file() or path.stat().st_size != item['bytes'] or sha256(path, cancel) != item['sha256']:
            raise ValueError('A saved file is missing or changed. Keep the archive and preserve a new copy.')


def preserve(source, root, receipt, progress, cancel):
    source = rescue.locate(source)
    source_root, files = source_files(source)
    if root == source.parent or (source_root and (root == source_root or source_root in root.parents)):
        raise ValueError('Choose a destination outside the Pieces source folder.')
    identity = {'path': str(source), 'stat': fingerprint(source)}
    wal = Path(str(source) + '-wal')
    identity['wal'] = wal_fingerprint(wal)
    if receipt.get('source_identity') and receipt['source_identity'] != identity:
        raise ValueError('Source changed since preservation started. Choose a new destination so both attempts are kept.')
    receipt['source_identity'] = identity
    check_space(root, estimate(source)['recommended_bytes'])
    receipt['stage'] = 'preserving'
    write_json(root / 'recovery.json', receipt)
    saved = root / 'preserved'
    saved.mkdir(exist_ok=True)
    database = saved / 'snapshot.sqlite3'
    before = {str(p): fingerprint(p) for p in files}
    if receipt.get('auxiliary_identity') is not None and receipt['auxiliary_identity'] != before:
        raise ValueError('Supporting files changed since preservation started. Use a new destination.')
    receipt['auxiliary_identity'] = before
    write_json(root / 'recovery.json', receipt)
    # A checkpointed snapshot is reusable only if already recorded and verified.
    known = {item['path']: item for item in receipt.get('files', [])}
    verify_files(root, list(known.values()), progress, cancel)
    if 'preserved/snapshot.sqlite3' not in known:
        database.unlink(missing_ok=True)
        rescue.snapshot(source, database, progress, cancel)
        item = {'path': 'preserved/snapshot.sqlite3', 'bytes': database.stat().st_size, 'sha256': sha256(database, cancel)}
        known[item['path']] = item
        receipt['files'] = list(known.values())
        write_json(root / 'recovery.json', receipt)
    for number, path in enumerate(files, 1):
        check_cancel(cancel)
        relative = 'preserved/auxiliary/' + path.relative_to(source_root).as_posix()
        if relative in known:
            continue
        progress('Preserving supporting files: %d / %d' % (number, len(files)))
        dest = child(root, relative)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_name(dest.name + '.partial')
        with path.open('rb') as inp, temporary.open('wb') as out:
            for block in iter(lambda: inp.read(4 * 1024 * 1024), b''):
                check_cancel(cancel)
                out.write(block)
            out.flush(); os.fsync(out.fileno())
        replace_file(temporary, dest)
        digest = sha256(dest, cancel)
        if fingerprint(path) != before[str(path)] or sha256(path, cancel) != digest:
            raise ValueError('Pieces files changed while copying. Close Pieces and preserve into a new destination.')
        known[relative] = {'path': relative, 'bytes': dest.stat().st_size, 'sha256': digest}
        receipt['files'] = list(known.values())
        write_json(root / 'recovery.json', receipt)
    _, after_files = source_files(source)
    current_wal = wal_fingerprint(wal)
    if (fingerprint(source) != identity['stat'] or current_wal != identity['wal']
            or before != {str(p): fingerprint(p) for p in after_files}):
        raise ValueError('Source changed during preservation. Close Pieces and use a new destination.')
    receipt['preservation'] = 'complete'
    receipt['scope'] = {'database': 'SQLite snapshot including committed WAL',
                        'auxiliary': list(CATEGORIES) if source_root else [],
                        'standalone_database': source_root is None,
                        'excludes': ['other stores and historical backups', 'client caches', 'lock files and shared-memory files']}
    write_json(root / 'recovery.json', receipt)


def verify(root, progress=lambda message: None, cancel=None):
    root = Path(root).resolve()
    if not (root / 'recovery.json').is_file():
        raise ValueError('Choose a saved recovery folder containing recovery.json.')
    with exclusive(root, '.recovery.lock'), exclusive(root / 'export'):
        return _verify(root, progress, cancel)


def _verify(root, progress, cancel):
    root = Path(root).resolve()
    receipt = json.loads((root / 'recovery.json').read_text(encoding='utf-8'))
    if receipt.get('preservation') != 'complete':
        raise ValueError('Preservation has not completed. Retry recovery first.')
    verify_files(root, receipt['files'], progress, cancel)
    export_root = root / 'export'
    manifest = json.loads((export_root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'complete':
        raise ValueError('The export is incomplete. Source files remain in preserved/.')
    snapshot = next((item for item in receipt['files'] if item['path'] == 'preserved/snapshot.sqlite3'), None)
    if not snapshot or manifest.get('identity', {}).get('sha256') != snapshot['sha256']:
        raise ValueError('Export identity does not match the preserved snapshot.')
    verify_files(export_root, [{'path': v['file'], 'bytes': v['bytes'], 'sha256': v['sha256']} for v in manifest['collections'].values()], progress, cancel)
    from atlas import connect
    with connect(export_root / 'knowledge.sqlite') as db:
        for name, item in manifest['collections'].items():
            check_cancel(cancel)
            actual = db.execute('select count(*) from nodes where source=?', (name,)).fetchone()[0]
            if actual != item['indexed'] or item['expected'] != item['exported'] or item['decode_errors']:
                raise ValueError('Collection counts do not match the export receipt.')
        if db.execute('pragma quick_check').fetchone()[0] != 'ok':
            raise ValueError('The search index failed its SQLite check.')
    return {'status': 'verified', 'files': len(receipt['files']) + len(manifest['collections']),
            'records': sum(v['exported'] for v in manifest['collections'].values()),
            'excluded_records': sum(v['records'] for v in manifest['excluded'].values())}


def recover(source, output, source_closed=False, progress=None, cancel=None):
    if not source_closed:
        raise ValueError('Quit Pieces OS and Pieces for Developers before preserving supporting files.')
    progress = progress or (lambda message: print(message, flush=True))
    root = Path(output).expanduser().resolve()
    if root.exists() and any(root.iterdir()) and not (root / 'recovery.json').is_file():
        raise FileExistsError('Choose an empty destination, or a folder with recovery.json to retry.')
    if not (root / 'recovery.json').exists():
        initial_source = rescue.locate(source)
        source_root, _ = source_files(initial_source)
        if source_root and (root == source_root or source_root in root.parents):
            raise ValueError('Choose a destination outside the Pieces source folder.')
        private_directory(root)
    with exclusive(root, '.recovery.lock'):
        receipt_path = root / 'recovery.json'
        receipt = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {
            'format': 'pieces-recovery-v1', 'version': VERSION, 'status': 'in-progress', 'preservation': 'pending', 'files': []}
        if receipt.get('format') != 'pieces-recovery-v1':
            raise ValueError('This recovery format is not supported by this version.')
        if receipt.get('source_identity'):
            requested = Path(source).expanduser().resolve()
            recorded = Path(receipt['source_identity']['path'])
            # Retain folder aliases even after the original store is unavailable.
            if requested != recorded and requested not in recorded.parents:
                raise ValueError('This destination belongs to a different source. Choose a new destination.')
        receipt['status'] = 'in-progress'
        receipt.pop('failure', None)
        write_json(receipt_path, receipt)
        try:
            if receipt['preservation'] != 'complete':
                preserve(source, root, receipt, progress, cancel)
            else:
                progress('Checking the preserved source before retrying')
                verify_files(root, receipt['files'], progress, cancel)
            check_cancel(cancel)
            receipt['stage'] = 'recovering'
            write_json(receipt_path, receipt)
            args = SimpleNamespace(source=root / 'preserved/snapshot.sqlite3', output=root / 'export', limit=0,
                                   include_secrets=False, require_wal=True, allow_wal_omission=False,
                                   fleece_library=None, resume=True)
            rescue.export(args, progress, cancel)
            receipt['stage'] = 'verifying'
            write_json(receipt_path, receipt)
            with exclusive(root / 'export'):
                receipt['verification'] = _verify(root, progress, cancel)
            check_cancel(cancel)
            receipt['stage'] = 'preparing-viewer'
            write_json(receipt_path, receipt)
            progress('Preparing the visual overview. Large archives can take several minutes.')
            from prepare_viewer import build
            with exclusive(root / 'export'):
                build(root / 'export', progress=progress)
            check_cancel(cancel)
            from atlas import connect
            with connect(root / 'export/atlas.sqlite') as db:
                receipt['reader'] = {'sessions': db.execute('select count(*) from sessions').fetchone()[0],
                                     'missing_references': db.execute('select coalesce(sum(missing_content),0) from sessions').fetchone()[0]}
            receipt['status'] = 'complete'
            receipt['stage'] = 'ready'
            write_json(receipt_path, receipt)
            progress('Ready. Your preserved source, readable export and verification receipt are saved.')
            return receipt
        except BaseException as error:
            receipt['status'] = 'cancelled' if isinstance(error, (Cancelled, KeyboardInterrupt)) else 'failed'
            receipt['failure'] = type(error).__name__
            try:
                write_json(receipt_path, receipt)
            except OSError:
                pass
            raise


def diagnostics(root):
    """Allowlist only counts and stage labels; never copy paths or error strings."""
    root = Path(root)
    receipt = json.loads((root / 'recovery.json').read_text(encoding='utf-8'))
    allowed_status = {'pending', 'in-progress', 'complete', 'failed', 'cancelled'}
    result = {'version': VERSION, 'platform': sys.platform,
              'status': receipt.get('status') if receipt.get('status') in allowed_status else 'unknown',
              'preserved_files': len(receipt.get('files', []))}
    manifest_path = root / 'export/manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        result['collections'] = len(manifest.get('collections', {}))
        for name, field in [('records', 'exported'), ('decode_errors', 'decode_errors')]:
            result[name] = sum(v.get(field, 0) for v in manifest.get('collections', {}).values() if isinstance(v.get(field, 0), int))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=VERSION)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('discover')
    item = sub.add_parser('recover')
    item.add_argument('source'); item.add_argument('output'); item.add_argument('--source-closed', action='store_true')
    for name in ('verify', 'diagnostics'):
        sub.add_parser(name).add_argument('output')
    args = parser.parse_args()
    try:
        if args.command == 'discover':
            print('\n'.join(discover()))
        elif args.command == 'recover':
            recover(args.source, args.output, args.source_closed)
        elif args.command == 'verify':
            print(json.dumps(verify(args.output), indent=2))
        else:
            print(json.dumps(diagnostics(args.output), indent=2))
    except (Cancelled, KeyboardInterrupt):
        print('Stopped. Keep the destination and retry the same recovery.', file=sys.stderr)
        return 130
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
