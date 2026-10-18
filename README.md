# Pieces Rescue

Save your local Pieces memories and find your way back through them. Pieces
Rescue preserves a selected local store, verifies the saved files, and opens a
visual overview with click-through reading. Everything runs on your computer.

**[Download the Windows x64 beta](https://github.com/anthony-maio/pieces-rescue/releases/tag/v0.1.0-beta.1)**

This is an unsigned, opt-in beta. Clean-machine Windows testing and independent
customer recovery testing remain open. Keep your original Pieces data.

## Start here

1. Download `pieces-rescue-0.1.0-beta.1-windows-x64.zip` from the release above.
   Download `SHA256SUMS.txt` if you want to verify its SHA-256 checksum.
2. Extract the entire ZIP. Keep `_internal` beside `PiecesRescue.exe`.
   The app bundles its runtime; you do not need to install Python.
3. Quit Pieces OS and Pieces for Developers, including their tray apps.
   Keep their data folders and do not uninstall or clear data first.
4. Open `PiecesRescue.exe`, choose your Pieces database and a private local
   destination, then click **Save my memories**.
5. Open the overview when recovery and verification finish. Choose a day or
   topic, then open the memories behind it. Keep the launcher open while reading.

The archive is plaintext and can contain secrets. Its preserved database includes
account records. Keep it private. Public issues should contain only safe diagnostic
counts and a description of the failed step, never databases, manifests, memory
text, or screenshots of private content.

## What you get

- A source database snapshot with committed WAL content and supporting files
  when available.
- Raw exported records, checksum receipts, interruption/retry support and safe
  diagnostics.
- A calendar, recorded-tag heatmaps, detected subject groups, search and a full
  reader for recovered summaries and conversations.
- Local reading without a Pieces account, a running Pieces service, telemetry
  or a hosted backend.

The overview counts summaries and conversations, rather than every captured
event. Detected subjects use title heuristics. Missing references stay visible.
The tool cannot recover history that is absent from the selected store.

## Watch the demo

[![Pieces Rescue demo](https://github.com/anthony-maio/pieces-rescue/releases/download/v0.1.0-beta.1/brag.jpg)](https://github.com/anthony-maio/pieces-rescue/releases/download/v0.1.0-beta.1/brag.mp4)

The 22-second video uses invented sample memories.

## Documentation and support

- [Full instructions](README.txt)
- [Beta scope and validation limits](BETA_NOTES.md)
- [Troubleshooting and safe diagnostics](SUPPORT.md)
- [Archive format](FORMAT.md)
- [Report a problem](https://github.com/anthony-maio/pieces-rescue/issues)

Windows x64 is the beta target. macOS, Linux and Windows ARM remain unverified.
The current evidence comes from one Windows development machine and one user's
source data. Independent recovery evidence and a signed distribution channel
are needed before a stable release.

## Development

Source use requires Python 3.10+ with SQLite FTS5, plus Tk for the launcher.
The packaged Windows build uses Python 3.14.

```text
python -m unittest discover -v
node --check viewer.js
python launcher.py
```

To build a new Windows package on Windows:

```text
python -m pip install -r requirements-build.txt
python build_release.py NEW_BUILD_FOLDER --windows
```

The builder uses an explicit source allowlist. Keep personal archives outside
the repository; never add them to Git or attach them to a public issue.
`SOURCE_SHA256.json` records the source files in the original beta package.

MIT license. Maintainer: Anthony Maio. See [LICENSE](LICENSE) and
[THIRD_PARTY.txt](THIRD_PARTY.txt).
