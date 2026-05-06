# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.5.0] - 2026-05-01

### Added

- **Multiple confusion matrices per experiment** — the Confusion Matrix tab now keeps a tab bar of named matrices. "+ New" adds another, double-click a tab to rename, "Duplicate" makes a copy, "Delete" drops one. Each matrix has its own classes, palette, and intensity, so you can keep e.g. "validation", "test", and "after threshold tuning" side-by-side on the same experiment
- **Compare confusion matrices** — once you have ≥2 matrices, a "Compare…" tab opens a side-by-side read-only view with two dropdowns (A and B) and a difference table for accuracy / macro & weighted precision-recall-F1 / total. Δ is colored green for B>A and red for B<A
- **Confusion matrix intensity slider** — new range control (0.3–1.5) in the matrix toolbar lets you lighten or darken the heatmap independently of the color palette, useful when high-count cells are saturating or low-count cells are too pale
- **Confusion matrices persist on the experiment** — matrices now save to the server (as a JSON-encoded manual param `_confusion_matrices`) so they survive across browsers and clean cache, and round-trip with the experiment record. Saves are debounced; legacy localStorage matrices are auto-migrated on first load. New endpoints `GET /api/confusion/<id>` and `POST /api/experiment/<id>/save-confusion`. Saved metrics are prefixed with the matrix name when more than one matrix exists, so saving from each doesn't clobber the previous

### Fixed

- **Sidebar no longer pops back open on every detail refresh** — adding a metric, param, tag, note, or any other in-place mutation kept re-expanding the experiment sidebar even after you collapsed it. The dashboard now only auto-expands the sidebar when transitioning into the detail view (or switching to a different experiment); subsequent refreshes leave the user's collapsed/open choice alone

## [1.4.5] - 2026-04-28

### Changed

- **Confusion matrix class names render in caps** — both the column header inputs and the mirrored row labels apply `text-transform: uppercase` so typing "class 1" displays as "CLASS 1" on both axes (the underlying value is preserved as-typed in storage and exports)
- **Color picker + dark-mode-friendly heatmap** — new "Color" dropdown in the matrix toolbar lets you switch between Blue, Green, Purple, Orange, Teal, and Grey palettes (choice persists in localStorage). The on-screen heatmap now uses an alpha-based fill so empty cells stay transparent against the card background, which fixes the washed-out look in dark mode while keeping the same gradient feel in light mode. The PNG export lerps from white to the chosen accent so it stays clean on a white background

## [1.4.4] - 2026-04-28

### Changed

- **Confusion matrix uses natural casing throughout** — dropped `text-transform: uppercase` from the axis labels ("Predicted" / "Actual"), the row/column "Total" labels, the metric stat labels, and the per-class table header. The PNG export now renders these in the same Title-case form. Domain abbreviations (TP/FP/FN/TN/F1) are kept since that's their conventional spelling

## [1.4.3] - 2026-04-28

### Changed

- **Confusion matrix row labels match column labels** — row class names share the same font, size, padding, and centering as the column-header inputs, so the two axes look like one set of labels rather than two visually distinct fields
- **Confusion matrix PNG export** — new "Export PNG" button rasterizes the matrix (with axis labels, totals, and the Blues heatmap) at 2× scale via SVG → canvas, ready to drop straight into a slide deck or paper

## [1.4.2] - 2026-04-28

### Changed

- **Confusion matrix totals, exports, and palette** — the matrix now grows a "Total" column on the right and a "Total" row at the bottom showing per-row, per-column, and grand-total counts. Cells are shaded with a single sklearn-style Blues gradient (no more red/green) so colorblind viewers and dark-mode users can read it without the traffic-light palette. New buttons export the matrix as **CSV** (download), **Markdown** (clipboard), or **JSON** (clipboard) — labels, row/column totals, and grand total included

## [1.4.1] - 2026-04-28

### Changed

- **Confusion matrix UX polish** — class names are now edited in one place (the column headers) and mirror onto the row headers, so labels stay in sync. Cells auto-fit large counts and drop the +/- spinner (counts can be pasted in directly). The "Actual" axis is rendered as a vertical sidebar that no longer overlaps row labels. A diagonal-green / off-diagonal-red heatmap shades each cell by relative magnitude so big confusions stand out at a glance. Per-class numbers in the results table are formatted with thousands separators

## [1.4.0] - 2026-04-28

### Added

- **Confusion matrix calculator in the dashboard** — every experiment detail view gains a "Confusion Matrix" tab where you punch in raw counts (binary or NxN multi-class) and immediately see accuracy, per-class precision/recall/F1, plus macro and weighted aggregates. Class labels are editable, the matrix size is adjustable up to 20 classes, and "Save as metrics" pushes accuracy and macro/weighted precision/recall/F1 onto the experiment as manual metrics. Matrix state is persisted per-experiment in localStorage so it survives reloads
- **Multi-line notes** — pressing Enter inside the inline notes editor now produces a real visual line break in the rendered notes; the detail view honors `\n` via `white-space: pre-wrap` so paragraphs read the way you typed them

