# Archive format

The preservation layer is `preserved/`. Keep it even if you delete the viewer's
indexes. All paths inside receipts are relative to their containing archive;
checksums use SHA-256. All text files use UTF-8. Store each selected Pieces store
in its own archive. The app never merges production, staging or historical stores.

`recovery.json` uses `pieces-recovery-v1`. `status` is in-progress, cancelled,
failed or complete. `stage` identifies preservation, recovery, verification or
viewer preparation. `preservation: complete` means the database snapshot and
recognized auxiliary files were copied and source stability checks passed.
`files` records their paths, bytes and SHA-256 hashes. This private receipt also
contains the original source path. Do not share it as a diagnostic report.

`preserved/snapshot.sqlite3` is a SQLite backup, including committed database WAL
content. It includes account/credential collections. It retains Fleece bodies and
the `kv_info.SharedKeys` mapping required to interpret integer dictionary keys.
Generic SQLite integrity checks may encounter Couchbase's custom tokenizer; this
tool checks its own ordinary SQLite derivative, not those unavailable extensions.

`preserved/auxiliary` retains files from vector_db, Formats and Couchbase
Attachments, including vector WAL files. Lock and shared-memory files are omitted.
Pieces must be closed. These bytes are preserved for future tools; the viewer
does not promise attachment rendering or semantic vector search.

`export/manifest.json` uses `pieces-rescue-v2`. It records the snapshot identity,
export options, excluded collection counts, and each completed collection's
expected/exported/indexed/decode-error counts, raw path, byte size and SHA-256.
Statuses: in-progress, cancelled, failed, incomplete, test-limited, complete.
Complete applies only to selected collections in this source. Decode failures
preserve the encoded body and make the export incomplete with a failing exit code.
Immutable reads that omit WAL are never complete. Legacy v1 exports are readable
but cannot be resumed by v2; make a new export from their source instead.

Each raw JSONL line contains collection, id, sequence, flags, expiration,
version_b64, body_b64 and extra_b64. Successfully decoded documents add document;
malformed bodies add decode_error. `body_b64` remains the original binary source.
All live rows in selected collections are exported, including empty collections
in the receipt. Raw records are not a replacement for the preserved SQLite file.

One collection is one recovery checkpoint. The exporter writes `.jsonl.partial`
and a SQLite transaction, commits the index, renames the raw file, then publishes
the receipt using atomic replacement. A checkpoint is trusted only after receipt
publication. On retry, files and source/options are checked, then any unrecorded
collection is removed from the derivative index and replayed. OS locks prevent
two cooperating recovery/viewer instances from writing the same archive. A killed
process releases its OS lock even if the lock file remains.

`knowledge.sqlite` contains nodes, edges, FTS5 search and collection counts. It
also gains date indexes for the viewer. `atlas.sqlite` assembles summary and
conversation text and adds day/week/tag/title-group indexes. Both are derivatives.
Keep raw files and the preserved snapshot; changing a derivative does not change
the original source. Chart dates use UTC. Suggested subjects are title heuristics.

Verification detects accidental changes relative to the receipt. Receipts are
not digitally signed and do not establish authorship or protect against someone
who changes both data and receipt. Archives are plaintext and contain secrets.
