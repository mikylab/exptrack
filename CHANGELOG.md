# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
