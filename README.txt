Pieces Rescue 0.2.0-beta.1

Save your local Pieces memories and explore them without a Pieces account,
a running Pieces service, or a hosted backend. Everything runs on your computer.

Public beta target: Windows x64. The Windows ZIP includes Python and its runtime;
you do not need to install Python. Source use requires Python 3.10+ with SQLite
FTS5 and Tk for the desktop launcher. macOS and Linux are not validated beta
targets yet. See BETA_NOTES.md for the exact evidence and limits.

Start here

1. Extract the entire Windows ZIP into a new folder. Keep _internal beside
   PiecesRescue.exe, then open PiecesRescue.exe. Do not run it inside the ZIP.
2. Quit Pieces OS and Pieces for Developers, including their tray/menu apps.
   Keep their existing data folders. Do not uninstall or clear their data first.
3. Select your Pieces database. Find installed stores searches known locations;
   Browse can select db.sqlite3 or a saved SQLite snapshot. If several stores
   appear, check the full path and recover each into its own destination.
4. Choose a private local destination with enough free space. The app checks a
   conservative estimate of 8 times the database/WAL size, plus auxiliary files
   and 1 GiB. Actual space varies with captured text and indexes. A large archive
   can take a while; progress identifies the current collection or stage.
5. Click Save my memories. The app saves a SQLite snapshot, copies supporting
   files when available, recovers readable records, verifies checksums and counts,
   and prepares the visual overview. Open overview when it is ready.
6. Keep the launcher open while reading. Closing it stops the local viewer.
   To read again, use Open / retry saved archive and select your archive folder.

Your source is opened read-only. A SQLite backup includes committed WAL content.
The launcher requires Pieces to be closed for supporting-file consistency and
checks for running Pieces processes on Windows. It never kills Pieces for you.
If source files change during preservation, the attempt is marked failed and
its saved files remain available. Use a new destination after closing Pieces.

If a recovery stops

Keep the original source AND the destination. Open / retry saved archive,
select the same destination, and click Save my memories. Completed files are
checked before reuse. Completed export collections are retained; the unfinished
collection is replayed from the saved snapshot. A hard process exit can leave an
in-progress receipt; it is not a success receipt. Close another viewer/recovery
using the archive before retrying. A failed viewer build leaves the source copy
and exported files intact. A changed or damaged completed file is rejected,
not silently replaced. See SUPPORT.md for troubleshooting.

