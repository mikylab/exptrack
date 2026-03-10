# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**expTrack** is a local-first, zero-friction Python experiment tracker for ML workflows. It automatically captures parameters, metrics, and git state by monkey-patching argparse and IPython hooks -- no code changes required in user scripts. Uses SQLite (WAL mode) for storage with no external dependencies (stdlib only).

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

# Shell/SLURM pipeline integration
eval $(exptrack run-start --lr 0.01 --epochs 50)
# ... run training ...
exptrack run-finish $EXP_ID --metrics results.json
# or on failure:
exptrack run-fail $EXP_ID "reason"

# CLI commands: ls, show, diff, compare, history, tag, note, rm, clean, stale, upgrade, ui
```

## Testing & Linting

No test suite or linting configuration exists in the repo yet.

## Architecture

```
exptrack/
  __init__.py          # Package init, exports Experiment
  __main__.py          # python -m exptrack entry point (wraps scripts via runpy)
  core.py              # Experiment class, DB schema, git capture, run naming
  config.py            # Project-aware config (.exptrack/config.json), root detection
  cli.py               # Terminal UI (18+ subcommands), SLURM integration, upgrade
  notebook.py          # Jupyter: %load_ext exptrack magic + explicit API
  capture/
    __init__.py        # Argparse monkey-patch (parse_args + parse_known_args),
                       #   raw argv fallback, notebook cell snapshot hooks
  plugins/
    __init__.py        # Plugin base class + event registry singleton
    github_sync.py     # Example: sync run metadata to GitHub repo as JSONL
  dashboard/
    app.py             # Web UI (stdlib http.server, Chart.js from CDN)
```

### Key modules

- **`core.py`** -- `Experiment` class: DB schema (4 tables: experiments, params, metrics, artifacts), git state snapshot, run naming (`{script}__{params}__{date}_{uid}`), context manager support
- **`capture/__init__.py`** -- Patches both `parse_args()` AND `parse_known_args()`, plus raw `sys.argv` fallback catches single-dash flags, click, manual parsing
- **`cli.py`** -- ANSI-colored terminal UI. Shell pipeline commands (`run-start`/`run-finish`/`run-fail`) print to stdout for `eval $()` capture, everything else to stderr
- **`notebook.py`** -- `%load_ext exptrack` magic + explicit API (`start()`, `metric()`, `out()`, `done()`). IPython `post_execute` hook captures cell diffs and auto-detects hyperparameters
- **`plugins/__init__.py`** -- `Plugin` base class with lifecycle hooks (`on_start`, `on_finish`, `on_fail`, `on_metric`). `registry` singleton loads plugins from config

## Key Design Patterns

- **Zero-friction capture**: Argparse monkey-patching and IPython hooks intercept params without user code changes
- **Project root detection**: Walks parent directories looking for `.git` or `.exptrack/`
- **stdout/stderr separation**: Shell pipeline commands (`run-start`) output `export` statements to stdout so `eval $()` works; all status messages go to stderr
- **Plugin system**: Plugins loaded dynamically from `exptrack.plugins.<name>`, each module exports `plugin_class`
- **Per-project storage**: DB + notebook history in `.exptrack/` (gitignored), config.json is committable

## Database Schema

SQLite with tables: `experiments` (run metadata + full git diff), `params` (JSON-stringified key/value), `metrics` (float values with optional step + timestamp), `artifacts` (output file paths). Indexed on `metrics(exp_id, key)` and `params(exp_id)`.
