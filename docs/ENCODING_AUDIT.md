# Encoding Audit / 编码可读性审计

Date: 2026-05-20

## Scope

This audit covers the retained source and documentation paths requested for P3 #18:

- `README.md`
- `docs`
- `frontend/src`
- `backend/app`

The cleanup boundary is intentionally narrow. Backend business logic, plugin code, evaluation code, research code, and technical-analysis implementation files were not changed by this pass.

## UTF-8 Convention

All new source and documentation files in this repository should be saved as UTF-8. Do not rely on the Windows PowerShell default text reader for Chinese text inspection unless `-Encoding UTF8` is provided; otherwise valid UTF-8 files can appear as mojibake in terminal output.

Recommended inspection commands:

```powershell
rg -n -U "�|Ã|Â|â€|乣|銆|锛|鑷|绾|鏄" docs frontend/src backend/app
```

After this audit file exists, use the clean rerun form to avoid self-referential hits from the command examples:

```powershell
rg -n -U "�|Ã|Â|â€|乣|銆|锛|鑷|绾|鏄" docs frontend/src backend/app --glob '!docs/ENCODING_AUDIT.md'
```

```powershell
$utf8Strict = New-Object System.Text.UTF8Encoding($false,$true)
Get-ChildItem -Recurse -File docs,frontend\src,backend\app | ForEach-Object {
  try {
    [void]$utf8Strict.GetString([System.IO.File]::ReadAllBytes($_.FullName))
  } catch {
    $_.FullName
  }
}
```

For task references that intentionally mention encoding issues, include the task words in a separate scan so they do not hide real mojibake hits:

```powershell
rg -n -U "mojibake|乱码|�|Ã|Â|â€|乣|銆|锛|鑷|绾|鏄" docs frontend/src backend/app
```

## Current Result

- Strict UTF-8 decoding found no invalid files under `README.md`, `docs`, `frontend/src`, or `backend/app`.
- The high-confidence mojibake pattern scan found no live mojibake strings in `frontend/src` or `backend/app`.
- No retained live-development document should rely on the removed `docs/OPEN_DEVELOPMENT_BACKLOG.md` for encoding audit context.
- No frontend user-visible strings were changed in this pass.

## 2026-05-31 Regression Guard

- `backend/tests/test_repo_hygiene.py` now runs the retained-text UTF-8 and mojibake sentinel scan as part of the default backend guardrail suite.
- The executable scan covers `README.md`, `docs`, `frontend/src`, and `backend/app`, excluding this audit file's command examples, the generated module interaction review log, backend runtime storage, and Python caches.
- Latest validation: `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-encoding` passed with 5 tests, and the default `npm.cmd run test:backend` suite passed with 295 tests.

## 2026-05-31 README Guard Update

- `README.md` is now included in the executable retained-text UTF-8 and mojibake sentinel scan.
- Latest validation: `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-readme-encoding` passed with 5 tests.

## Retained History

Historical development logs and audit notes may contain references to previous encoding issues. Those records should be preserved unless the visible text is still unreadable in a current retained document header, checklist, contract, guide, or UI-facing page. Do not mass-rewrite old development-log entries solely to remove historical mojibake audit context.

## Browser-Visible Check Scope

If a future pass changes frontend strings, mainline should run the normal frontend verification and inspect these currently relevant UI surfaces in the browser:

- `/signalops` for SignalOps Chinese labels, condition/status badges, runtime status cards, and simulated portfolio text.
- `/dvg` for DVG source-note and gate explanation text.
- `/research-lab` for Research Lab metric cards, loop details, feedback labels, and linked-project wording.
- Dashboard / final output views if conclusion, probability, or provenance strings are edited.

Recommended handoff command for changed frontend strings:

```powershell
npm.cmd run build
```

Then perform browser checks against the active Vite URL used by the mainline worker.

## Remaining Risk

- `backend/app` was scanned for encoding risks only. No backend behavior was changed.
- Windows terminal output can still display valid UTF-8 Chinese incorrectly if read without explicit UTF-8 handling.
