# exptrack v2

Local-first experiment tracker. Zero changes to your existing scripts.

---

## Installation

```bash
pip install -e /path/to/exptrack
```

**Important:** Install using the same Python that your tools use. If you use Jupyter,
install into the Jupyter kernel's Python (see [Notebook setup](#notebooks) below).

---

## Setup (once per project)

```bash
cd your_project/
exptrack init
```

This creates `.exptrack/` at your project root (the nearest parent directory
containing `.git/`) and patches `.gitignore`:

```
.exptrack/experiments.db        <-- local only, never pushed
.exptrack/notebook_history/     <-- local only, never pushed
.exptrack/config.json           <-- commit this (no secrets)
outputs/                        <-- gitignored (large files live here)
```

If your working directory is inside a larger git repo and you want `.exptrack/`
in the current directory instead of the git root, use:

```bash
exptrack init --here
```

---

## Scripts -- zero changes needed

```bash
# Before:
python train.py --lr 0.01 --data train

# After:
exptrack run train.py --lr 0.01 --data train
# or:
python -m exptrack train.py --lr 0.01 --data train
```

exptrack automatically:
- Captures argparse params the moment `parse_args()` is called
- Names the run: `train__lr0.01_datatrain__0312_a3f2`
- Snapshots `git diff HEAD` (catches uncommitted changes)
- Marks done/failed when the script exits

**Your script needs zero modifications.**

---

## Shell / SLURM pipelines

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

## Notebooks

### Step 1: Install exptrack in your Jupyter kernel

exptrack must be installed in the **same Python environment** as your Jupyter
kernel. If you get `ModuleNotFoundError: No module named 'exptrack'`, this is
almost always the cause.

**From inside a notebook cell:**
```python
import sys
!{sys.executable} -m pip install -e /path/to/exptrack
```

This uses the notebook kernel's own Python, which may be different from the
`pip` or `python` on your shell PATH.

**Or from a terminal**, find the kernel's Python first:
```bash
# List Jupyter kernels and their Python paths
jupyter kernelspec list
# Then install with that specific Python
/path/to/kernel/python -m pip install -e /path/to/exptrack
```

### Step 2: Initialize exptrack in your project

Run this once (from a terminal or notebook cell):
```bash
cd /path/to/your/project
exptrack init
```

Or from a notebook cell:
```python
!cd /path/to/your/project && exptrack init
```

### Step 3: Use exptrack in your notebook

**Option A: Magic extension (zero friction)**

```python
%load_ext exptrack
```

That's it. A new experiment starts automatically. Every cell execution is
snapshotted: source diff, changed variables, output. Variables that look like
hyperparams (`lr`, `batch_size`, `epochs`, etc.) are auto-captured as params.

Magic commands:
```
%exp_status          show current experiment + params captured so far
%exp_tag baseline    add a tag
%exp_note "text"     add a note
%exp_done            finish experiment
%exp_start           restart with a fresh experiment
```

**Option B: Explicit API**

```python
import exptrack.notebook as exp

run = exp.start(lr=0.001, bs=32)   # kwargs become experiment params
exp.metric("val/loss", 0.23, step=5)
path = exp.out("preds.csv")        # -> outputs/run_name/preds.csv
exp.done()
```

### Step 4: View your experiments

```bash
exptrack ls          # list all experiments
exptrack show <id>   # full details for a run
```

---

## CLI reference

```bash
# Project setup
exptrack init [name]              init project, patch .gitignore
exptrack init --here              init in current dir (not git root)

# Script tracking
exptrack run script.py [args]     run with tracking

# Shell/SLURM pipeline
exptrack run-start [--key val]    start experiment, print env vars
exptrack run-finish <id>          mark done (--metrics file.json)
exptrack run-fail <id> [reason]   mark failed
exptrack log-metric <id> <k> <v>  log metric (--step N, --file f.json)
exptrack log-artifact <id> <path> register output file (--label name)

# Inspection
exptrack ls [-n 50]               list experiments
exptrack show <id>                params, metrics, outputs, diff size
exptrack diff <id>                colorized git diff captured at run time
exptrack compare <id1> <id2>      side-by-side params + metrics
exptrack history <nb> [id]        notebook cell snapshots

# Management
exptrack tag <id> <tag>           add tag
exptrack note <id> "text"         add note
exptrack rm <id>                  delete run
exptrack clean                    remove all failed runs
exptrack stale --hours 24         mark old running experiments as failed
exptrack upgrade [--reinstall]    run schema migrations

# Dashboard
exptrack ui [--port 7331]         web dashboard
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'exptrack'`

This means exptrack is not installed in the Python environment you're using.

**In Jupyter notebooks**, the kernel's Python is often different from your
shell's Python. Fix it by installing from inside a notebook cell:

```python
import sys
!{sys.executable} -m pip install -e /path/to/exptrack
```

Then **restart the kernel** and try again.

**In scripts**, make sure you installed with the same Python you're running:
```bash
python -m pip install -e /path/to/exptrack   # use the same 'python' you run scripts with
```

### `exptrack init` didn't create `.exptrack/` where I expected

`exptrack init` creates `.exptrack/` at the project root, which it finds by
walking up from your current directory looking for `.git/`. If your directory
is inside a larger git repo, `.exptrack/` ends up at the git root.

To force creation in your current directory:
```bash
exptrack init --here
```

### Experiments not showing up / wrong database

exptrack stores data in `.exptrack/experiments.db` relative to the project root.
If you run scripts from a different directory than where you initialized, exptrack
may create a new `.exptrack/` directory elsewhere.

Always run scripts from within your project directory (the one with `.exptrack/`).

---

## GitHub sync (optional)

Appends one JSON line per run to a file in your repo -- params, metrics,
run name, commit hash, diff line count. Never large files.

In `.exptrack/config.json`:
```json
{
  "plugins": {
    "enabled": ["github_sync"],
    "github_sync": {
      "repo":      "yourname/NewCode1",
      "file":      "experiment_log/runs.jsonl",
      "branch":    "main",
      "token_env": "GITHUB_TOKEN"
    }
  }
}
```

```bash
export GITHUB_TOKEN=ghp_yourtoken
```

Now every run auto-syncs metadata to `experiment_log/runs.jsonl` in your repo --
searchable history with no large files ever touching GitHub.

---

## Adding a plugin

```python
# exptrack/plugins/myplugin.py
from exptrack.plugins import Plugin

class MyPlugin(Plugin):
    name = "myPlugin"
    def __init__(self, config): ...
    def on_finish(self, exp): ...   # fires when run completes

plugin_class = MyPlugin
```

Add `"myPlugin"` to `"enabled"` in config. No other changes needed.

---

## Project layout

```
exptrack/
  pyproject.toml          pip install -e .
  README.md               this file
  CLAUDE.md               AI assistant context
  exptrack/
    __init__.py            public API
    __main__.py            python -m exptrack entrypoint
    core.py                Experiment class + DB schema
    config.py              project-aware config (finds .git root automatically)
    cli.py                 terminal interface (18+ commands)
    notebook.py            %load_ext + explicit API
    capture/
      __init__.py          argparse patch + notebook cell hooks
    plugins/
      __init__.py          Plugin base class + event registry
      github_sync.py       GitHub metadata sync
    dashboard/
      app.py               web UI (stdlib http.server + Chart.js)
```
