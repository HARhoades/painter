# Painter refactor: status and decisions

Companion to `painter-code-review-and-architecture.md`. Last updated 12 Nov 2026.

## Decisions

- **Target:** a local machine, used by one person at a time. No hosted service.
- **GUI:** a Python UI. Working assumption is a desktop app (PySide6) as recommended in the review; to be confirmed before phase 5.
- **Repository:** https://github.com/HARhoades/painter. Work is on branch `refactor/package-split`.

## Status

| Phase | State | Notes |
|---|---|---|
| Sync | Done | GitHub `master` held an older 2,332-line script. The 4,435-line working copy is the first commit on the branch. |
| 0. Safety net | Done | `pyproject.toml`, `.gitignore` additions (including the signed-in browser profile), 86 tests using a fake Canvas (no network). |
| 1. Mechanical split | Done | Code moved verbatim into `painter/{canvas,domain,qti,storage,services,cli}`. `canvas_fetch_submissions.py` is a shim. |
| 2. Bug fixes | Not started | Findings 1-4 and 8 first. Finding 2 already has a failing (xfail) test. |
| 3. Decouple from CLI | Not started | The step the GUI depends on. |
| 4. Consolidate duplicates | Not started | |
| 5. GUI | Not started | |

## How phase 1 was checked

- The phase 0 tests passed unmodified before and after the split.
- 48 CLI scenarios were run against the single-file version and the package; exit code, stdout, stderr, API calls and output files were identical.
- All 3,662 code lines of the original are present in the package. The only additions are import lines and the `run_download()` wrapper around the download half of `main()`.

## Known gaps

- Test coverage is 72% overall. Lowest: `quiz_uploads.py` 12% (the Playwright browser flow is untested), `quiz_export.py` 58% (course-export path), `qti/builder.py` 61% (matching and fill-in-the-blank converters).
- Nothing has been run against a real Canvas instance since the split.
- The branch has not been pushed: the session has read-only access to the repository until a GitHub account is linked.
- Deviation from the proposed layout: `domain/selection.py`, `storage/tabular.py`, `events.py` and `errors.py` do not exist yet (they are new code, phases 3-4). `services/quiz_plan.py` and `domain/assignments.py` were added to avoid a circular import between quiz export and quiz uploads.
