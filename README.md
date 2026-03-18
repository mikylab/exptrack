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
- **Auto artifact linking** -- `plt.savefig()` is monkey-patched so saved plots auto-register as artifacts
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

## What Gets Captured

expTrack works in four modes. Here's what each captures automatically vs. what you log yourself:

| | `exptrack run` (scripts) | `%load_ext exptrack` (notebooks) | Shell / SLURM | Python API |
|---|---|---|---|---|
| **How you use it** | `exptrack run train.py --lr 0.01` | `%load_ext exptrack` in first cell | `eval $(exptrack run-start ...)` | `with Experiment() as exp:` |
| **Parameters** | Auto from argparse / sys.argv | Auto from HP-like variables (`lr`, `batch_size`, etc.) | You pass them: `--lr 0.01` | You log them: `exp.log_param()` |
| **Metrics** | You log them via `__exptrack__` global | You log them: `exp.metric()` | You log them: `exptrack log-metric` | You log them: `exp.log_metric()` |
| **Git state** | Auto (branch, commit, diff) | Auto (branch, commit, diff) | Auto (branch, commit, diff) | Auto (branch, commit, diff) |
| **Code changes** | Auto (script diff vs last commit) | Auto (cell diffs, variable changes) | Not captured | Not captured |
| **Artifacts** | Auto (`plt.savefig` + new files) | Auto (`plt.savefig`) | You log them: `exptrack log-artifact` | You log them: `exp.log_artifact()` |
| **Status** | Auto (done/failed on exit) | You call `exp.done()` or `%exp_done` | You call `run-finish` or `run-fail` | Auto with context manager, or `exp.finish()` |

**Key takeaway:** Parameters, git state, and artifacts are mostly automatic. **Metrics always need explicit logging** -- exptrack can't guess which numbers matter to you.

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

### Logging metrics from a wrapped script

`exptrack run` auto-captures **parameters** and **artifacts**, but metrics (loss, accuracy, etc.) need to be logged explicitly. When your script runs under `exptrack run`, an `__exptrack__` global is injected into the script's namespace with the active `Experiment` object:

```python
# No imports needed — works only under `exptrack run`
exp = globals().get("__exptrack__")

for epoch in range(epochs):
    loss, acc = train(...)

    if exp:
        # Single metric
        exp.log_metric("loss", loss, step=epoch)

        # Multiple metrics at once (same step applied to all)
        exp.log_metrics({"loss": loss, "accuracy": acc}, step=epoch)
```

The `globals().get()` pattern keeps your script portable -- it still runs with plain `python train.py` (metrics are just skipped). See [`examples/basic_script.py`](examples/basic_script.py) for a full example.

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
eval $(exptrack run-start --script train.py --lr 0.01 --epochs 50)
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

### Multi-step pipelines

Each `run-start` creates a **separate experiment**. For pipelines with multiple scripts (train, test, analyze), call `run-start`/`run-finish` for each step. Save each `$EXP_ID` before the next `run-start` overwrites it.

Use `--study` to group related steps into a study, and `--stage` to number them:

```bash
STUDY="resnet-ablation-$(date +%s)"

# Step 1: Train
eval $(exptrack run-start --script train.py --study "$STUDY" --stage 1 --stage-name train \
      --lr 0.01 --epochs 50)
TRAIN_ID=$EXP_ID
python train.py --train --lr 0.01
exptrack log-metric $TRAIN_ID loss 0.23 --step 100
exptrack run-finish $TRAIN_ID --metrics results.json

# Step 2: Test
eval $(exptrack run-start --script train.py --study "$STUDY" --stage 2 --stage-name test)
TEST_ID=$EXP_ID
python train.py --test
exptrack log-metric $TEST_ID accuracy 0.94
exptrack run-finish $TEST_ID

# Step 3: Analyze
eval $(exptrack run-start --script analyze.py --study "$STUDY" --stage 3 --stage-name analyze)
ANALYZE_ID=$EXP_ID
python analyze.py
exptrack log-artifact $ANALYZE_ID report.pdf --label "analysis"
exptrack run-finish $ANALYZE_ID
```

