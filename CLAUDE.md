# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**exptrack** is a local-first, zero-friction Python experiment tracker for ML workflows. It automatically captures parameters, metrics, and git state by monkey-patching argparse and IPython hooks — no code changes required in user scripts. Uses SQLite (WAL mode) for storage with no external dependencies (stdlib only).

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
# First call sets EXP_STUDY and EXP_STAGE; subsequent calls inherit automatically
eval $(exptrack run-start --study my-run --stage 1 --stage-name train --lr 0.01)
python train.py; exptrack run-finish $EXP_ID
# EXP_STUDY inherited, EXP_STAGE auto-increments to 2
eval $(exptrack run-start --stage-name eval)
./evaluate; exptrack run-finish $EXP_ID

# Resume a previous experiment (auto-detected from script's --resume flag)
# All metrics, artifacts, and params aggregate into the same experiment
exptrack run train.py --output_dir results/ --resume --ckpt results/model.pt

# Shell pipeline resume
eval $(exptrack run-start --resume --lr 0.01)
# or resume a specific experiment:
eval $(exptrack run-start --resume abc123 --lr 0.01)

# Programmatic resume
from exptrack.core import Experiment
exp = Experiment.resume("abc123")    # by ID
exp = Experiment.resume("abc")       # by ID prefix

# Session Trees (notebook only — opt-in, no-op when not started)
#   %exptrack session start "name"        begin a session (must precede other magics)
#   %exptrack checkpoint "label"          mark stable point (snapshots per-checkpoint diff)
#   %exptrack branch "label"              declare intent for the next divergence
#   %%scratch                             cell magic — runs cell, never logged
#   %%pin "label"                         cell magic — runs cell, snapshots cell+output as artifact
#   %exptrack promote "label"             link active experiment to current node
#   %exptrack session end                 close session (open branches → abandoned)
#
# CLI commands: ls, show, diff, compare, history, timeline, tag, untag, note,
#   edit-note, rm, clean, finish, delete-tag, study, unstudy, stage, stale,
#   upgrade, storage, export, verify, ui,
#   sessions, session show|nodes|rm|note     Session Trees
```

## Testing & Linting

```bash
pip install pytest
python -m pytest tests/ -x -q
```

Key test files: `test_pipeline_shell.py` (53 tests for shell/SLURM pipeline commands),
`test_experiment.py`, `test_cli.py`, `test_db.py`, `test_capture_argparse.py`, etc.

## Architecture

```
exptrack/
  __init__.py                 Package init, exports Experiment, load_ipython_extension
  __main__.py                 python -m exptrack entry point (wraps scripts via runpy, auto-resume detection)
  config.py                   Project-aware config (.exptrack/config.json), root detection
  notebook.py                 Jupyter: %load_ext exptrack magic + explicit API
  core/
    __init__.py               Re-exports Experiment, make_run_name
    experiment.py             Experiment class, lifecycle, param/metric/artifact logging
    db.py                     SQLite schema (9 tables), migrations, WAL mode
    naming.py                 Run name generation ({script}__{params}__{date}_{uid})
    hashing.py                File integrity hashing (SHA-256, partial for large files)
    git.py                    Git branch/commit/diff capture

  capture/
    __init__.py               Re-exports capture modules
    argparse_patch.py         Patches parse_args() and parse_known_args()
    matplotlib_patch.py       Patches plt.savefig() and Figure.savefig()
    notebook_hooks.py         IPython post_run_cell hook, cell snapshots (skips %%scratch cells)
    session_hooks.py          Session Trees magics (%exptrack ..., %%scratch)
    cell_lineage.py           Content-addressed cell tracking (SHA-256, 30% similarity)
    variables.py              Variable fingerprinting, HP detection, assignment extraction
    script_tracking.py        Git diff capture for scripts
  cli/
    main.py                   Argument parsing, subcommand dispatch
    pipeline_cmds.py          run-start, run-finish, run-fail, log-metric, log-artifact
    inspect_cmds.py           ls, show, diff, compare, history, timeline, export, verify
    mutate_cmds.py            tag, untag, delete-tag, note, edit-note, rm, finish
    admin_cmds.py             clean, stale, upgrade, storage
    session_cmds.py           sessions, session show|nodes|rm|note (Session Trees CLI)
  sessions/
    __init__.py               Re-exports SessionManager, get_current_session, set_current_session
    manager.py                SessionManager — start/end, checkpoint, branch, promote, get_tree
    tree.py                   ASCII renderer + JSON renderer + list_sessions, find_session
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
        charts.py             Chart toolbar, scale controls, chart containers
        code.py               Diff views, code changes, variable displays
        timeline.py           Timeline events, badges, within-compare, source viewer
        compare.py            Compare view, side-by-side diffs, reproduce box
        components.py         Tabs, help, export, tags, inline editing, owl mascot
        studies.py             Study management panel
        sessions.py           Session Trees tree-view styling (checkpoint/branch/abandoned nodes)
        images.py             Image gallery, modals, image comparison
      js/
        __init__.py           JS assembly: get_all_js() + all section re-exports
        core.py               State variables, API helpers, dark mode, column config
        owl.py                Mascot animation, speech bubble, easter egg
        sidebar.py            Sidebar rendering, checkbox actions, bulk ops
        table.py              Table rendering, sorting, column resizing
        experiments.py        Experiment list filtering, grouping
        inline_edit.py        Double-click inline editing
        detail.py             Detail panel, tabs, overview preview, export
        charts.py             Charts tab: single/all view, scale controls, downsampling
        compare.py            Compare view, diff rendering, metric comparison
        mutations.py          Tag/note/name/delete/pin mutation helpers
        timeline.py           Timeline rendering, cell lineage viewer
        image_compare.py      Image diff viewer with slider overlay
        studies.py            Study management UI
        stage.py              Stage/pipeline state tracking
        manual.py             Manual experiment creation modal
        confusion.py          Confusion matrix calculator tab (per-experiment)
        sessions.py           Session Trees tab — list + tree renderer + node detail
        init.py               Page initialization, event binding
    js/
      __init__.py             Convenience re-exports with short aliases
    routes/
      __init__.py             Package docstring
      read_routes.py          GET endpoints (stats, experiments, metrics, etc.)
      write_routes.py         POST endpoints (tag, note, delete, log-metric, etc.)
