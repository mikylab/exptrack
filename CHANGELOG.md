# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Dashboard CSS and JS modularization: `static_parts/css/` (12 modules) and `static_parts/js/` (15 modules)
- `exptrack compact` command to strip git diffs while keeping experiment results
- Manual experiment creation modal in dashboard
- Image comparison features: side-by-side, overlay, and swipe modes
- Multi-compare bar charts and overlay line charts for 2+ experiments
- Reproduce command box with one-click copy in experiment detail
- Unified metrics storage: manual results and auto-captured metrics in one table
- Metric namespace prefixes, abbreviations, and group collapse
- Click-to-delete chart points and double-click metric rename
- Studies (renamed from groups) and stage fields with inline editing
- Customizable table columns with resize, show/hide, and reset defaults
- Row hiding with toggle panel below experiment table
- Database health reporting and WAL checkpoint command
- Per-thread DB connection caching for concurrent notebook use
- Storage limits for git diffs and notebook cells
- Highlight mode for experiment rows by study
- Sparkline mini-charts in experiment list metrics column
- Global tag deletion and tag management panel in dashboard
- Compare button for quick experiment comparison from list view
- Output directory artifact scanning

### Changed
- Dashboard modularized: `static.py` is now a thin assembler, CSS in `static_parts/css/`, JS in `static_parts/js/`, routes in `routes/`
- `styles.py` and `scripts.py` reduced to re-export shims (~20 lines each, down from 878 and 4354)
- Metrics and results unified into single metrics table with source badges (auto/manual/pipeline)
- Export and Copy separated into distinct dropdowns in detail view

### Fixed
- Database locked errors when rerunning notebooks on same kernel
- BrokenPipeError from browser closing dashboard connections early
- Owl speech bubble dismissal and positioning
- Table overflow and horizontal scroll with default column widths
- Multi-compare KeyError and selector issues
- Compact buttons feedback (alert-based confirmation)
- Tag deletion UX: visible detail view x buttons now work correctly
- Variable display losing assignment expression on notebook rerun
- License field format in pyproject.toml for setuptools compatibility
- JS syntax errors from inline onclick handlers (replaced with event wiring)

## [2.0.0] - 2026-03-12

### Added
- Full README documentation with CLI reference, Python API, plugin guide, and troubleshooting
- End-to-end tests for artifact protection lifecycle
- Artifact protection broadened to all experiments with expanded auto-detection
- Reference-only artifact strategy with SHA-256 integrity verification
- Output folder rename when experiment is renamed, with output_dir tracked by ID
- `finish` CLI command to manually mark running experiments as done
- `storage` command showing DB size, output size, row counts, and optimization tips
- Cascade delete for experiments (params, metrics, artifacts, timeline cleaned up)
- Finish-run button in web dashboard

### Changed
- Refactored bloated modules into packages with cleaner separation of concerns
- Database optimizations (indexes on frequently queried columns)
- Outputs folder uses reference-only artifacts instead of copies by default

### Fixed
- Savefig timing and artifact protection race conditions
- Dashboard export consistency across JSON, Markdown, and Plain Text formats
- Artifact-experiment association bugs
- Build error from deprecated license classifier (PEP 639 compatibility)

## [1.0.0] - 2026-03-11

### Added
- Web dashboard (`exptrack ui`) with stdlib http.server and Chart.js
  - Experiment list with status filters, search, and metric previews
  - Experiment detail view with params, metrics, code changes, and git diff
  - Timeline view with chronological event log and cell source viewer
  - Compare view for side-by-side experiment comparison
  - Inline editing (double-click to edit names, tags, notes)
  - Tag autocomplete with usage counts
  - Timezone selector saved to project config
  - Bulk operations (select multiple, delete, tag)
  - Export to JSON, Markdown, and Plain Text
- Execution timeline tracking with sequence numbers for full execution order
- Content-addressed cell lineage (SHA-256, 30% similarity parent discovery)
- Variable fingerprinting with HP auto-detection (recognizes `lr`, `batch_size`, etc.)
- Assignment expression enrichment from cell source
- Incremental code diffing against DB baselines
- `--baselines` flag for `clean` command to wipe code baselines
- Collapsible detail sections in dashboard
- Savefig extension auto-detection for matplotlib patches
- Dedicated Code Changes and Variable Changes sections in dashboard
- IDE-style dashboard layout with side panel and select mode
- Lab notebook visual theme for experiment table

### Changed
- Dashboard underwent multiple UI redesigns for better UX
- Snapshot storage slimmed to diffs-only (no full-source copies)
- Experiment creation deferred until first real cell execution (skips `%load_ext` cell)

### Fixed
- Timeline variable capture for functions, tensors, and non-scalar types
- Notebook cell and variable tracking across reordering and splits
- Cell diff logging for `%exp_start` (switched to post_run_cell event)
- Variable capture for non-scalar types (ndarrays, DataFrames, Tensors)
- Numpy logging format issues
- Duplicate artifact registration
- Artifact tagging and cell logging
- Dashboard compare view reliability
- Notebook CSS padding issues

## [0.1.0] - 2026-03-10

### Added
- Initial project structure and package setup
- `exptrack init` command to initialize projects (creates `.exptrack/`, patches `.gitignore`)
- `exptrack run` command to wrap training scripts with automatic tracking
- `python -m exptrack` entry point for script wrapping via runpy
- Shell/SLURM pipeline commands: `run-start`, `run-finish`, `run-fail`, `log-metric`, `log-artifact`
- CLI commands: `ls`, `show`, `diff`, `compare`, `history`, `tag`, `untag`, `note`, `edit-note`, `rm`, `clean`, `stale`, `upgrade`, `export`, `verify`
- Argparse monkey-patching (`parse_args()` and `parse_known_args()`) with raw `sys.argv` fallback
- Matplotlib `plt.savefig()` and `Figure.savefig()` auto-patching for artifact capture
- IPython `%load_ext exptrack` magic extension with post_run_cell hooks
- Explicit notebook API (`start()`, `metric()`, `param()`, `tag()`, `note()`, `artifact()`, `out()`, `done()`)
- `Experiment` class with context manager support
- SQLite storage with WAL mode (7 tables: experiments, params, metrics, artifacts, timeline, cell_lineage, code_baselines)
- Git state capture (branch, commit hash, uncommitted diff)
- Project root detection (walks parent directories for `.git` or `.exptrack/`)
- Plugin system with 4 lifecycle hooks (`on_start`, `on_finish`, `on_fail`, `on_metric`)
- GitHub Sync built-in plugin (JSONL export to GitHub repo)
- Per-project configuration via `.exptrack/config.json`
- `--here` flag for `exptrack init` to force initialization in current directory
- `.gitignore` template with Python and exptrack exclusions

### Fixed
- pip install and Jupyter magic registration
- Script wrapping via `python -m exptrack`
- exptrack import in Jupyter environments
- `exptrack init` directory resolution

[Unreleased]: https://github.com/mikylab/expTrack/compare/HEAD
[2.0.0]: https://github.com/mikylab/expTrack/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/mikylab/expTrack/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/mikylab/expTrack/releases/tag/v0.1.0
