# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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

[Unreleased]: https://github.com/mikylab/exptrack/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mikylab/exptrack/releases/tag/v1.0.0
