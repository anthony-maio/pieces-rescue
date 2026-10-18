"""Create source and Windows beta archives from a strict source allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from release import VERSION

FILES = (
    'release.py', 'recovery_io.py', 'recovery.py', 'launcher.py', 'rescue.py',
    'purefleece.py', 'auxiliary.py', 'atlas.py', 'viewer.py', 'prepare_viewer.py',
    'render.py', 'portable.py', 'viewer.html', 'viewer.js', 'viewer.css', 'README.txt', 'LICENSE',
    'THIRD_PARTY.txt', 'BETA_NOTES.md', 'SUPPORT.md', 'FORMAT.md',
    'requirements-build.txt', 'PiecesRescue.spec', 'build_release.py',
    'synthetic_store.py', 'test_rescue.py', 'test_viewer.py', 'test_atlas.py',
    'test_recovery.py', 'test_release.py', 'test_portable.py', '.gitignore',
)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def pack(folder, destination):
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path, folder.name + '/' + path.relative_to(folder).as_posix())


def build(output, windows=False):
    source = Path(__file__).resolve().parent
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new build folder; previous artifacts are kept.')
    output.mkdir(parents=True, exist_ok=True)
    stage = output / ('pieces-rescue-' + VERSION + '-source')
    stage.mkdir()
    for name in FILES:
        origin = source / name
        if origin.is_symlink() or not origin.is_file():
            raise ValueError('Missing or linked release source: ' + name)
        shutil.copyfile(origin, stage / name)
    inventory = {name: digest(stage / name) for name in FILES}
    (stage / 'SOURCE_SHA256.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
    # Test the actual staged sources with no access to personal fixture files.
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v'], cwd=stage, check=True)
    source_zip = output / (stage.name + '.zip')
    pack(stage, source_zip)
    artifacts = [source_zip]
    if windows:
        if sys.platform != 'win32':
            raise RuntimeError('Build Windows binaries on Windows.')
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                        '--distpath', str(output / 'binary'), '--workpath', str(output / 'work'),
                        str(stage / 'PiecesRescue.spec')], cwd=stage, check=True)
        bundle = output / 'binary/PiecesRescue'
        for name in ('README.txt', 'LICENSE', 'THIRD_PARTY.txt', 'BETA_NOTES.md', 'SUPPORT.md', 'FORMAT.md'):
            shutil.copyfile(stage / name, bundle / name)
        licenses = bundle / 'licenses'
        licenses.mkdir()
        base = Path(sys.base_prefix)
        required = {'Python-and-bundled-libraries.txt': base / 'LICENSE.txt',
                    'Tk.txt': base / 'tcl/tk8.6/license.terms'}
        import importlib.metadata
        dist = importlib.metadata.distribution('pyinstaller')
        license_file = next(p for p in dist.files if p.name == 'COPYING.txt')
        required['PyInstaller.txt'] = Path(dist.locate_file(license_file))
        for name, path in required.items():
            if not path.is_file():
                raise FileNotFoundError('Runtime license not found: ' + str(path))
            shutil.copyfile(path, licenses / name)
        (licenses / 'SQLite.txt').write_text('SQLite is in the public domain. https://www.sqlite.org/copyright.html\n', encoding='utf-8')
        binary_zip = output / ('pieces-rescue-' + VERSION + '-windows-x64.zip')
        pack(bundle, binary_zip)
        artifacts.append(binary_zip)
    (output / 'SHA256SUMS.txt').write_text(''.join(digest(path) + '  ' + path.name + '\n' for path in artifacts), encoding='ascii')
    print('Release artifacts:', *[str(path) for path in artifacts], sep='\n')
    return artifacts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    parser.add_argument('--windows', action='store_true')
    args = parser.parse_args()
    build(args.output, args.windows)