What is saved

  recovery.json                  Overall progress, source identity and checksums
  preserved/snapshot.sqlite3     Source database with committed WAL included
  preserved/auxiliary/           Attachments, Formats, vector_db when present
  export/manifest.json           Collection counts, exclusions, decode status
  export/raw/*.jsonl             Original encoded bodies and decoded documents
  export/knowledge.sqlite        Searchable records and recorded references
  export/atlas.sqlite            Rebuildable summaries, conversations and charts

The source snapshot contains ALL database collections, including account and
credential records. Account/credential collections are excluded from the readable
export by default, but ordinary memories can also contain secrets and other
people's content. The archive is NOT encrypted. Store it in a private user folder
on an encrypted drive. New archives get private account permissions; the Windows
launcher requires a filesystem that supports Windows ACLs (normally NTFS). Shared drives and cloud-synced folders may expose it.
No uploads, analytics or automatic updates are included. Do not publish archives.
Only application source and the built app belong in a public release.

The preservation scope is the selected database and recognized supporting files
from that Pieces folder. Other production/staging stores, historical backups,
and separate client caches are not merged. A standalone database copy has no
auxiliary files unless separately preserved. Copying vector files preserves them;
this app does not restore Pieces vector search or promise to restore the app.

Reading your archive

The overview shows sessions (summaries and conversations) by UTC day, recorded
summary tags by week, and suggested subjects from repeated title phrases. Click
any chart to browse its matching sessions, then open a full-width reader. Subject
lines mean shared sessions, not recorded project dependencies. Summary narratives
come from linked annotations; conversations include linked messages. Missing
references are reported. Original record shows the decoded source. References
shows at most 60 incoming and 60 outgoing UUID links per record.

Search is lexical word matching, not semantic search. Search -> All indexed
records includes captures and other record types outside the session charts.
Undated sessions do not appear in date charts. No captured HTML or script is
executed; following an external link is an explicit user action. The server binds
127.0.0.1 only. Other local apps with access to your account can read local data.

Portable Markdown notes

After recovery, click Export Markdown, or select an existing archive with
Open / retry saved archive first. Choose a private parent folder. The app writes
a new notes folder; start with index.md in a Markdown editor or open that folder
as an Obsidian vault. No plugins or Pieces service are needed. Keep the notes
folder together so relative links keep working after moving it.

The notes include reconstructed summaries and conversations, people, recorded
tags, sources, websites, reports and attached annotations. Profile reports stay
in separate notes instead of being repeated inside each summary. Recorded links
work in both directions. Missing targets and relationship display limits are
reported. The notes are a selected reading view, not a full database backup.
Keep preserved/ and export/raw/ for recovery and original records.

Source HTML, link/image syntax and code delimiters are rendered as text;
headings and emphasis remain readable. Generated navigation links point to
exported notes. Source text is not redacted and may contain
secrets. A completed notes export does not certify complete recovery. A stopped
notes export keeps its partial files; choose a new destination to run it again.
Stopping waits for summary preparation to finish if that stage is already running.

Advanced source use (no third-party runtime packages)

  python launcher.py
  python recovery.py discover
  python recovery.py recover SOURCE NEW_ARCHIVE --source-closed
  python recovery.py verify ARCHIVE
  python recovery.py diagnostics ARCHIVE
  python recovery.py markdown ARCHIVE NEW_NOTES_FOLDER
  python rescue.py serve ARCHIVE/export --port 8765

SOURCE can be a Pieces folder or its Couchbase db.sqlite3. On Windows the usual
store is under:
  %LOCALAPPDATA%/Mesh Intelligent Technologies, Inc/Pieces OS/com.pieces.os/
    production/Pieces/couchbase.cblite2/db.sqlite3

The Windows executable supports the same recovery commands with --cli:
  PiecesRescue.exe --cli recover SOURCE NEW_ARCHIVE --source-closed
  PiecesRescue.exe --cli verify ARCHIVE
  PiecesRescue.exe --cli markdown ARCHIVE NEW_NOTES_FOLDER
  PiecesRescue.exe --serve ARCHIVE/export 8765

Low-level export from an already preserved SQLite snapshot:
  python rescue.py export SNAPSHOT NEW_EXPORT --require-wal
  python rescue.py export SNAPSHOT SAME_EXPORT --require-wal --resume

Immutable fallback is refused unless --allow-wal-omission is explicitly supplied.
Such exports remain incomplete even if the WAL appears empty. --limit is for
testing only; a test-limited export is never a complete recovery. Standalone
snapshot and auxiliary.py commands are advanced tools; use recovery.py or the
launcher for the integrated preservation and verification flow.

Verification and support

Complete export means the selected collections were exported and decoded with
matching counts. Verified means the saved files still match their SHA-256 receipt
and indexed counts match the export. Neither proves that every past memory was
on this computer, or that this tool understands every Pieces version. Keep the
source snapshot for future readers. FORMAT.md documents the durable files.

Copy safe diagnostics produces only version/platform/status and counts. Nothing
is sent automatically. Share those counts and a description of the failed step
with the person who provided the beta. Do not send raw memories, databases,
recovery.json, manifests, or screenshots of private content in public reports.

Development

  python -m unittest discover -v
  node --check viewer.js
  python -m pip install -r requirements-build.txt
  python build_release.py NEW_BUILD_FOLDER --windows

The builder stages an explicit allowlist, runs all portable tests there, and
produces source/Windows ZIPs with SHA256SUMS.txt. The Windows build is unsigned;
Windows may show an unknown-publisher warning. This beta has no installer, admin
requirement, background service or auto-update channel. Use an approved download
source; security software may require review before an unsigned app runs.

MIT license. Maintainer: Anthony Maio. See LICENSE and THIRD_PARTY.txt.
