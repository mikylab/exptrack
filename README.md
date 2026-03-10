# exptrack v2

Local-first experiment tracker. Zero changes to your existing scripts.

---

## Setup (once per project)

```bash
pip install -e /path/to/exptrack

cd NewCode1/
exptrack init
```

This creates `.exptrack/` inside your project and patches `.gitignore`:
```
.exptrack/experiments.db        ← local only, never pushed
.exptrack/notebook_history/     ← local only, never pushed  
.exptrack/config.json           ← commit this (no secrets)
outputs/                        ← gitignored (large files live here)
```

---

## Scripts — zero changes needed

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

## Notebooks — one line

```python
%load_ext exptrack
```

Every cell execution is then snapshotted: source diff, changed variables, output.
Variables that look like hyperparams (`lr`, `batch_size`, `epochs`, etc.) are
auto-captured as experiment params.

Magic commands:
```
%exp_status          show current experiment + params captured so far
%exp_tag baseline    add a tag
%exp_note "text"     add a note
%exp_done            finish experiment
%exp_start           restart with a fresh experiment
```

Explicit API:
```python
import exptrack.notebook as exp

run = exp.start(lr=0.001, bs=32)
exp.metric("val/loss", 0.23, step=5)
path = exp.out("preds.csv")   # → outputs/run_name/preds.csv
exp.done()
```

---

## Typical workflow

```
# Repo at start: train.py has model(lr=0.1)

exptrack run train.py --lr 0.01 --data train    # run 1 → train__lr0.01__0312_a3f2
exptrack run train.py --lr 0.001 --data train   # run 2 → train__lr0.001__0312_b7c1

# Notebook:
%load_ext exptrack
show(model1)    # cell snapshotted: source, output, vars
show(model2)    # cell snapshotted: linked to active experiment
%exp_done
```

Now you can always answer:
- *What produced model1?* → `exptrack show a3f2`
- *What code was running?* → `exptrack diff a3f2`
- *What changed between runs?* → `exptrack compare a3f2 b7c1`
- *What did ExploreResults.ipynb do?* → `exptrack history ExploreResults b7c1`

---

## CLI reference

```bash
exptrack init [name]              init project, patch .gitignore
exptrack run script.py [args]     run with tracking
exptrack ls [-n 50]               list experiments
exptrack show <id>                params, metrics, outputs, diff size
exptrack diff <id>                colorized git diff captured at run time
exptrack compare <id1> <id2>      side-by-side params + metrics
exptrack history <nb> [id]        notebook cell snapshots
exptrack tag <id> <tag>           add tag
exptrack note <id> "text"         add note
exptrack rm <id>                  delete run
exptrack clean                    remove all failed runs
exptrack ui                       web dashboard → http://localhost:7331
```

---

## GitHub sync (optional)

Appends one JSON line per run to a file in your repo — params, metrics,
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

Now every run auto-syncs metadata to `experiment_log/runs.jsonl` in your repo —
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
  exptrack/
    __init__.py       public API
    __main__.py       python -m exptrack entrypoint
    core.py           Experiment class
    config.py         project-aware config (finds .git root automatically)
    cli.py            terminal interface
    capture/
      __init__.py     argparse patch + notebook cell hooks
    notebook.py       %load_ext + explicit API
    plugins/
      __init__.py     Plugin base class + event registry
      github_sync.py  GitHub metadata sync
  dashboard/
    app.py            web UI (Flask optional, stdlib fallback)
```