```

### Key modules

- **`core/experiment.py`** — `Experiment` class: context manager support, param/metric/artifact logging, timeline events, variable context reconstruction. `Experiment.resume(exp_id)` reopens a finished experiment for continuation. `thin_every` parameter controls write-time metric thinning. Properties: id, name, status, git_branch, git_commit, git_diff, created_at, duration_s, tags, notes
- **`core/db.py`** — SQLite schema with 9 tables (experiments, params, metrics, artifacts, timeline, cell_lineage, code_baselines, sessions, session_nodes). WAL mode, indexed on exp_id/key/created_at. Schema migrations via ALTER TABLE
- **`capture/argparse_patch.py`** — Patches both `parse_args()` AND `parse_known_args()`, plus raw `sys.argv` fallback for non-argparse scripts (catches single-dash flags, click, manual parsing)
- **`capture/notebook_hooks.py`** — `post_run_cell` hook: content-addressed cell lineage, diff against parent cells, variable change detection with fingerprinting, assignment expression enrichment, timeline event emission, HP auto-detection, cell snapshot saving
- **`capture/variables.py`** — Variable fingerprinting (scalars via repr, ndarrays/DataFrames/Tensors via content hash, collections via JSON). HP name regex detection. Assignment expression extraction from cell source. Observational cell detection
- **`capture/matplotlib_patch.py`** — Patches `plt.savefig()` and `Figure.savefig()`. Copies figures to experiment output directory. Buffers artifacts saved before experiment creation. Deduplication by path
- **`capture/cell_lineage.py`** — Content-addressed cell tracking: SHA-256 hash of source, parent discovery via 30% SequenceMatcher similarity, simple_diff for cell change display
- **`notebook.py`** — `%load_ext exptrack` magic + explicit API (`start()`, `metric()`, `metrics()`, `param()`, `tag()`, `note()`, `artifact()`, `out()`, `done()`, `current()`). Deferred experiment creation (skips `%load_ext` cell itself)
- **`cli/`** — 24 subcommands across 4 modules. ANSI-colored terminal output. Shell pipeline commands (`run-start`/`run-finish`/`run-fail`) print to stdout for `eval $()` capture, everything else to stderr
- **`plugins/__init__.py`** — `Plugin` base class with 4 lifecycle hooks (`on_start`, `on_finish`, `on_fail`, `on_metric`). `registry` singleton loads plugins dynamically from config
- **`dashboard/`** — Web UI: stats cards, experiment list with filters, detail view with overview chart preview, dedicated Charts tab (single/all view with scale controls and configurable downsampling), timeline view with cell source viewer, compare view (pair + multi), image comparison, git diff viewer, per-experiment Confusion Matrix tab (binary or NxN, computes accuracy/precision/recall/F1 with macro and weighted aggregates; supports **multiple named matrices per experiment** with per-matrix palette + intensity slider, side-by-side **Compare** view with a metric-difference table; "Save as metrics" persists results via `/api/experiment/<id>/log-result` (prefixed with the matrix name when more than one matrix exists); matrix state persisted server-side via `POST /api/experiment/<id>/save-confusion` and `GET /api/confusion/<id>`, stored as a JSON-encoded manual param `_confusion_matrices`; legacy localStorage state auto-migrates on first load). The detail-view sidebar only auto-expands when entering detail or switching experiments — in-place refreshes (logging metrics, adding params, etc.) preserve the user's collapsed/open state. Image artifacts only display in the Images tab and Compare view (not in the overview artifacts table). Reproduce box with inline editing and Save-to-Commands (reads current DOM text, includes tags/study). Commands notepad with inline-adjustable code and modified indicator. Inline editing (double-click), tag autocomplete, timezone selector, bulk operations, studies/stages, manual experiment creation, export (JSON/Markdown/Plain Text). Fully modularized: 13 CSS modules in `static_parts/css/`, 16 JS modules in `static_parts/js/`, routes split into `routes/read_routes.py` and `routes/write_routes.py`

## Key Design Patterns

- **Zero-friction capture**: Argparse monkey-patching and IPython hooks intercept params without user code changes
- **Diff-only storage**: Script changes are diffed against `git HEAD`; notebook snapshots store only cell diffs and variable change hashes — no full-source copies, keeps `.exptrack/` light
- **Content-addressed cell lineage**: Cells identified by SHA-256 of source content, parent found via 30% SequenceMatcher similarity. Handles cell reordering and splits
- **Project root detection**: Walks parent directories looking for `.git` or `.exptrack/`
- **stdout/stderr separation**: Shell pipeline commands (`run-start`) output `export` statements to stdout so `eval $()` works; all status messages go to stderr
- **Auto artifact linking**: `plt.savefig()` is monkey-patched so saved plots auto-register as artifacts. Figures saved before experiment creation are buffered and flushed
- **Auto output detection**: After a script finishes, `_auto_detect_outputs` scans the working directory for new files (images, models, data) created during the run and registers them as artifacts. Deduplicates against already-registered artifacts. Recognizes `.pt`, `.pth`, `.ckpt`, `.safetensors`, `.h5`, `.onnx`, `.pkl`, and other common ML file types
- **No-copy artifact tracking**: Artifacts are tracked by reference (path + hash in DB) — exptrack never copies or moves user files. Resume workflows and large checkpoint directories are unaffected
- **Auto-resume detection**: When `exptrack run` sees `--resume` (or any flag in `resume_flags` config) in the script's argv, it automatically resumes the latest experiment for that script instead of creating a new one. All metrics, artifacts, and params aggregate into the same experiment. Timeline seq and stdout/stderr logs append. Shell pipelines use `exptrack run-start --resume [EXP_ID]` explicitly. Programmatic: `Experiment.resume(exp_id)`
- **Plugin system**: Plugins loaded dynamically from `exptrack.plugins.<name>`, each module exports `plugin_class`. 4 lifecycle hooks
- **Per-project storage**: DB + notebook history in `.exptrack/` (gitignored), config.json is committable
- **Collapsible study groups (sidebar + main table)**: The experiments sidebar has a "Group by study" toggle button in the sidebar header, and the main-table group bar has a "Study" option alongside Git Commit / Branch / Status / None. The two views use **different defaults**: the sidebar defaults study groups to **collapsed** (tracked via `expandedStudyGroups`, persisted as `exptrack-expanded-studies`) since a busy left rail is the main motivation; the main table defaults to **expanded** like the other groupings (uses the existing `collapsedGroups` set, so click-to-collapse behavior matches Git Commit / Branch / Status). Master sidebar toggle persists in localStorage (`exptrack-sidebar-group-study`). Experiments without a study fall under a "(no study)" header in both views
- **Pinnable Todos / Commands panel**: The toolbox drawer (Todos + Commands) can be pinned as a persistent right-side panel via the pushpin button in the drawer header or the "Pin Todos / Commands panel" checkbox in Settings → Display. When pinned, `body.toolbox-pinned` shifts the header and `#app-layout` right by `var(--toolbox-w)` (the drawer width), the overlay is hidden, and `closeToolbox()` is a no-op. The drawer's left edge is a drag handle when pinned — drag to resize between 260–800px (RAF-throttled). State persists in localStorage (`exptrack-toolbox-pinned`, `exptrack-toolbox-tab`, `exptrack-toolbox-w`). Each panel also has export buttons: Todos → `.md`/`.txt`/`.json`, Commands → `.sh` (runnable script)/`.md`/`.json`. Tab switches re-render local state without re-fetching
- **Save exports to project folder**: A "Save exports to project folder" toggle in Settings → Display routes all downloads (Todos, Commands, experiment exports) through `POST /api/save-export`, which writes to `<project_root>/exports/` and auto-suffixes filenames (`foo.md`, `foo_2.md`, …) so existing files are never overwritten. The unified `saveOrDownload(text, filename, mime)` helper in `js/core.py` wraps `downloadBlob` (browser download) with this server-side save path; preference is held in localStorage (`exptrack-export-to-folder`)
- **Inline editing**: All editable fields (name, tags, notes) support double-click inline editing in dashboard — no modal prompts
- **Tag autocomplete**: `/api/all-tags` endpoint returns all tags with usage counts; UI shows autocomplete dropdown
- **Timezone-aware display**: Dashboard timestamps use `Intl.DateTimeFormat` with configurable timezone stored in project config
- **Timeline-based tracking**: Every event (cell_exec, var_set, artifact, metric, observational) gets a sequence number for full execution order reconstruction
- **Metric thinning**: Two-layer system for large metric series. Write-time: `thin_every` param on Experiment or `metric_keep_every` in config stores every Nth point. Read-time: min-max bucketing downsamples for chart display. Configurable via dashboard settings or `metric_max_points` in config
- **Metric source tracking**: Metrics tagged as auto/manual/pipeline via `source` column. Manual metrics cannot overwrite auto points at the same step. Metrics table splits rows by source for clarity
- **Session Trees (opt-in exploratory tree tracking)**: A second tracking mode for notebooks that records the *shape* of exploration (checkpoints + branches + scratch cells) as a tree, layered on top of standard `%load_ext exptrack` capture. Activated only by `%exptrack session start "name"` — without it every other session magic is a silent no-op, so existing capture is unaffected. `%exptrack checkpoint "label"` writes a node and snapshots a per-checkpoint git diff (`git diff` from the previous checkpoint's commit, falling back to `git diff HEAD`). `%exptrack branch "label"` adds a child of the most recent checkpoint and tags it as the current node so subsequent commits/checkpoints flow under it. `%%scratch` is a cell magic that executes the cell body but its source begins with `%%scratch`, so the `_post_run_cell` hook detects it via `is_scratch_cell()` and skips all logging — no DB row is ever inserted, not insert-then-delete. `%exptrack promote "label"` writes the active experiment's `session_node_id` to the current node and appends the label to the node's `note`. `%exptrack session end` flips any open branch (no descendant) to `node_type='abandoned'` and sets `sessions.status='ended'`. The current `SessionManager` lives in `exptrack.sessions` as a module-level singleton (`get_current_session()` / `set_current_session()`); it caches `_current_node_id` and `_last_checkpoint_id` so branches always attach under the most recent checkpoint. The dashboard's `Sessions` tab (toggled via the `☰ Sessions` header button, which adds `body.sessions-active`) renders the tree as a vertical, indented node graph (checkpoints = filled circles, branches = open circles, abandoned = dashed/dimmed); each node shows label, time, diff summary, and a `→ exp <id>` badge when promoted. Clicking a node shows its source/diff/note in `#session-detail`, with inline note editing via `POST /api/session/<id>/note-node`. Cell runs render as collapsible `<details>` blocks (header shows `cell N / M` and line count) with an inline line-number gutter; older cells default to collapsed when there are more than three. Git diffs render in a GitHub-style **split** (side-by-side) view by default with a `Split / Unified` toggle (persisted in localStorage as `exptrack-diff-mode`); each file is its own collapsible card with per-file `+N −M` stats, hunk headers, and theme-aware tinted backgrounds (`--diff-add-bg`, `--diff-del-bg`, `--diff-add-bar`, `--diff-del-bar`, `--diff-empty-bg`, `--diff-hunk-bg`, all redefined under `body.dark`). Branch nodes capture and refresh their `git_diff` (vs. the parent checkpoint's commit, plus working-tree changes) at creation time and after every recorded cell, via `SessionManager._compute_diff_vs_checkpoint`; checkpoints freeze their diff at creation. Tree reconstruction tolerates orphaned nodes (attached to root) and synthesizes a root if none exists. CLI: `exptrack sessions`, `exptrack session show|nodes|rm|note`. Schema: `sessions`, `session_nodes`, plus a nullable `experiments.session_node_id` foreign key — all added by `_ensure_schema()` so `exptrack upgrade` is idempotent
- **Param source tracking**: Params tagged as auto/manual via `source` column. Auto params (captured by argparse/argv) are read-only in the dashboard; manual params (added via the manual-experiment modal or the per-experiment "+ Add Param" form) can be edited, renamed, or deleted inline. `+ Add Param` refuses to overwrite an existing key — to change a value, double-click to edit; to swap an auto key, delete is blocked, so pick a different key. Endpoints: `/api/experiment/<id>/{add-param,edit-param,delete-param,rename-param}`

## Database Schema

SQLite WAL mode with 9 tables:

- **`experiments`** — run metadata (id, name, status, created_at, duration_s, git_branch, git_commit, git_diff, hostname, python_ver, notes, tags, output_dir, **session_node_id** — nullable FK into `session_nodes` set only by `%exptrack promote`)
- **`params`** — key/value pairs (exp_id, key, value as JSON string, source). Source is 'auto' (captured from script/argparse) or 'manual' (added via dashboard or `api_create_experiment`). Auto params are read-only in the UI; manual params can be edited, renamed, and deleted via dashboard inline editing
- **`metrics`** — float values (exp_id, key, value, step, ts, source). Source is 'auto' (from scripts), 'manual' (dashboard), or 'pipeline' (CLI)
- **`artifacts`** — output files (exp_id, label, path, content_hash, size_bytes, timeline_seq, created_at)
- **`timeline`** — execution events (exp_id, seq, event_type, cell_hash, cell_pos, key, value, prev_value, source_diff, ts)
- **`cell_lineage`** — content-addressed cell history (cell_hash, notebook, source, parent_hash, created_at)
- **`code_baselines`** — position-based cell baselines (notebook, cell_seq, source, source_hash)
- **`sessions`** — Session Trees container (id, name, notebook, status `'active'|'ended'`, git_branch, git_commit, created_at, ended_at). Created only by `%exptrack session start`
- **`session_nodes`** — tree nodes (id, session_id, parent_id, node_type `'root'|'checkpoint'|'branch'|'abandoned'`, label, note, cell_source, git_diff, git_commit, seq, created_at). Indexed on (session_id, seq) and (parent_id)

Indexed on: metrics(exp_id, key), params(exp_id), artifacts(exp_id), timeline(exp_id, seq), experiments(created_at, status).

## Configuration

`.exptrack/config.json` defaults:

```json
{
  "db": ".exptrack/experiments.db",
  "outputs_dir": "outputs",
  "exports_dir": "exports",
  "notebook_history_dir": ".exptrack/notebook_history",
  "max_git_diff_kb": 256,
  "artifact_strategy": "reference",
  "hash_max_mb": 500,
  "metric_keep_every": 1,
  "metric_max_points": 500,
  "timezone": "",
  "resume_flags": ["--resume"],
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
- **`static_parts/css/`** — 13 CSS modules (reset, layout, cards, table, detail, charts, code, timeline, compare, components, studies, images). Each exports a single string constant. `get_all_css()` assembles them
- **`static_parts/js/`** — JS modules (core, owl, sidebar, table, experiments, inline_edit, detail, charts, compare, mutations, timeline, image_compare, studies, stage, manual, todos, commands, confusion, init). `get_all_js()` assembles them
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

## Rules for Changes

Every user-visible change (new feature, bug fix, behavior change) must update **all three** of the following before commit:

1. **`CLAUDE.md`** — keep the codebase documentation in sync. Update the relevant sections (Architecture, Key modules, Key Design Patterns, Database Schema, Configuration) so this file accurately reflects the current state
2. **`CHANGELOG.md`** — add an entry under the current unreleased version using the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Use `### Added` / `### Changed` / `### Fixed` / `### Removed` sub-headings. Lead each bullet with a bolded short title (e.g. `**Param editing in the dashboard**`) followed by a one-sentence description of what changed and why a user should care
3. **`pyproject.toml`** — bump the `version` field. Patch (`x.y.Z+1`) for bug fixes; minor (`x.Y+1.0`) for new features or schema migrations; major (`X+1.0.0`) for breaking API changes. The `__version__` exposed in `exptrack/__init__.py` reads from package metadata, so this is the single source of truth

Internal-only refactors with no user-visible effect (e.g. moving a helper, renaming a private function) may skip the changelog and version bump, but should still update `CLAUDE.md` if the structural map changes.
