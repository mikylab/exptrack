# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**expTrack** is a local-first, zero-friction Python experiment tracker for ML workflows. It automatically captures parameters, metrics, and git state by monkey-patching argparse and IPython hooks — no code changes required in user scripts. Uses SQLite (WAL mode) for storage with no external dependencies (stdlib only).

## Installation

```bash
pip install -e .
```

Uses `pyproject.toml` with setuptools. The `exptrack` console script entry point maps to `exptrack.cli:main`.

## Running

```bash
# Initialize a project (creates .exptrack/ and patches .gitignore)
exptrack init [project_name]

# Wrap any training script
exptrack run train.py --lr 0.01 --data train
# Or: python -m exptrack train.py --lr 0.01

# Shell/SLURM pipeline integration (single step)
eval $(exptrack run-start --lr 0.01 --epochs 50)
# ... run training ...
exptrack run-finish $EXP_ID --metrics results.json
# or on failure:
exptrack run-fail $EXP_ID "reason"

# Multi-step pipeline (group steps in a study with numbered stages)
eval $(exptrack run-start --script train --study my-run --stage 1 --stage-name train --lr 0.01)
TRAIN_ID=$EXP_ID; python train.py; exptrack run-finish $TRAIN_ID
eval $(exptrack run-start --script test --study my-run --stage 2 --stage-name test)
TEST_ID=$EXP_ID; python test.py; exptrack run-finish $TEST_ID

# CLI commands: ls, show, diff, compare, history, timeline, tag, untag, note,
#   edit-note, rm, clean, finish, delete-tag, study, unstudy, stage, stale,
#   upgrade, storage, export, verify, ui
```

## Testing & Linting

No test suite or linting configuration exists in the repo yet.

## Architecture

```
exptrack/
  __init__.py                 Package init, exports Experiment, load_ipython_extension
  __main__.py                 python -m exptrack entry point (wraps scripts via runpy)
  config.py                   Project-aware config (.exptrack/config.json), root detection
  notebook.py                 Jupyter: %load_ext exptrack magic + explicit API
  core/
    __init__.py               Re-exports Experiment, make_run_name
    experiment.py             Experiment class, lifecycle, param/metric/artifact logging
    db.py                     SQLite schema (7 tables), migrations, WAL mode
    naming.py                 Run name generation ({script}__{params}__{date}_{uid})
    hashing.py                File integrity hashing (SHA-256, partial for large files)
    git.py                    Git branch/commit/diff capture
    artifact_protection.py    Archive old artifacts on path conflict during reruns
  capture/
    __init__.py               Re-exports capture modules
    argparse_patch.py         Patches parse_args() and parse_known_args()
    matplotlib_patch.py       Patches plt.savefig() and Figure.savefig()
    notebook_hooks.py         IPython post_run_cell hook, cell snapshots
    cell_lineage.py           Content-addressed cell tracking (SHA-256, 30% similarity)
    variables.py              Variable fingerprinting, HP detection, assignment extraction
    script_tracking.py        Git diff capture for scripts
  cli/
    main.py                   Argument parsing, subcommand dispatch
    pipeline_cmds.py          run-start, run-finish, run-fail, log-metric, log-artifact
    inspect_cmds.py           ls, show, diff, compare, history, timeline, export, verify
    mutate_cmds.py            tag, untag, delete-tag, note, edit-note, rm, finish
    admin_cmds.py             clean, stale, upgrade, storage
  plugins/
    __init__.py               Plugin base class + event registry singleton
    github_sync.py            Sync run metadata to GitHub repo as JSONL
  dashboard/
    app.py                    Web UI entry point (stdlib http.server, default port 7331)
    handler.py                HTTP request handler, dispatches to route modules
    static.py                 Assembler: imports CSS/HTML/JS parts into DASHBOARD_HTML
    static_parts/
      __init__.py             Package docstring
      styles.py               Re-exports CSS from css/ subpackage
      scripts.py              Re-exports JS from js/ subpackage
      html.py                 HTML structure (HEAD, BODY, FOOTER)
      css/
        __init__.py           CSS assembly: get_all_css() + all section re-exports
        reset.py              CSS variables, theme definitions, base reset
        layout.py             Header, sidebar, main content layout
        cards.py              Experiment cards, stats cards, status indicators
        table.py              Experiment table, toolbar, actions, filters
        detail.py             Detail panel, info grid, params/metrics tables
        code.py               Diff views, code changes, variable displays
        timeline.py           Timeline events, badges, within-compare, source viewer
        compare.py            Compare view, side-by-side diffs, reproduce box
        components.py         Tabs, help, export, tags, inline editing, owl mascot
        studies.py             Study management panel
        images.py             Image gallery, modals, image comparison
      js/
        __init__.py           JS assembly: get_all_js() + all section re-exports
        core.py               State variables, API helpers, dark mode, column config
        owl.py                Mascot animation, speech bubble, easter egg
        sidebar.py            Sidebar rendering, checkbox actions, bulk ops
        table.py              Table rendering, sorting, column resizing
        experiments.py        Experiment list filtering, grouping
        inline_edit.py        Double-click inline editing
        detail.py             Detail panel, tabs, metric charts, export
        compare.py            Compare view, diff rendering, metric comparison
        mutations.py          Tag/note/name/delete/pin mutation helpers
        timeline.py           Timeline rendering, cell lineage viewer
        image_compare.py      Image diff viewer with slider overlay
        studies.py            Study management UI
        stage.py              Stage/pipeline state tracking
        manual.py             Manual experiment creation modal
        init.py               Page initialization, event binding
    js/
      __init__.py             Convenience re-exports with short aliases
    routes/
      __init__.py             Package docstring
      read_routes.py          GET endpoints (stats, experiments, metrics, etc.)
      write_routes.py         POST endpoints (tag, note, delete, log-metric, etc.)
```

