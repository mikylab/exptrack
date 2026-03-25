# expTrack

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![stdlib only](https://img.shields.io/badge/stdlib-only-brightgreen.svg)](#what-it-does)
[![SQLite](https://img.shields.io/badge/storage-SQLite-003B57.svg)](https://www.sqlite.org/)

**A local experiment tracker for ML workflows.** Captures parameters, metrics, git state, and code changes from your training scripts and notebooks automatically. Uses only the Python standard library and stores everything in a single SQLite file.

```bash
pip install exptrack && cd my_project && exptrack init

# Prefix your training command. Parameters, git state, and artifacts
# are captured without any changes to your script.
exptrack run train.py --lr 0.01 --epochs 20 --data cifar10

exptrack ls        # list experiments
exptrack ui        # open the web dashboard
```

---

## Dashboard

<img width="1393" height="705" alt="expTrack dashboard" src="https://github.com/user-attachments/assets/7e41bf20-a428-40cf-a732-5e9a0cd8123f" />

Filter, compare, tag, and explore experiments from a local web UI. Runs on localhost with no accounts or internet needed.

---

## What It Does

**Organize experiments with studies, tags, and stages.** Group related runs into studies (e.g., a train → eval → analyze pipeline), label them with tags (`baseline`, `v2`, `ablation`), and define numbered stages within each study.

**Track Jupyter notebooks in detail.** Every cell execution is recorded: code diffs between runs, variable changes with fingerprinting, and hyperparameter-like variables (`lr`, `batch_size`) are captured as parameters automatically.

**Compare experiments visually.** Side-by-side parameter diffs with overlay metric charts for pairs. Bar charts across three or more runs. Image artifacts support swipe and overlay comparison.

**Chart metrics over time.** Interactive charts with linear/log scale, zoom, and configurable downsampling. Write-time thinning for long training runs. Sparkline previews in the experiment list.

**Capture git state automatically.** Branch, commit hash, and full diff against HEAD are stored with every run. See exactly what code produced each result.

**Log and compare image artifacts.** `plt.savefig()` calls are captured automatically. View images in a gallery grid, lightbox, or side-by-side/overlay comparison between experiments.

**Run entirely on your machine.** One SQLite file, standard library only, no accounts or internet. Data stays local.

---

## Four Ways to Use It

### 1. Wrap a script (easiest)

```bash
exptrack run train.py --lr 0.01 --epochs 20
```

Your script needs no modifications. expTrack captures argparse parameters, git state, code changes, and `plt.savefig()` artifacts automatically.

To log metrics, use the injected `__exptrack__` global:

```python
# Available only under `exptrack run`, no imports needed
exp = globals().get("__exptrack__")
for epoch in range(epochs):
    loss, acc = train(...)
    if exp:
        exp.log_metrics({"loss": loss, "accuracy": acc}, step=epoch)
```

The script still works with plain `python train.py`. The metrics lines are skipped when `exp` is `None`.

### 2. Jupyter notebook

```python
%load_ext exptrack   # add this to your first cell
```

Every cell is tracked: code diffs, variable changes, hyperparameter-like variables (`lr`, `batch_size`, etc.) become parameters, and `plt.savefig()` calls register artifacts.

**Or use the explicit API:**

```python
import exptrack.notebook as exp

exp.start(lr=0.001, bs=32)
exp.metric("val/loss", 0.23, step=5)
exp.done()
```

### 3. Shell / SLURM pipeline

Works with **any language or binary** — Python, C++, Julia, R, Fortran, or plain shell commands. Only the `exptrack` CLI calls need Python installed; your actual workload can be anything.

Add two lines to any existing script — `run-start` at the top, `run-finish` at the bottom:

```bash
#!/bin/bash
# run.sh todayRun — your existing script, now tracked
set -e

eval $(exptrack run-start --name "$1" --lr 0.01 --epochs 50)
#  └── sets $EXP_ID, $EXP_NAME, $EXP_OUT in your shell

# Your actual work (unchanged) — any language, any binary
python train.py --lr 0.01 --output "$EXP_OUT"
./postprocess --input "$EXP_OUT"

# Done — auto-discovers output files, loads metrics from JSON
exptrack run-finish $EXP_ID --metrics "$EXP_OUT/results.json"
```

```bash
bash run.sh todayRun              # run it the same way as before
exptrack show $EXP_ID             # see what was captured
```

> **How `eval $(...)` works:** `exptrack run-start` prints `export EXP_ID=...` lines to stdout. `eval $(...)` executes them in your shell, setting the variables. If you prefer, you can source the env file instead:
> ```bash
> exptrack run-start --lr 0.01 > /tmp/exp.env 2>/dev/null
> source /tmp/exp.env
> ```

**Log metrics and artifacts mid-run:**

```bash
exptrack log-metric $EXP_ID val_loss 0.234 --step 10       # single metric
exptrack log-metric $EXP_ID --file metrics.json --step 10   # bulk from JSON
exptrack log-artifact $EXP_ID path/to/model.pt --label model
exptrack log-result $EXP_ID accuracy 0.95                    # final results
exptrack link-dir $EXP_ID ./logs/tensorboard --label tb      # link directories
command | exptrack log-output $EXP_ID --label training        # capture stdout
```

**SLURM jobs** — SLURM environment variables (`SLURM_JOB_ID`, `SLURM_NODELIST`, etc.) are captured automatically:

```bash
#!/bin/bash
#SBATCH --job-name=train_resnet
#SBATCH --gpus=1

eval $(exptrack run-start --script train --lr 0.001 --batch-size 256)
trap 'exptrack run-fail "$EXP_ID" "Exit code $?"' ERR

python train.py --lr 0.001 --output "$EXP_OUT"
exptrack run-finish "$EXP_ID" --metrics "$EXP_OUT/results.json"
```

**Multi-step wrappers** — set `--study` once, subsequent calls inherit automatically (stages auto-increment):

```bash
#!/bin/bash
# run.sh — wrapper that tracks each script as a separate stage
eval $(exptrack run-start --study my-ablation --stage 1 --stage-name train --lr 0.01)
python train.py --lr 0.01 --output "$EXP_OUT"
exptrack run-finish $EXP_ID

# $EXP_STUDY inherited, $EXP_STAGE auto-increments to 2
eval $(exptrack run-start --stage-name eval)
./evaluate --model "$EXP_OUT/model.pt"
exptrack run-finish $EXP_ID
```

### 4. Python API (full control)

```python
from exptrack.core import Experiment

with Experiment(params={"lr": 0.01, "optimizer": "adam"}) as exp:
    for epoch in range(100):
        loss, acc = train(...)
        exp.log_metrics({"loss": loss, "accuracy": acc}, step=epoch)
    exp.add_tag("baseline")
```

---

## What Gets Captured Automatically

| | Scripts | Notebooks | Shell/SLURM | Python API |
|---|---|---|---|---|
| **Params** | From argparse / sys.argv | From HP-like variables | You pass them | You log them |
| **Git state** | Yes | Yes | Yes | Yes |
| **Code changes** | Script diff vs last commit | Cell diffs + variable changes | | |
| **Artifacts** | `plt.savefig` + new files | `plt.savefig` | You log them | You log them |
| **Status** | Automatic (done/failed) | You call `done()` | You call `run-finish` | Automatic with `with` |

Metrics always need explicit logging. expTrack captures what you ran and how your code changed, but it can't decide which numbers matter to you.

---

## Managing Experiments

```bash
# List and inspect
exptrack ls                        # last 20 experiments
exptrack show <id>                 # full details
exptrack diff <id>                 # colorized git diff
exptrack compare <id1> <id2>       # side-by-side comparison

# Tag and annotate
exptrack tag <id> baseline
exptrack note <id> "tried higher dropout, worse results"

# Clean up
exptrack rm <id>                   # delete one run
exptrack clean                     # bulk-delete all failed runs

# Export
exptrack export <id>               # JSON to stdout
exptrack export <id> --format md   # Markdown
```

---

## Dashboard Features

```bash
exptrack ui          # opens http://localhost:7331
```

- **Experiment list** with status filters, search, and sparkline charts inline
- **Detail view** with parameters, metrics, interactive charts, code changes, git diff, and a reproducible command with one-click copy
- **Compare** experiments pair-wise (side-by-side with overlay charts) or across 3+ runs (bar charts)
- **Timeline** showing cell executions, variable changes, and artifact creation (notebooks)
- **Images** displayed in a gallery grid with lightbox and side-by-side/overlay/swipe comparison
- **Data files** (CSV, JSON, JSONL) rendered as interactive sortable tables
- **Inline editing** for names, tags, and notes (double-click to edit)
- Tag autocomplete, timezone selector, bulk operations, and export (JSON/Markdown/Text)

---

## Installation

```bash
# From GitHub
pip install git+https://github.com/mikylab/expTrack.git

# Local / development
git clone https://github.com/mikylab/expTrack.git
cd expTrack && pip install -e .
```

Only standard library dependencies. Requires Python 3.8+.

**Does it affect other packages?** Patches only activate when you explicitly use `exptrack run` or `%load_ext exptrack`, and they're removed when the script or session ends.

---

## Examples

The [`examples/`](examples/) directory has ready-to-run scripts:

| Example | What it shows |
|---------|---------------|
| [`basic_script.py`](examples/basic_script.py) | Automatic tracking with `exptrack run`, no imports needed |
| [`resnet_exptrack_run.py`](examples/resnet_exptrack_run.py) | Metric logging via the `__exptrack__` global |
| [`resnet_python_api.py`](examples/resnet_python_api.py) | Same training using the explicit Python API |
| [`manual_tracking.py`](examples/manual_tracking.py) | Full lifecycle: parameters, metrics, tags, artifacts |
| [`notebook_example.py`](examples/notebook_example.py) | Notebook API as a plain script |
| [`shell_script_example.sh`](examples/shell_script_example.sh) | Pure shell workflow (no Python in the workload) |
| [`pipeline_example.sh`](examples/pipeline_example.sh) | Shell/SLURM single-step pipeline |
| [`pipeline_multistep.sh`](examples/pipeline_multistep.sh) | Multi-step pipeline: train, test, analyze |
| [`pipeline_wrapper.sh`](examples/pipeline_wrapper.sh) | Wrapper script with auto-inherited study and stages |
| [`slurm_job.sh`](examples/slurm_job.sh) | SLURM sbatch script with error trapping |

---

## Further Documentation

| Doc | What's in it |
|-----|-------------|
| [CLI Reference](docs/cli-reference.md) | All 24 subcommands |
| [Configuration](docs/configuration.md) | Every `.exptrack/config.json` option |
| [Python API](docs/python-api.md) | `Experiment` class properties and methods |
| [Plugins](docs/plugins.md) | Writing plugins, GitHub Sync |
| [How It Works](docs/how-it-works.md) | Capture mechanisms, storage design, schema |
| [FAQ](docs/faq.md) | Common questions |
| [Troubleshooting](docs/troubleshooting.md) | Solutions for common issues |
| [Contributing](docs/contributing.md) | Development setup, linting, guidelines |

---

## License

MIT. See [LICENSE](https://opensource.org/licenses/MIT).