## [1.3.0] - 2026-04-28

### Added

- **Editable manual params in the dashboard** — params now carry a `source` ('auto' or 'manual') alongside their value. Auto params (captured from the script via argparse/argv) are read-only with an "auto" badge; manual params (created via the New Experiment modal or the per-experiment "+ Add Param" form) get a "manual" badge and full inline-edit support: double-click the key to rename, double-click the value to edit, click `×` to delete. New endpoints: `/api/experiment/<id>/{add-param,edit-param,delete-param,rename-param}`
- **Per-experiment "+ Add Param" form** — every experiment detail view (auto or manual) gains a small form below the params table for attaching extra manual params after the run. Refuses to overwrite any existing key — to update a value, double-click to edit; to swap an auto key, pick a different name. Values are JSON-decoded when possible (so `50` stays a number, `true` stays a boolean) and fall back to a plain string otherwise

### Changed

- **`params` table now has a `source` column** — automatic ALTER TABLE migration on first run. Backfill marks params on manually-created experiments (those with NULL `hostname`/`python_ver`) as `manual`; everything else stays `auto`. Existing reads via `get_experiment_detail` are unchanged in shape; a new sibling `param_sources` map exposes per-key origin to the dashboard

## [1.2.0] - 2026-04-21

### Added

- **Auto-generated dashboard token** — `exptrack ui` now generates a per-session URL-safe token (`secrets.token_urlsafe`) when none is configured and prints a Jupyter-style URL with the token embedded. The token lives only in process memory: never persisted to `.exptrack/config.json`, never exported to the environment, so it can't leak to child processes. A fresh token is rolled on every restart. `--token` and `EXPTRACK_DASHBOARD_TOKEN` still take precedence when set
- **Jupyter-style login flow in the dashboard** — visiting with the token in the URL now stashes it in `localStorage` and strips it from the address bar (no more token in browser history), subsequent API calls send `Authorization: Bearer <token>` instead of a query param, and if the token is missing or rejected a modal login overlay appears with a token input. Bookmarking the bare `http://127.0.0.1:7331/` now just works across refreshes
- **`--no-auth` flag for `exptrack ui`** — opt out of the auto-generated token for fully-trusted local sessions
- **`exptrack ui-stop --port N`** — kill a dashboard process still holding a port (useful after a parent shell died without propagating SIGHUP, or you lost the auto-generated token in a different terminal). Uses `fuser` (Linux) with an `lsof` fallback (macOS/BSD)
- **EADDRINUSE hint** — `exptrack ui` now prints a helpful message pointing at `ui-stop` and `lsof -i :PORT` when the port is already taken

## [1.1.0] - 2026-04-20

### Added

- **Params-only export (CLI)** — new `exptrack export <id> --format` values that emit just the parameters: `params` (`key=value` lines, shell-friendly), `params-flags` (`--key value` CLI flags, with bare `--flag` for booleans), `params-json` (JSON object), `params-md` (markdown table, pastes into lab notebooks), and `params-tsv` (tab-separated, pastes into spreadsheets). Also available via `/api/export/<id>?format=<name>`
- **Params "Copy" button on the dashboard** — the detail view's Params section header now has a one-click Copy button (next to the section like the Reproduce box's Copy). Copies the parameters as a markdown table for direct paste into lab notebooks, Obsidian, GitHub, or Jupyter markdown cells. The main Export ▼ / Copy ▼ dropdowns remain unchanged (whole-experiment only)

### Changed

- **Artifacts list is truncated for runs with >50 artifacts** — the detail view now shows the first 50 artifacts with a "Show all N" expand button. Prevents the page from becoming unreadable on runs that produce hundreds of outputs
- **Artifacts filter** — a filter input appears above the artifact list when a run has more than 10 artifacts, so users can quickly locate a specific file by label or path. Typing into the filter also auto-expands any truncated rows

### Fixed

- **Duplicate `batch-size` / `batch_size` params** — scripts using argparse with dashed long flags (e.g. `--batch-size`) previously produced two keys in their params: the dashed form from the raw `sys.argv` fallback and the underscored form from argparse's Namespace. The fallback now normalizes dashes to underscores on capture, matching argparse's convention, so only one key lands in the params store

## [1.0.1] - 2026-03-27

### Added

- **Experiment resume** — `Experiment.resume(exp_id)` reopens a finished/failed experiment. Metrics, artifacts, and params aggregate into the same run. A `resume` timeline event records the command that triggered it
- **Auto-resume detection** — `exptrack run` auto-detects `--resume` (or flags listed in `resume_flags` config) from the script's own argv and resumes the latest experiment for that script. No extra flags needed
- **Shell pipeline resume** — `exptrack run-start --resume [EXP_ID]` resumes from shell scripts and SLURM jobs
- **Resume example** — `examples/resume_training.py` demonstrates first run + resume with metrics aggregation
- **Output auto-detection** — after a script finishes, new files (models, images, data) are scanned from the working directory and registered as artifacts. Recognizes `.pt`, `.pth`, `.ckpt`, `.safetensors`, `.h5`, `.onnx`, `.pkl`, and other ML file types