### Key modules

- **`core/experiment.py`** — `Experiment` class: context manager support, param/metric/artifact logging, timeline events, variable context reconstruction. Properties: id, name, status, git_branch, git_commit, git_diff, created_at, duration_s, tags, notes
- **`core/db.py`** — SQLite schema with 7 tables (experiments, params, metrics, artifacts, timeline, cell_lineage, code_baselines). WAL mode, indexed on exp_id/key/created_at. Schema migrations via ALTER TABLE
- **`capture/argparse_patch.py`** — Patches both `parse_args()` AND `parse_known_args()`, plus raw `sys.argv` fallback for non-argparse scripts (catches single-dash flags, click, manual parsing)
- **`capture/notebook_hooks.py`** — `post_run_cell` hook: content-addressed cell lineage, diff against parent cells, variable change detection with fingerprinting, assignment expression enrichment, timeline event emission, HP auto-detection, cell snapshot saving
- **`capture/variables.py`** — Variable fingerprinting (scalars via repr, ndarrays/DataFrames/Tensors via content hash, collections via JSON). HP name regex detection. Assignment expression extraction from cell source. Observational cell detection
- **`capture/matplotlib_patch.py`** — Patches `plt.savefig()` and `Figure.savefig()`. Copies figures to experiment output directory. Buffers artifacts saved before experiment creation. Deduplication by path
- **`capture/cell_lineage.py`** — Content-addressed cell tracking: SHA-256 hash of source, parent discovery via 30% SequenceMatcher similarity, simple_diff for cell change display
- **`notebook.py`** — `%load_ext exptrack` magic + explicit API (`start()`, `metric()`, `metrics()`, `param()`, `tag()`, `note()`, `artifact()`, `out()`, `done()`, `current()`). Deferred experiment creation (skips `%load_ext` cell itself)
- **`cli/`** — 24 subcommands across 4 modules. ANSI-colored terminal output. Shell pipeline commands (`run-start`/`run-finish`/`run-fail`) print to stdout for `eval $()` capture, everything else to stderr
- **`plugins/__init__.py`** — `Plugin` base class with 4 lifecycle hooks (`on_start`, `on_finish`, `on_fail`, `on_metric`). `registry` singleton loads plugins dynamically from config
- **`dashboard/`** — Web UI: stats cards, experiment list with filters, detail view with Chart.js metric plots, timeline view with cell source viewer, compare view (pair + multi), image comparison, git diff viewer. Inline editing (double-click), tag autocomplete, timezone selector, bulk operations, studies/stages, manual experiment creation, export (JSON/Markdown/Plain Text). Fully modularized: 12 CSS modules in `static_parts/css/`, 15 JS modules in `static_parts/js/`, routes split into `routes/read_routes.py` and `routes/write_routes.py`

## Key Design Patterns

