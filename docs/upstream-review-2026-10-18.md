# Export review, October 18, 2026

Reviewed [pieces-app/export-tool at 86bac28e](https://github.com/pieces-app/export-tool/tree/86bac28e62b561d5d6afbeef970c04f261d23c4b)
against Pieces Rescue's first beta. Tsavo's exporter has useful answers to a
problem our local reader did not fully solve: taking recovered text into another
editor while keeping its context and exact record identity.

## Adopted in 0.2.0-beta.1

- Portable Markdown with a start page, paged collection indexes, readable note
  names, identity metadata and relative links. The notes can be moved together
  or opened as an Obsidian vault. Source IDs remain in the record map.
- Separate profile reports. Upstream's `people.go` recognizes
  `HIERARCHICAL_PROFILE_SUMMARY` and `PROFILE_DESCRIPTION`. Our atlas previously
  inlined these alongside narrative annotations. It now leaves their text in
  separate source records and the notes exporter links the exact report versions.
- Reverse attachment recovery. An annotation's recorded `summaries` references
  can supply a summary's body even when its forward annotation list is absent.
  Content provenance records which side supplied the link. No canonical edges
  or source records are rewritten.
- Explicit navigation scope. Notes link only to files actually exported.
  Unavailable targets remain labels, relationship display limits are disclosed,
  and indexes paginate instead of silently dropping records.
- Conservative handling of source markup. Source link/image syntax, HTML and
  code delimiters remain readable text. Headings and emphasis are retained.
  Generated navigation connects the exported notes.
  This does not redact secrets or make an archive safe to publish.

The relevant upstream implementations are `render.go`, `people.go`,
`annotation_relationships.go`, `navigation.go`, `links.go` and
`obsidian_compact.go` under `internal/exporter`. Its readable-render and
navigation tests informed the acceptance cases: retain exact report versions,
include reverse-only attachments, avoid broken local links, and preserve links
when a folder moves. These are independent Python changes to our offline reader.
The upstream MIT notice is retained in THIRD_PARTY.txt.

## Deferred

Live Pieces API discovery, app process management, historical SDK-cache recovery,
identity consolidation, PDF output, automatic redaction and encrypted capture
checkpoints need different recovery guarantees and broader validation. They are
not included in this release. The review did not establish additional offline
database paths to add to automatic discovery.

The low-level `render.py --format markdown` now uses the same portable exporter
and requires `--output NEW_NOTES_FOLDER`. The launcher action and
`recovery.py markdown` expose that same reconstructed text and validated
navigation. This release does not claim parity with upstream's AST
Markdown processing or its complete export scope.

## Evidence limits

The upstream review inspected code and tests; its Go test suite was not run.
Our release is still an unsigned Windows x64 beta. Local synthetic tests and
packaged-app checks are reported in the release notes. Clean-Windows and
independent customer recovery acceptance remain open.