### Fixed

- **Model checkpoints not saved on resume** — argparse recapture was renaming the experiment's output directory mid-run, causing scripts to write to a stale path. Resumed experiments now preserve their original name and output directory
- **Model checkpoints not detected** — the `outputs/` directory was incorrectly skipped during auto-detection, so files saved there by the user's script were never registered
- **Artifact protection breaking resume** — `protect_previous_artifacts` was moving checkpoint files before the script started, breaking resume workflows that need to load from the same path. Removed entirely — artifacts are now tracked by reference only (path + hash), exptrack never copies or moves user files

### Removed

- **`protect_on_rerun` config option** — artifact protection removed. The deduplication set in auto-detect already prevents double-logging without needing to copy files
- **`artifact_protection.py` module** — no longer needed

## [1.0.0] - 2026-03-26

Initial public release.

### Core

- **Zero-friction tracking** — wrap any script with `exptrack run train.py --lr 0.01` and parameters, git state, and artifacts are captured automatically. No code changes required
- **Four integration modes**: CLI wrapper (`exptrack run`), Jupyter (`%load_ext exptrack`), shell/SLURM pipelines (`run-start`/`run-finish`), and Python API (`Experiment` context manager)
- **Argparse capture** — monkey-patches `parse_args()` and `parse_known_args()` with `sys.argv` fallback for non-argparse scripts
- **Matplotlib capture** — `plt.savefig()` and `Figure.savefig()` calls auto-register artifacts. Figures saved before experiment creation are buffered
- **Git state** — branch, commit hash, and diff against HEAD stored with every run
- **SQLite storage** (WAL mode) with 7 tables. No external dependencies — stdlib only
- **Plugin system** with 4 lifecycle hooks and a built-in GitHub Sync plugin

### Jupyter Notebooks

- Cell execution timeline with sequence numbers for full execution order reconstruction
- Content-addressed cell lineage (SHA-256 hashing, parent discovery via similarity matching)
- Variable fingerprinting with automatic hyperparameter detection (`lr`, `batch_size`, etc.)
- Code diffs between runs — stores only diffs, not full source copies

### Shell / SLURM Pipelines

- `run-start` / `run-finish` / `run-fail` commands with `eval $()` integration
- `log-metric` and `log-artifact` for logging from shell scripts
- Multi-step pipelines with `--study` and `--stage` flags
- Study/stage inheritance via environment variables across scripts
- SLURM environment variables captured automatically

### Web Dashboard (`exptrack ui`)

- Experiment list with status filters, search, sparkline charts, and customizable columns (resize, show/hide)
- Detail view with parameters, metrics, interactive charts (linear/log scale, zoom, downsampling), code changes, and git diff
- Reproduce command box with one-click copy and Save-to-Commands
- Compare experiments: side-by-side with overlay charts (2 runs) or bar charts (3+ runs)
- Image gallery with lightbox and side-by-side/overlay/swipe comparison
- Data file rendering: CSV, TSV, JSON, and JSONL displayed as interactive sortable tables
- Timeline view with cell executions, variable changes, and artifact creation
- Toolbox panel with commands notepad and todo list
- Manual experiment creation modal
- Studies and stages with highlight mode, filtering, and inline editing
- Inline editing for names, tags, notes, studies, and stages (double-click)
- Tag autocomplete, searchable filter dropdowns, bulk operations
- Timezone selector, dark mode
- Export to JSON, Markdown, CSV, TSV, and Plain Text
- Optional authentication via `EXPTRACK_DASHBOARD_TOKEN` or config

### CLI (24 commands)

- **Tracking**: `init`, `run`, `create`, `finish`
- **Pipelines**: `run-start`, `run-finish`, `run-fail`, `log-metric`, `log-artifact`
- **Inspect**: `ls`, `show`, `diff`, `compare`, `history`, `timeline`, `export`, `verify`
- **Organize**: `tag`, `untag`, `delete-tag`, `note`, `edit-note`, `study`, `unstudy`, `stage`
- **Maintain**: `rm`, `clean`, `stale`, `compact`, `backup`, `restore`, `storage`, `upgrade`
- Export supports JSON, Markdown, CSV, and TSV formats with `--all` for bulk export

### Configuration

- Per-project config via `.exptrack/config.json`
- Metric thinning: write-time (`metric_keep_every`) and read-time (min-max bucketing via `metric_max_points`)
- Artifact strategy, git diff size limits, naming conventions, auto-capture toggles
- Non-finite metric values (NaN, Inf) silently dropped

[1.1.0]: https://github.com/mikylab/exptrack/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/mikylab/exptrack/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mikylab/exptrack/releases/tag/v1.0.0
