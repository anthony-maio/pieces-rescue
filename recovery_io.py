"""Local, durable recovery primitives. No captured text in diagnostics."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


class Cancelled(Exception):
    pass


def check_cancel(cancel=None):
    if cancel and cancel():
        raise Cancelled('Stopped. Run again with the same destination to retry.')


def sha256(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            check_cancel(cancel)
            digest.update(block)
    return digest.hexdigest()


def replace_file(source, destination):
    # Windows scanners/readers can briefly deny delete sharing during a rename.
    # Keep the previous checkpoint intact while retrying the atomic replacement.
    for attempt in range(8):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(0.025 * 2 ** attempt, 0.5))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    replace_file(temporary, path)


def child(root, relative):
    """Reject paths that could escape a receipt's archive directory."""
    root = Path(root).resolve()
    relative = Path(relative)
    result = (root / relative).resolve()
    if relative.is_absolute() or result == root or root not in result.parents:
        raise ValueError('Archive path is outside its destination')
    return result


def private_directory(path):
    """Restrict a new archive directory before any captured data is written."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        path.chmod(0o700)
        return
    options = {'capture_output': True, 'creationflags': subprocess.CREATE_NO_WINDOW, 'timeout': 15}
    user = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], **options)
    sid = re.search(rb'S-1-5-[0-9-]+', user.stdout)
    if user.returncode or not sid:
        raise PermissionError('Cannot identify your Windows account to protect this archive.')
    grant = '*' + sid.group().decode('ascii') + ':(OI)(CI)F'
    result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', grant,
                             '*S-1-5-18:(OI)(CI)F'], **options)
    if result.returncode:
        raise PermissionError('Cannot set private permissions here. Choose a local NTFS folder owned by your account.')


@contextmanager
def exclusive(root, name='.rescue.lock'):
    """OS lock releases on exit or process termination; file may remain."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = (root / name).open('a+b')
    try:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('This archive is already open in another recovery or viewer. Close it and retry.') from error
        yield
    finally:
        handle.close()
