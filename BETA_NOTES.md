# Pieces Rescue 0.2.0-beta.1

This beta preserves a selected local Pieces store and makes its recovered memories
readable after Pieces is no longer available. The Windows app bundles its runtime
and serves a local visual overview with click-through reading. It has no account,
cloud dependency, telemetry, installer, or automatic update service.

## Included

- A guided source/destination launcher with Windows store discovery, a running-app
  check, free-space estimate, progress, cancellation, retry and safe diagnostics.
- A SQLite snapshot including committed WAL, auxiliary file preservation, checksums
  and separate receipts for preservation, export and viewer preparation.
- Collection checkpoints that survive cancellation or a hard process exit. Retry
  verifies saved files, retains completed collections and replays unfinished work.
- Calendar, recorded-tag heatmaps, detected subject groups, full-text search,
  reconstructed summary/conversation reading and original-record access.
- MIT source distribution and an explicit file allowlist for release packaging.
- Portable Markdown notes from saved archives, with relative links, paged indexes,
  readable filenames and explicit missing-target counts. The launcher and the
  packaged command line both expose this export.
- Separate profile-report notes and summary reconstruction from attachments
  recorded on either the summary or annotation. No relationship is inferred
  from matching names or prose.

## Scope and limits

The tested beta target is Windows x64 on the development machine. This is not
evidence of a clean-machine installation or recovery across multiple customers'
Pieces versions. macOS, Linux and ARM builds are not validated beta targets.
The source uses Python 3.10+; the packaged Windows build uses Python 3.14.

Existing large production/staging archives from one user's installation were
used during viewer development. Portable tests use invented data. The release
checks cover WAL inclusion, decode failures, interruption/retry, corrupt saved
files, disk-space refusal, Unicode paths, HTTP restrictions and the reading flow.
Local package checks do not establish universal compatibility with Pieces stores.

The app is unsigned. It has no automatic crash reporting. Archives are plaintext
and contain private material; the preserved database includes account records.
Preserve into a private local folder and keep the original source. There is no
promise to recover deleted history, absent cloud content, every old store version,
or the running Pieces application itself.

Markdown exports require a new folder for each attempt. Source HTML, links,
images and code delimiters are displayed as text; headings and emphasis remain
readable. Some editors may automatically recognize plain URLs. Stop takes effect
after summary preparation if that stage is already running. Large-archive
Markdown performance and native Obsidian application acceptance remain unverified.

The overview counts summaries and conversations, not every captured event.
Date charts exclude undated sessions. Subject groups are title heuristics. Missing
references remain visible. Attachment/vector files are preserved as files rather
than reconstructed into their original application features.

A future stable release needs independent clean-Windows and volunteer recovery
evidence, broader version/platform coverage, and a signed distribution channel.
Use this beta with a retained source copy and report failures through the channel
where you received it. See SUPPORT.md and FORMAT.md.
