# exptrack

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

<img width="1392" height="678" alt="exptrack dashboard" src="https://github.com/user-attachments/assets/5e388fec-a884-4bcc-a2ec-7f24ed2ff89b" />

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

Your script needs no modifications. exptrack captures argparse parameters, git state, code changes, and `plt.savefig()` artifacts automatically.

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

For shell scripts, SLURM jobs, or multi-step workflows.

**Your script (`run.sh`):**

```bash
#!/bin/bash
LR=$1
EPOCHS=$2

eval $(exptrack run-start --name "$3" --lr $LR --epochs $EPOCHS)

python train.py --lr $LR --epochs $EPOCHS --output "$EXP_OUT"

exptrack run-finish $EXP_ID --metrics "$EXP_OUT/results.json"
```

**In your terminal:**

```bash
bash run.sh 0.01 50  baseline
bash run.sh 0.1  100 higher-lr

exptrack ls                       # see both runs
```

`eval $(exptrack run-start ...)` creates a new experiment and sets three variables inside your script: `$EXP_ID` (experiment ID), `$EXP_NAME` (run name), and `$EXP_OUT` (output directory — files written here are auto-discovered as artifacts). Each run of the script creates a separate experiment. On failure, call `exptrack run-fail $EXP_ID "reason"`.

**SLURM** — submit with `sbatch run.sh`. SLURM env vars are captured automatically:

```bash
#!/bin/bash
#SBATCH --job-name=train_resnet
#SBATCH --gpus=1

eval $(exptrack run-start --lr 0.001 --batch-size 256)
trap 'exptrack run-fail "$EXP_ID" "Exit code $?"' ERR

python train.py --lr 0.001 --output "$EXP_OUT"
exptrack run-finish "$EXP_ID" --metrics "$EXP_OUT/results.json"
```

**Multi-step** — set `--study` on the first step, subsequent steps inherit it:

```bash
#!/bin/bash
eval $(exptrack run-start --study my-ablation --stage 1 --stage-name train --lr 0.01)
python train.py; exptrack run-finish $EXP_ID

# EXP_STUDY inherited, EXP_STAGE auto-increments to 2
eval $(exptrack run-start --stage-name eval)
python eval.py; exptrack run-finish $EXP_ID
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

Metrics always need explicit logging. exptrack captures what you ran and how your code changed, but it can't decide which numbers matter to you.

---

## Managing Experiments

```bash
# List and inspect
exptrack ls                        # last 20 experiments
exptrack show <id>                 # full details
exptrack diff <id>                 # colorized git diff
exptrack compare <id1> <id2>       # side-by-side comparison
exptrack history <id>              # param/metric change history
exptrack timeline <id>             # chronological event log

# Tag, annotate, and organize
exptrack tag <id> baseline
exptrack note <id> "tried higher dropout, worse results"
exptrack study <id> ablation-v2    # group into a study
exptrack stage <id> 1 train        # assign a numbered stage

# Export (JSON, Markdown, CSV, TSV)
exptrack export <id>               # JSON to stdout
exptrack export <id> --format csv  # CSV
exptrack export --all --format md  # bulk export

# Clean up and maintenance
exptrack rm <id>                   # delete one run
exptrack clean                     # bulk-delete all failed runs
exptrack compact                   # strip git diffs to save space
exptrack backup                    # backup the database
exptrack restore <path>            # restore from backup
exptrack storage                   # show DB size and stats
```

---

## Dashboard Features

```bash
exptrack ui          # opens http://localhost:7331
exptrack ui --token secret   # with optional authentication
```

- **Experiment list** with status filters, search, sparkline charts, and customizable columns (resize, show/hide)
- **Detail view** with parameters, metrics, interactive charts, code changes, git diff, and a reproducible command with one-click copy
- **Compare** experiments pair-wise (side-by-side with overlay charts) or across 3+ runs (bar charts)
- **Timeline** showing cell executions, variable changes, and artifact creation (notebooks)
- **Images** displayed in a gallery grid with lightbox and side-by-side/overlay/swipe comparison
- **Data files** (CSV, JSON, JSONL, TSV) rendered as interactive sortable tables
- **Toolbox** with a commands notepad (save and edit shell commands) and a todo list with due dates
- **Manual experiment creation** for logging runs that weren't tracked automatically
- **Inline editing** for names, tags, notes, studies, and stages (double-click to edit)
- **Studies and stages** to organize multi-step pipelines, with highlight mode and filtering
- Tag autocomplete, searchable filter dropdowns, timezone selector, bulk operations, and export (JSON/Markdown/CSV/TSV/Text)

---

## Installation

```bash
# From GitHub
pip install git+https://github.com/mikylab/exptrack-dev.git

# Local / development
git clone https://github.com/mikylab/exptrack-dev.git
cd exptrack-dev && pip install -e .
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
