# Build only from the allowlisted source stage produced by build_release.py.
from pathlib import Path
base = Path(SPECPATH)
a = Analysis([str(base / 'launcher.py')], pathex=[str(base)],
             binaries=[], datas=[(str(base / item), '.') for item in
             ('viewer.html', 'viewer.js', 'viewer.css')],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['pytest', 'numpy', 'pandas', 'matplotlib', 'IPython'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PiecesRescue',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, hide_console='hide-early', disable_windowed_traceback=False,
          target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PiecesRescue')
