Pieces Rescue can now turn a saved recovery archive into portable Markdown notes.
Open `index.md` in your editor, or open the notes folder as an Obsidian vault.
The links stay relative, so the folder can move with you.

## What changed

- **Export Markdown** is available in the launcher and the packaged command line.
  It includes reconstructed summaries and conversations, separate profile
  histories, people, tags, sources, websites and linked annotations.
- Profile reports no longer get folded into summary narrative. Summary text
  can also be recovered from attachments recorded only on the annotation side.
- Notes have readable filenames, exact source identities, paged indexes and
  recorded relationships in both directions. Missing targets and the 60-entry
  display limit per direction are reported.
- Generated links are checked before completion. Source HTML, link/image syntax
  and code delimiters display as text, with headings and emphasis retained.
  Existing destinations are never overwritten; interrupted attempts keep their
  partial files and an unfinished receipt.

These changes follow a [review of Tsavo's exporter](https://github.com/anthony-maio/pieces-rescue/blob/v0.2.0-beta.1/docs/upstream-review-2026-10-18.md).
Recovery still works offline from the saved local store.

## Download and use

Download `pieces-rescue-0.2.0-beta.1-windows-x64.zip` and extract the entire ZIP.
Keep `_internal` beside `PiecesRescue.exe`. Python installation is not needed.
The source ZIP and `SHA256SUMS.txt` are also attached.

For an existing archive, choose **Open / retry saved archive**, then
**Export Markdown**. Choose a private parent folder. A new notes folder is
created there. You do not need another recovery from Pieces.

```powershell
.\PiecesRescue.exe --cli markdown "C:\MyArchive" "C:\MyNotes"
```

The older `render.py --format markdown` command now uses the same exporter and
requires `--output NEW_NOTES_FOLDER`. Markdown does not accept `--limit`.

## Checked for this release

- All 53 synthetic tests passed against the exact staged release sources.
- The extracted Windows executable recovered and verified an invented store,
  exported six notes, preserved the five checked source/receipt hashes, and
  refused an existing destination with Python removed from PATH.
- All 28 generated links in that packaged-app fixture resolved inside the notes
  folder. The portable tests also check links after moving an export.
- The source launcher's open-archive-to-Markdown flow passed. Independent
  Markdown parsing checked 900 adversarial list/fence combinations.
- Source and Windows ZIP contents, source inventory hashes and publication
  contents were reviewed for unintended private data.

## Beta limits

This remains an unsigned Windows x64 beta. Clean-machine Windows acceptance,
independent customer recovery, native Obsidian application acceptance and
large-archive Markdown performance remain unverified. macOS, Linux and Windows
ARM are not validated targets.

Stop waits for summary preparation if that stage is already running. Retry a
stopped Markdown export into a new folder. Notes are a selected reading view,
not a replacement for the preserved database and raw export. They can contain
private text and secrets; no automatic redaction or encryption is provided.