Filter by study in the dashboard or CLI (`exptrack ls --study <name>`) to see all steps together. You can also manage studies after the fact with `exptrack study <id> <name>` and `exptrack studies`. See [`examples/pipeline_multistep.sh`](examples/pipeline_multistep.sh) for a full working example.

**Studies vs tags:** Studies group experiments that belong together (pipeline steps, ablation runs). Tags are categorical labels (`baseline`, `production`, `slow`). An experiment can have both.

---

## Logging Metrics

Metrics (loss, accuracy, F1, etc.) always need explicit logging -- expTrack can't guess which numbers matter to you. There are two ways to log them: **one at a time** or **multiple at once**. The API is the same regardless of how you run expTrack.

### Single metric: `log_metric(key, value, step=None)`

```python
exp.log_metric("loss", 0.42, step=epoch)
```

### Multiple metrics: `log_metrics(dict, step=None)`

Pass a dictionary. The `step` is applied to all values:

```python
exp.log_metrics({
    "train_loss": 0.42,
    "val_loss": 0.38,
    "accuracy": 0.91,
}, step=epoch)
```

### How you get `exp` depends on your mode

| Mode | How to get the experiment object | Metric call |
|------|----------------------------------|-------------|
| **`exptrack run`** | `exp = globals().get("__exptrack__")` | `exp.log_metric(...)` / `exp.log_metrics(...)` |
| **Python API** | `with Experiment() as exp:` or `exp = Experiment()` | `exp.log_metric(...)` / `exp.log_metrics(...)` |
| **Notebook (explicit)** | `import exptrack.notebook as exp` | `exp.metric(key, val)` / `exp.metrics(step=N, loss=0.5, acc=0.9)` |
| **Shell / SLURM** | N/A (use CLI commands instead) | `exptrack log-metric $EXP_ID key value --step N` |

### Full examples by mode

**`exptrack run`** -- your script is wrapped, no imports needed:
```python
exp = globals().get("__exptrack__")
for epoch in range(epochs):
    loss, acc = train(...)
    if exp:
        exp.log_metrics({"loss": loss, "accuracy": acc}, step=epoch)
```

**Python API** -- you create the experiment yourself:
```python
from exptrack.core import Experiment

with Experiment(params={"lr": 0.01}) as exp:
    for epoch in range(epochs):
        loss, acc = train(...)
        exp.log_metrics({"loss": loss, "accuracy": acc}, step=epoch)
```

**Notebook** -- using the explicit API:
```python
import exptrack.notebook as exp
exp.start(lr=0.001)

# Single
exp.metric("val/loss", 0.23, step=5)

# Multiple (keyword arguments, not a dict)
exp.metrics(step=10, train_loss=0.5, val_loss=0.3, accuracy=0.91)

exp.done()
```

**Shell / SLURM** -- from the command line:
```bash
eval $(exptrack run-start --lr 0.01)

# Single metric
exptrack log-metric $EXP_ID loss 0.42 --step 10

# Multiple from a JSON file
echo '{"loss": 0.42, "accuracy": 0.91}' > metrics.json
exptrack log-metric $EXP_ID --file metrics.json --step 10

# Or log metrics when finishing
exptrack run-finish $EXP_ID --metrics results.json
```

### The `step` parameter

`step` is optional but recommended for time-series data. It enables sparkline charts in the dashboard and proper line plots in the detail view. Typical usage: pass the epoch or batch number.

```python
# Without step — just logs the final value
exp.log_metric("final_accuracy", 0.94)

# With step — tracks the metric over time
for epoch in range(100):
    exp.log_metric("loss", loss, step=epoch)
```

### Nested JSON metrics (CLI only)

When logging from a JSON file, nested dicts are flattened with `/` separators:

