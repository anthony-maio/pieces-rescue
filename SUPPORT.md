# Beta support

Maintainer: Anthony Maio. Report problems through the channel where you received
this beta. There is no hosted recovery service and no guaranteed response time.

Keep your original Pieces data folder. Preserve before uninstalling or clearing
application data. A readable chart is not proof that all historical records were
present on this computer. Do not discard the saved source when decoding fails.

| Problem | Next step |
| --- | --- |
| No stores found | Browse to couchbase.cblite2/db.sqlite3. The search is limited to known app folders; moved data and different layouts need manual selection. |
| Multiple stores | Check the full path. Recover each production/staging/historical store into a separate destination. |
| Pieces still running | Quit Pieces OS and Pieces for Developers from the tray/menu, then retry. The tool does not stop them for you. |
| Not enough space | Choose a larger private drive. Preserve the original source and existing attempt. Do not delete your only copy to make room. |
| Cancelled or power lost | Open / retry saved archive and select the same folder. Completed checkpoints are verified; the unfinished collection restarts. |
| Archive already open | Close its other viewer/recovery window and retry. A leftover lock file alone does not mean it is locked. |
| Source changed | Keep both attempts; close Pieces and use a new destination. Completed preservation can be reused even if the original source is later unavailable. |
| A saved file changed | Keep the damaged archive and original; use a new destination. The tool refuses to overwrite a checksum mismatch. |
| Some records did not decode | The encoded records and source snapshot remain available. Share safe diagnostic counts and the app version, not the data. A future decoder may recover them. |
| Overview failed to prepare | Retry the same recovery. The saved source and raw export are separate from the viewer. |
| Empty charts | Charts show dated summaries and conversations. Try Search -> All indexed records for other captures and undated content. |
| Markdown export stopped | Keep its partial folder and retry Export Markdown into a new destination. This does not require another recovery from Pieces. |
| Missing note or relationship | The notes include selected record kinds and bounded relationships. Check their manifest and the original archive; unavailable targets do not acquire invented files. |
| Profile text missing from a summary | Profile reports now have their own notes. Follow the recorded relationship to the exact report. The original annotation remains in the archive. |
| Unknown publisher | This beta executable is unsigned. Verify the download and its SHA-256 checksum. Follow your organization's software policy. |

For a report, include the beta version, Windows version, failed step, whether the
source was live or a saved copy, and the launcher's Copy safe diagnostics output.
That button copies version/platform/status and aggregate counts to your clipboard;
it sends nothing. Remove personal information from any additional explanation.

Do not post databases, raw JSONL, source or recovery manifests, captures, account
tokens, or screenshots containing memories. There is no archive upload button.
Do not put a data archive in a public source repository.