- **Zero-friction capture**: Argparse monkey-patching and IPython hooks intercept params without user code changes
- **Diff-only storage**: Script changes are diffed against `git HEAD`; notebook snapshots store only cell diffs and variable change hashes — no full-source copies, keeps `.exptrack/` light
- **Content-addressed cell lineage**: Cells identified by SHA-256 of source content, parent found via 30% SequenceMatcher similarity. Handles cell reordering and splits
- **Project root detection**: Walks parent directories looking for `.git` or `.exptrack/`
- **stdout/stderr separation**: Shell pipeline commands (`run-start`) output `export` statements to stdout so `eval $()` works; all status messages go to stderr
- **Auto artifact linking**: `plt.savefig()` is monkey-patched so saved plots auto-register as artifacts. Figures saved before experiment creation are buffered and flushed
- **Artifact protection**: On rerun, old artifacts at conflicting paths are archived to prevent data loss
- **Plugin system**: Plugins loaded dynamically from `exptrack.plugins.<name>`, each module exports `plugin_class`. 4 lifecycle hooks
- **Per-project storage**: DB + notebook history in `.exptrack/` (gitignored), config.json is committable
- **Inline editing**: All editable fields (name, tags, notes) support double-click inline editing in dashboard — no modal prompts
- **Tag autocomplete**: `/api/all-tags` endpoint returns all tags with usage counts; UI shows autocomplete dropdown
- **Timezone-aware display**: Dashboard timestamps use `Intl.DateTimeFormat` with configurable timezone stored in project config
- **Timeline-based tracking**: Every event (cell_exec, var_set, artifact, metric, observational) gets a sequence number for full execution order reconstruction

## Database Schema

SQLite WAL mode with 7 tables:

- **`experiments`** — run metadata (id, name, status, created_at, duration_s, git_branch, git_commit, git_diff, hostname, python_ver, notes, tags, output_dir)
- **`params`** — key/value pairs (exp_id, key, value as JSON string)
- **`metrics`** — float values (exp_id, key, value, step, ts)
- **`artifacts`** — output files (exp_id, label, path, content_hash, size_bytes, timeline_seq, created_at)
- **`timeline`** — execution events (exp_id, seq, event_type, cell_hash, cell_pos, key, value, prev_value, source_diff, ts)
- **`cell_lineage`** — content-addressed cell history (cell_hash, notebook, source, parent_hash, created_at)
- **`code_baselines`** — position-based cell baselines (notebook, cell_seq, source, source_hash)

Indexed on: metrics(exp_id, key), params(exp_id), artifacts(exp_id), timeline(exp_id, seq), experiments(created_at, status).

## Configuration

`.exptrack/config.json` defaults:

```json
{
  "db": ".exptrack/experiments.db",
  "outputs_dir": "outputs",
  "notebook_history_dir": ".exptrack/notebook_history",
  "max_git_diff_kb": 256,
  "artifact_strategy": "reference",
  "hash_max_mb": 500,
  "protect_on_rerun": true,
  "timezone": "",
  "auto_capture": { "argparse": true, "argv": true, "notebook": true },
  "naming": { "max_param_keys": 4, "key_max_len": 8 },
  "plugins": { "enabled": [] }
}
```

## Coding Best Practices

### General Principles
- **stdlib only**: No external dependencies. Every import must come from the Python standard library
- **Keep functions focused**: Each function should do one thing. If a function exceeds ~40 lines, consider splitting it
- **Reuse existing utilities**: Check `core/db.py` (`get_db`, `_find_exp`), `cli/formatting.py` (ANSI color helpers), and `config.py` (project root, config loading) before writing new helpers
- **Deduplication**: `log_artifact()` already deduplicates by resolved path. Use this pattern — check before insert — for any new data types
- **Error boundaries**: Wrap external operations (file I/O, git, plugin calls) in try/except. Never let a capture failure crash the user's training script

### Dashboard Modularization

The dashboard has been fully modularized. `static.py` is a thin assembler (~10 lines) that imports parts from `static_parts/` and concatenates into `DASHBOARD_HTML`.

**Current structure:**
- **`static_parts/css/`** — 12 CSS modules (reset, layout, cards, table, detail, code, timeline, compare, components, studies, images). Each exports a single string constant. `get_all_css()` assembles them
- **`static_parts/js/`** — 15 JS modules (core, owl, sidebar, table, experiments, inline_edit, detail, compare, mutations, timeline, image_compare, studies, stage, manual, init). `get_all_js()` assembles them
- **`static_parts/html.py`** — HTML_HEAD, HTML_BODY, HTML_FOOTER
- **`static_parts/styles.py`** and **`static_parts/scripts.py`** — thin re-export shims for backward compatibility
- **`dashboard/js/__init__.py`** — convenience re-exports with short aliases (e.g., `from exptrack.dashboard.js import core`)
- **`routes/read_routes.py`** — GET API endpoints
- **`routes/write_routes.py`** — POST API endpoints

**Rules for dashboard changes:**
- When modifying JS, keep the existing function signatures stable — other parts of the JS may call them
- All API calls should go through `api()` (GET) or `postApi()` (POST) helpers
- New UI features should follow the inline-editing pattern (double-click to edit, Enter/Escape to save/cancel)
- CSS custom properties (variables) are defined in `:root` — use them instead of hardcoded colors