```json
{"train": {"loss": 0.5, "acc": 0.9}, "val": {"loss": 0.3, "acc": 0.92}}
```

Becomes: `train/loss`, `train/acc`, `val/loss`, `val/acc`.

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

**Images** -- image artifacts are displayed in a gallery grid under the Images tab. Click thumbnails for full-size lightbox. Pair Compare supports side-by-side, overlay (opacity slider), and swipe comparison modes.

**Data Files** -- CSV, TSV, JSON, and JSONL artifacts are rendered as interactive tables under the Data Files tab. Auto-detected by file extension with sortable columns.

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

## Examples

The [`examples/`](examples/) directory contains ready-to-run scripts. Install exptrack first (`pip install -e .`), then:

| Example | What it shows |
|---------|---------------|
| [`basic_script.py`](examples/basic_script.py) | Zero-friction tracking -- no exptrack imports, just wrap with `exptrack run` |
| [`manual_tracking.py`](examples/manual_tracking.py) | Explicit Python API -- `Experiment` context manager, params, metrics, tags |
| [`notebook_example.py`](examples/notebook_example.py) | Notebook workflow via `exptrack.notebook` |
| [`pipeline_example.sh`](examples/pipeline_example.sh) | Shell/SLURM pipeline with `eval $(exptrack run-start ...)` |
| [`pipeline_multistep.sh`](examples/pipeline_multistep.sh) | Multi-step pipeline: train → test → analyze as separate experiments |

```bash
# Install and initialize
pip install -e .
exptrack init

# Copy an example into your project, then run it
cp examples/basic_script.py .
exptrack run basic_script.py --lr 0.01 --epochs 10
exptrack ls
```

---

## Further Documentation

Detailed docs are in the [`docs/`](docs/) directory:

- [CLI Reference](docs/cli-reference.md) -- full list of all 24 subcommands
- [Configuration](docs/configuration.md) -- `.exptrack/config.json` options
- [Python API](docs/python-api.md) -- `Experiment` class properties and methods
- [Plugins](docs/plugins.md) -- writing and enabling plugins, GitHub Sync
- [How It Works](docs/how-it-works.md) -- capture mechanisms, storage design, database schema, comparison with TensorBoard
- [FAQ](docs/faq.md) -- common questions about scripts, notebooks, artifacts, performance
- [Troubleshooting](docs/troubleshooting.md) -- solutions for common issues
- [Contributing](docs/contributing.md) -- development setup, linting, testing, guidelines

---

## Project Layout

```
exptrack/
  pyproject.toml              pip install -e .
  README.md                   this file
  CHANGELOG.md                version history
  CLAUDE.md                   AI assistant context
  docs/                       detailed documentation
  examples/                   ready-to-run example scripts
  exptrack/
    __init__.py               public API, load_ipython_extension entry point
    py.typed                  PEP 561 type checking marker
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
      argparse_patch.py       Argparse monkey-patch
      matplotlib_patch.py     plt.savefig() auto-linking
      notebook_hooks.py       IPython post_run_cell hook
      cell_lineage.py         Content-addressed cell tracking
      variables.py            Variable fingerprinting and classification
      script_tracking.py      Git diff capture for scripts
    cli/
      main.py                 Argument parsing, subcommand dispatch
      pipeline_cmds.py        run-start, run-finish, run-fail
      inspect_cmds.py         ls, show, diff, compare, history
      mutate_cmds.py          tag, untag, note, rm, finish
      admin_cmds.py           clean, stale, upgrade, storage
    plugins/
      __init__.py             Plugin base class + event registry
      github_sync.py          GitHub metadata sync (JSONL)
    dashboard/
      app.py                  Web server entry point
      handler.py              HTTP request handler
      static.py               Assembler: imports parts into DASHBOARD_HTML
      static_parts/           CSS, JS, HTML modules
      routes/                 GET and POST API endpoints
```

---

## License

expTrack is released under the [MIT License](https://opensource.org/licenses/MIT).
