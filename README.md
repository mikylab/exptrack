# expTrack

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![No Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](#why-exptrack)
[![SQLite](https://img.shields.io/badge/storage-SQLite-003B57.svg)](https://www.sqlite.org/)

**Local-first experiment tracker for ML workflows. Zero dependencies. Zero code changes.**

expTrack automatically captures parameters, metrics, git state, and code changes from your training scripts and notebooks -- without touching your code. It monkey-patches argparse and IPython hooks so tracking is invisible. Everything is stored locally in SQLite.

---

## Why expTrack?

Most experiment trackers ask you to rewrite your training code, install heavy dependencies, or sign up for a cloud service. expTrack takes a different approach:

- **Zero friction** -- wrap your script with `exptrack run` or add one line to your notebook. No `SummaryWriter`, no `wandb.init()`, no decorators
- **Zero dependencies** -- stdlib only (sqlite3, json, hashlib, http.server). Nothing to install beyond Python 3.8+
- **Local-first** -- everything stays on your machine in a single SQLite file. No accounts, no cloud, no internet required
- **Git-aware** -- captures branch, commit hash, and full uncommitted diff at run time. Know exactly what code produced each result
- **Code change tracking** -- diffs scripts against the last commit; tracks notebook cell edits and variable changes across executions
- **Auto artifact linking** -- `plt.savefig()` is monkey-patched so saved plots are automatically registered as experiment artifacts
- **Shell-native** -- first-class support for SLURM and multi-step pipelines via `eval $(exptrack run-start ...)`

---

## Quick Start

```bash
# 1. Install exptrack
pip install exptrack
# Or for development: pip install -e .

# 2. Initialize in your project
cd your_project/
exptrack init

# 3. Run your training script -- that's it
exptrack run train.py --lr 0.01 --epochs 20 --data cifar10

# 4. See your experiments
exptrack ls

# 5. Open the dashboard
exptrack ui
```

Your script needs **zero modifications**. expTrack automatically captures argparse params, names the run, snapshots the git diff, and links any saved plots.

---

## Table of Contents

- [Why expTrack?](#why-exptrack)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Scripts](#scripts)
- [Notebooks](#notebooks)
- [Shell / SLURM Pipelines](#shell--slurm-pipelines)
- [Web Dashboard](#web-dashboard)
- [Managing Experiments](#managing-experiments)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [Plugins](#plugins)
- [Python API](#python-api)
- [How It Works](#how-it-works)
- [expTrack vs. TensorBoard](#exptrack-vs-tensorboard)
- [Troubleshooting](#troubleshooting)
- [Project Layout](#project-layout)
- [Contributing](#contributing)
- [License](#license)

---

## Installation

expTrack has **zero external dependencies** -- it uses only the Python standard library.

### From GitHub

```bash
pip install git+https://github.com/mikylab/expTrack.git
```

### Local / development install

```bash
git clone https://github.com/mikylab/expTrack.git
cd expTrack
pip install -e .
```

### Virtual environment (recommended)

```bash
cd your_project/
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

pip install git+https://github.com/mikylab/expTrack.git
exptrack init
```

### Does expTrack affect other packages?

No. expTrack only activates when you explicitly use it:

- **`exptrack run`** / **`python -m exptrack`** -- patches argparse temporarily for the wrapped script only. Gone when the script exits.
- **`%load_ext exptrack`** / **`exptrack.notebook.start()`** -- registers an IPython hook in the current notebook session only.
- **`import exptrack`** -- does nothing on its own. No patches, no hooks, no side effects.

---

## Scripts

```bash
# Before:
python train.py --lr 0.01 --data train

# After:
exptrack run train.py --lr 0.01 --data train
# or:
python -m exptrack train.py --lr 0.01 --data train
```

**Your script needs zero modifications.** expTrack automatically:

- Captures argparse params the moment `parse_args()` is called
- Names the run: `train__lr0.01_datatrain__0312_a3f2`
- Snapshots `git diff HEAD` (catches uncommitted changes)
- Diffs the script against the last git commit and logs only changed lines
- Auto-links saved plots -- `plt.savefig("plot.png")` registers the file as an artifact
- Marks done/failed when the script exits

---

## Notebooks

### Setup

1. Install expTrack in your Jupyter kernel's Python:

```python
# Run this in a notebook cell
import sys
!{sys.executable} -m pip install -e /path/to/exptrack
```

2. Initialize your project (once):

```bash
exptrack init
```

### Option A: Magic extension (zero friction)

```python
%load_ext exptrack
```

That's it. A new experiment starts automatically on the first real cell execution. Every cell is snapshotted: source diff, changed variables, output.

**What gets captured automatically:**

- Variables that look like hyperparams (`lr`, `batch_size`, `epochs`, etc.) become experiment params
- Code changes are tracked -- editing `np.linspace(0, 10, 100)` to `np.linspace(0, 20, 200)` logs the diff
- Variable changes are logged with assignment context (e.g. `code = np.linspace(0, r, 100)  # ndarray(shape=(100,), dtype=float64)`)
- `plt.savefig()` calls auto-register plots as artifacts

**Magic commands:**

| Command | Description |
|---------|-------------|
| `%exp_status` | Show current experiment + params captured so far |
| `%exp_tag baseline` | Add a tag |
| `%exp_note "text"` | Add a note |
| `%exp_done` | Finish the experiment |
| `%exp_start` | Restart with a fresh experiment |

### Option B: Explicit API

```python
import exptrack.notebook as exp

run = exp.start(lr=0.001, bs=32)        # kwargs become experiment params
exp.metric("val/loss", 0.23, step=5)    # log a metric
path = exp.out("preds.csv")             # -> outputs/run_name/preds.csv
exp.done()                              # finish the experiment
```

### Using the explicit API with a model

Define hyperparameters as variables and pass them to both `exp.start()` and your model. The variables are the single source of truth -- expTrack just records them.

```python
import exptrack.notebook as exp
import torch
import torch.nn as nn

# 1. Define hyperparams (single source of truth)
lr = 0.001
bs = 32
epochs = 20
dropout = 0.3

# 2. Pass to exptrack
run = exp.start(lr=lr, bs=bs, epochs=epochs, dropout=dropout)

# 3. Use the same variables in your model
model = nn.Sequential(
    nn.Linear(784, 256),
    nn.ReLU(),
    nn.Dropout(dropout),
    nn.Linear(256, 10),
)
optimizer = torch.optim.Adam(model.parameters(), lr=lr)
train_loader = DataLoader(dataset, batch_size=bs)

# 4. Training loop
for epoch in range(epochs):
    for batch in train_loader:
        loss = train_step(model, batch, optimizer)
    val_loss = evaluate(model, val_loader)
    exp.metric("train/loss", loss, step=epoch)
    exp.metric("val/loss", val_loss, step=epoch)

# 5. Save model
path = exp.out("model.pt")
torch.save(model.state_dict(), path)
exp.done()
```

### Notebook API reference

| Function | Description |
|----------|-------------|
| `exp.start(name="", **params)` | Start experiment, kwargs become params. Returns `Experiment` |
| `exp.metric(key, value, step=None)` | Log a single metric |
| `exp.metrics(step=None, **kwargs)` | Log multiple metrics at once |
| `exp.param(key, value)` | Log a single param |
| `exp.tag(*tags)` | Add one or more tags |
| `exp.note(text)` | Append a note |
| `exp.artifact(path, label="")` | Register an existing file as artifact |
| `exp.out(filename)` | Get namespaced output path + register artifact |
| `exp.done()` | Finish the current experiment |
| `exp.current()` | Get the active `Experiment` or `None` |

---

## Shell / SLURM Pipelines

For multi-step pipelines where Python isn't the only language:

```bash
# Start experiment, get env vars back
eval $(exptrack run-start --script train --lr 0.01 --epochs 50)
# Now $EXP_ID, $EXP_NAME, $EXP_OUT are set

# Run your training
python train.py --lr 0.01 --epochs 50
# Save outputs to $EXP_OUT

# Log metrics mid-pipeline
exptrack log-metric $EXP_ID val_loss 0.234 --step 10
exptrack log-artifact $EXP_ID $EXP_OUT/model.pt --label model

# Finish
exptrack run-finish $EXP_ID --metrics results.json
# or on failure:
exptrack run-fail $EXP_ID "OOM on node gpu03"
```

SLURM environment variables (`SLURM_JOB_ID`, etc.) are captured automatically.

---

## Web Dashboard

```bash
exptrack ui                    # opens http://localhost:7331
exptrack ui --port 8080        # custom port
```

No external dependencies -- uses stdlib `http.server` and Chart.js from CDN.

### Features

**Experiment list** -- filterable by status, searchable by name/tag/param. Unified metrics column shows both auto-captured metrics and manually logged results with sparkline mini-charts inline.

**Experiment detail** -- summary card, params table, code changes, variables grouped by type, unified metrics & results view with source badges (`auto`/`manual`), interactive Chart.js plots, artifacts with type badges, git diff viewer. Includes a **Reproduce** box with the full command and a one-click copy button.

**Timeline view** -- chronological event log showing cell executions, variable changes, and artifact creation. Click "view source" to see full cell code with diffs. Filter by event type (Code, Variables, Artifacts, Observational).

**Compare view** -- two modes:
- **Pair Compare** -- side-by-side param, variable, and metric comparison between two experiments with overlay line charts showing metric trends. Toggle "show only differences" to focus on what changed.
- **Multi Compare** -- select 2+ experiments from the list or use the built-in multi-select picker to see bar charts comparing metrics/results across all selected runs, plus a summary comparison table.

**Inline editing** -- double-click any name, tag, or note field to edit directly. No modal prompts. Works in both the table view and detail view.

**Tag autocomplete** -- when adding tags, a dropdown shows previously used tags with usage counts.

**Export** -- JSON, Markdown, or Plain Text. "Copy as Text" includes full details (params, metrics, tags, notes, git info).

**Timezone selector** -- configure your preferred timezone in the header. All timestamps update accordingly. Saved to project config.

---

## Managing Experiments

### List and inspect

```bash
exptrack ls                   # last 20 experiments
exptrack ls -n 50             # last 50
exptrack show <id>            # full details
exptrack show <id> --timeline # with execution timeline
exptrack diff <id>            # colorized git diff
exptrack compare <id1> <id2>  # side-by-side comparison
exptrack history <notebook>   # notebook cell snapshot history
```

### Tag and annotate

```bash
exptrack tag <id> baseline    # add tag
exptrack untag <id> baseline  # remove tag
exptrack note <id> "tried higher dropout, worse results"
```

Notes are appended -- you can call `note` multiple times.

### Delete and clean up

```bash
exptrack rm <id>              # delete single run (with confirmation)
exptrack clean                # bulk-delete all failed runs
exptrack stale --hours 24     # mark old running experiments as timed-out
```

### Link artifacts after the fact

```bash
exptrack log-artifact <id> path/to/model.pt --label "best model"
```

### Export

```bash
exptrack export <id>                    # JSON to stdout
exptrack export <id> --format markdown  # Markdown
```

### Verify artifact integrity

```bash
exptrack verify <id>          # check file hashes (ok/missing/modified)
exptrack verify --backfill    # backfill hashes for legacy artifacts
```

### Storage info

```bash
exptrack storage              # DB size, output size, row counts, optimization tips
```

---

## CLI Reference

```
Project setup
  exptrack init [name]              Initialize project, patch .gitignore
  exptrack init --here              Initialize in current dir (not git root)

Script tracking
  exptrack run script.py [args]     Run script with automatic tracking

Shell/SLURM pipeline
  exptrack run-start [--key val]    Start experiment, print env vars for eval $()
  exptrack run-finish <id>          Mark done (--metrics file.json)
  exptrack run-fail <id> [reason]   Mark failed
  exptrack log-metric <id> <k> <v>  Log metric (--step N, --file f.json)
  exptrack log-artifact <id> <path> Register output file (--label name)

Inspection
  exptrack ls [-n 50]               List experiments
  exptrack show <id> [--timeline]   Full details (params, metrics, artifacts, diff)
  exptrack timeline <id> [-c]       Execution timeline (--type event_type)
  exptrack diff <id>                Colorized git diff captured at run time
  exptrack compare <id1> <id2>      Side-by-side params + metrics
  exptrack history <nb> [id]        Notebook cell snapshot history
  exptrack export <id> [--format]   Export as JSON or Markdown
  exptrack verify [id] [--backfill] Check artifact file integrity

Management
  exptrack tag <id> <tag>           Add tag
  exptrack untag <id> <tag>         Remove tag
  exptrack delete-tag <tag>         Delete a tag from all experiments
  exptrack note <id> "text"         Append note
  exptrack edit-note <id> "text"    Replace notes
  exptrack rm <id>                  Delete run
  exptrack clean [--baselines]      Remove all failed runs (or clear baselines)
  exptrack finish <id>              Manually mark running experiment as done
  exptrack stale --hours 24         Mark old running experiments as timed-out

Admin
  exptrack upgrade [--reinstall]    Run schema migrations
  exptrack storage                  Show storage breakdown and optimization tips
  exptrack ui [--port 7331]         Launch web dashboard
```

---

## Configuration

expTrack stores config in `.exptrack/config.json`. This file is safe to commit (no secrets).

```jsonc
{
  // Database and storage paths
  "db":                    ".exptrack/experiments.db",
  "outputs_dir":           "outputs",
  "notebook_history_dir":  ".exptrack/notebook_history",

  // Limits
  "max_git_diff_kb":       256,        // skip diffs larger than this
  "hash_max_mb":           500,        // partial-hash files larger than this

  // Artifact handling
  "artifact_strategy":     "reference", // "reference" or "copy"
  "protect_on_rerun":      true,        // archive old artifacts on path conflict

  // Timezone for dashboard display
  "timezone":              "",          // "" = UTC, or "America/New_York", etc.

  // Auto-capture toggles
  "auto_capture": {
    "argparse":  true,                  // patch ArgumentParser.parse_args()
    "argv":      true,                  // fallback: parse raw sys.argv
    "notebook":  true                   // capture notebook cell changes
  },

  // Run naming
  "naming": {
    "max_param_keys": 4,                // max params included in run name
    "key_max_len":    8                  // param key length limit in name
  },

  // Plugins
  "plugins": {
    "enabled": []                       // list of plugin module names
  }
}
```

---

## Plugins

Plugins run your code automatically when experiments start, finish, fail, or log metrics. You never call them directly.

### Use cases

- **Slack/email alerts** -- get notified when a run finishes or crashes
- **Cloud upload** -- auto-upload checkpoints to S3/GCS on completion
- **Shared experiment log** -- sync metadata to a shared database or GitHub repo
- **Auto-cleanup** -- delete old checkpoints when a new best model is found

### Writing a plugin

```python
# exptrack/plugins/slack_notify.py
import json
import urllib.request
from exptrack.plugins import Plugin

class SlackNotify(Plugin):
    name = "slack_notify"

    def __init__(self, config):
        self.webhook = config.get("webhook_url", "")

    def on_finish(self, exp):
        self._post(f"Run *{exp.name}* finished in {exp.duration_s:.0f}s")

    def on_fail(self, exp, error):
        self._post(f"Run *{exp.name}* FAILED: {error}")

    def _post(self, text):
        if not self.webhook:
            return
        data = json.dumps({"text": text}).encode()
        urllib.request.urlopen(
            urllib.request.Request(self.webhook, data,
                                  {"Content-Type": "application/json"})
        )

plugin_class = SlackNotify
```

### Plugin lifecycle hooks

| Hook | When it runs |
|------|-------------|
| `on_start(self, exp)` | Experiment created |
| `on_finish(self, exp)` | Experiment completed successfully |
| `on_fail(self, exp, error)` | Experiment failed |
| `on_metric(self, exp, key, value, step)` | Metric logged |

Override only the hooks you need.

### Enabling a plugin

Add to `.exptrack/config.json`:

```json
{
  "plugins": {
    "enabled": ["slack_notify"],
    "slack_notify": {
      "webhook_url": "https://hooks.slack.com/services/T.../B.../xxx"
    }
  }
}
```

### Built-in: GitHub Sync

Appends one JSON line per run to a file in your GitHub repo -- params, metrics, run name, commit hash.

```json
{
  "plugins": {
    "enabled": ["github_sync"],
    "github_sync": {
      "repo":      "yourname/yourrepo",
      "file":      "experiment_log/runs.jsonl",
      "branch":    "main",
      "token_env": "GITHUB_TOKEN"
    }
  }
}
```

---

## Python API

For programmatic use beyond the notebook API:

```python
from exptrack.core import Experiment

# Context manager (auto finish/fail)
with Experiment(name="my_run", params={"lr": 0.01}) as exp:
    exp.log_metric("loss", 0.5, step=1)
    exp.log_metric("loss", 0.3, step=2)
    path = exp.save_output("model.pt")
    torch.save(model.state_dict(), path)

# Manual lifecycle
exp = Experiment(params={"lr": 0.01})
exp.log_params({"optimizer": "adam", "scheduler": "cosine"})
exp.log_metrics({"val_loss": 0.23, "val_acc": 0.91}, step=10)
exp.add_tag("baseline")
exp.add_note("first run with new architecture")
exp.log_artifact("outputs/plot.png", label="training curve")
exp.finish()
```

### Experiment properties

| Property | Description |
|----------|-------------|
| `exp.id` | Unique 12-char hex identifier |
| `exp.name` | Run name (auto-generated or custom) |
| `exp.status` | `"running"`, `"done"`, or `"failed"` |
| `exp.created_at` | ISO timestamp |
| `exp.duration_s` | Duration in seconds (set on finish) |
| `exp.script` | Script path |
| `exp.git_branch` | Git branch at run time |
| `exp.git_commit` | Git commit hash at run time |
| `exp.git_diff` | Full uncommitted diff |
| `exp.tags` | List of tags |
| `exp.notes` | Freeform notes string |

### Experiment methods

| Method | Description |
|--------|-------------|
| `log_param(key, value)` | Log a single parameter |
| `log_params(dict)` | Log multiple parameters |
| `log_metric(key, value, step=None)` | Log a metric value |
| `log_metrics(dict, step=None)` | Log multiple metrics |
| `last_metrics()` | Get latest value for each metric key |
| `add_tag(tag)` | Add a tag |
| `remove_tag(tag)` | Remove a tag |
| `add_note(text)` | Append text to notes |
| `set_note(text)` | Replace notes entirely |
| `output_path(filename)` | Get namespaced path (no artifact registration) |
| `save_output(filename)` | Get namespaced path + register as artifact |
| `log_artifact(path, label="")` | Register an existing file |
| `finish()` | Mark as done |
| `fail(error="")` | Mark as failed |

---

## How It Works

### Capture mechanisms

**Argparse patching** -- expTrack monkey-patches `ArgumentParser.parse_args()` and `parse_known_args()` before your script runs. When your script calls `parser.parse_args()`, expTrack intercepts the result and logs all arguments as params. The patch is removed when the script exits. If your script doesn't use argparse, expTrack falls back to parsing raw `sys.argv`.

**Notebook hooks** -- `%load_ext exptrack` registers an IPython `post_run_cell` hook. After every cell execution, the hook:
1. Computes a content-addressed hash of the cell source
2. Diffs the cell against its parent version (30% similarity threshold)
3. Scans the namespace for new/changed variables
4. Enriches variable displays with assignment expressions from the cell source
5. Logs timeline events for code changes, variable changes, and observational cells

**Matplotlib patching** -- `plt.savefig()` and `Figure.savefig()` are patched to copy saved figures into the experiment's output directory and register them as artifacts. Figures saved before the experiment starts are buffered and flushed when it begins.

### Storage design

- **Diff-only** -- script changes are diffed against `git HEAD`; notebook snapshots store only cell diffs and variable change hashes. No full-source copies.
- **Per-project** -- database and notebook history live in `.exptrack/` (gitignored). Config is committable.
- **SQLite WAL mode** -- safe for concurrent reads. Single file, queryable, portable.
- **Content-addressed cell lineage** -- notebook cells are identified by SHA-256 of their source content, enabling accurate tracking across cell reordering and splits.

### Database schema

| Table | Purpose |
|-------|---------|
| `experiments` | Run metadata, git state, status, timestamps |
| `params` | Key-value parameters (JSON-stringified values) |
| `metrics` | Float values with optional step and timestamp |
| `artifacts` | Output file paths with content hashes and size |
| `timeline` | Execution events (cell_exec, var_set, artifact, metric, observational) |
| `cell_lineage` | Content-addressed notebook cell history |
| `code_baselines` | Position-based cell baselines (legacy) |

---

## expTrack vs. TensorBoard

| | expTrack | TensorBoard |
|---|---|---|
| **Dependencies** | Zero (stdlib only) | TensorFlow/tensorboard + protobuf |
| **Code changes** | None required | Must add `SummaryWriter` calls everywhere |
| **Auto-captures** | Params, git state, full diff, cell diffs, variable changes | Nothing automatic |
| **Storage** | SQLite (one file, queryable, portable) | Protobuf event files (need TB to read) |
| **Experiment management** | Built-in: `ls`, `show`, `diff`, `compare`, `tag`, `note`, `rm`, `clean` | None -- TB is a viewer only |
| **Reproducibility** | Full `git diff` at run time | No git integration |
| **Shell/SLURM** | First-class: `eval $(exptrack run-start ...)` | Not designed for non-Python workflows |
| **Rich media** | No (metrics, params, artifacts only) | Yes (images, audio, histograms, graphs) |

**They work together** -- use expTrack for "what params and code produced this run" and TensorBoard for rich media visualization. They don't conflict.

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'exptrack'`

expTrack is not installed in the Python environment you're using.

**In Jupyter notebooks**, the kernel's Python is often different from your shell's Python:

```python
import sys
!{sys.executable} -m pip install -e /path/to/exptrack
```

Then **restart the kernel**.

**In scripts**, use the same Python you run scripts with:

```bash
python -m pip install -e /path/to/exptrack
```

### `exptrack init` created `.exptrack/` in the wrong place

`exptrack init` walks up from your current directory looking for `.git/`. If you're inside a larger git repo, `.exptrack/` ends up at the git root. Force creation in the current directory:

```bash
exptrack init --here
```

### Experiments not showing up

expTrack stores data in `.exptrack/experiments.db` relative to the project root. If you run scripts from a different directory than where you initialized, expTrack may create a new `.exptrack/` elsewhere. Always run from within your project directory.

---

## Project Layout

```
exptrack/
  pyproject.toml              pip install -e .
  README.md                   this file
  CHANGELOG.md                version history
  CLAUDE.md                   AI assistant context
  exptrack/
    __init__.py               public API, load_ipython_extension entry point
    __main__.py               python -m exptrack (wraps scripts via runpy)
    config.py                 project-aware config, root detection
    notebook.py               %load_ext magic + explicit API
    core/
      experiment.py           Experiment class, lifecycle, logging
      db.py                   SQLite schema, migrations, WAL mode
      naming.py               Run name generation
      hashing.py              File integrity hashing
      git.py                  Git state capture
      artifact_protection.py  Artifact archiving on rerun conflicts
    capture/
      __init__.py             Module re-exports
      argparse_patch.py       Argparse monkey-patch
      matplotlib_patch.py     plt.savefig() auto-linking
      notebook_hooks.py       IPython post_run_cell hook
      cell_lineage.py         Content-addressed cell tracking
      variables.py            Variable fingerprinting and classification
      script_tracking.py      Git diff capture for scripts
    cli/
      main.py                 Argument parsing, subcommand dispatch
      pipeline_cmds.py        run-start, run-finish, run-fail, log-metric, log-artifact
      inspect_cmds.py         ls, show, diff, compare, history, timeline, export, verify
      mutate_cmds.py          tag, untag, note, edit-note, rm, finish
      admin_cmds.py           clean, stale, upgrade, storage
    plugins/
      __init__.py             Plugin base class + event registry
      github_sync.py          GitHub metadata sync (JSONL)
    dashboard/
      app.py                  Web server entry point
      handler.py              HTTP request handler, dispatches to routes
      static.py               Assembler: imports parts into DASHBOARD_HTML
      static_parts/
        html.py               HTML structure (HEAD, BODY, FOOTER)
        styles.py             CSS re-exports from css/
        scripts.py            JS re-exports from js/
        css/                  12 CSS modules (reset, layout, cards, table, ...)
        js/                   15 JS modules (core, sidebar, detail, compare, ...)
      routes/
        read_routes.py        GET API endpoints
        write_routes.py       POST API endpoints
```

---

## Contributing

Contributions are welcome! Here's how to get started:

1. Fork the repository and clone your fork
2. Create a virtual environment and install in development mode:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
3. Create a branch for your change (`git checkout -b my-feature`)
4. Make your changes -- remember, **stdlib only** (no external dependencies)
5. Commit and push to your fork
6. Open a pull request against `main`

### Guidelines

- **No external dependencies.** Every import must come from the Python standard library.
- **Keep functions focused.** If a function exceeds ~40 lines, consider splitting it.
- **Error boundaries.** Wrap external operations (file I/O, git, plugin calls) in try/except. Never let a capture failure crash the user's training script.
- **Dashboard changes.** Keep existing JS function signatures stable. Use `api()` / `postApi()` helpers for API calls. Follow the inline-editing pattern for new UI features.

---

## License

expTrack is released under the [MIT License](https://opensource.org/licenses/MIT).
