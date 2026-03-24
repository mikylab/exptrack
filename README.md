# expTrack

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![No Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](#why-exptrack)
[![SQLite](https://img.shields.io/badge/storage-SQLite-003B57.svg)](https://www.sqlite.org/)

**Track every ML experiment automatically. No code changes. No dependencies. No cloud.**

```bash
pip install exptrack && cd my_project && exptrack init

# Just prefix your command — everything else is automatic
exptrack run train.py --lr 0.01 --epochs 20 --data cifar10

exptrack ls        # see your experiments
exptrack ui        # open the web dashboard
```

That's it. expTrack captures your argparse params, names the run, snapshots the git diff, and links any saved plots — all without touching your code.

---

## Dashboard

<img width="1393" height="705" alt="expTrack dashboard" src="https://github.com/user-attachments/assets/7e41bf20-a428-40cf-a732-5e9a0cd8123f" />

Filter, compare, tag, and explore experiments from a local web UI. No accounts, no internet required.

---

## Why expTrack?

| | expTrack | Weights & Biases, MLflow, etc. |
|---|---|---|
| **Setup** | `pip install exptrack` | Install packages, create account, configure API keys |
| **Code changes** | None — just `exptrack run` | Add `wandb.init()`, `SummaryWriter`, decorators |
| **Dependencies** | Zero (stdlib only) | Heavy (protobuf, grpc, cloud SDKs) |
| **Where data lives** | Your machine, one SQLite file | Their cloud (or self-hosted server) |
| **Git tracking** | Auto (branch, commit, full diff) | Manual or limited |
| **Works offline** | Always | Needs sync |

---

## Four Ways to Use It

### 1. Wrap a script (easiest)

```bash
exptrack run train.py --lr 0.01 --epochs 20
```

Your script needs **zero modifications**. expTrack automatically captures argparse params, git state, code changes, and `plt.savefig()` artifacts.

To log metrics, use the injected `__exptrack__` global:

```python
# No imports needed — only works under `exptrack run`
exp = globals().get("__exptrack__")
for epoch in range(epochs):
    loss, acc = train(...)
    if exp:
        exp.log_metrics({"loss": loss, "accuracy": acc}, step=epoch)
```

Your script still works with plain `python train.py` — the metrics lines are just skipped.

### 2. Jupyter notebook

```python
%load_ext exptrack   # add this to your first cell — that's it
```

Every cell is tracked: code diffs, variable changes, hyperparameter-like variables (`lr`, `batch_size`, etc.) become params, and `plt.savefig()` calls register artifacts.

**Or use the explicit API:**

```python
import exptrack.notebook as exp

exp.start(lr=0.001, bs=32)
exp.metric("val/loss", 0.23, step=5)
exp.done()
```

### 3. Shell / SLURM pipeline

```bash
eval $(exptrack run-start --script train.py --lr 0.01 --epochs 50)
# $EXP_ID, $EXP_NAME, $EXP_OUT are now set

python train.py --lr 0.01 --epochs 50
exptrack log-metric $EXP_ID val_loss 0.234 --step 10
exptrack run-finish $EXP_ID --metrics results.json
```

Group pipeline steps with `--study` and `--stage`:

```bash
eval $(exptrack run-start --script train --study my-ablation --stage 1 --stage-name train --lr 0.01)
TRAIN_ID=$EXP_ID; python train.py; exptrack run-finish $TRAIN_ID

eval $(exptrack run-start --script test --study my-ablation --stage 2 --stage-name test)
TEST_ID=$EXP_ID; python test.py; exptrack run-finish $TEST_ID
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
| **Code changes** | Script diff vs last commit | Cell diffs + variable changes | — | — |
| **Artifacts** | `plt.savefig` + new files | `plt.savefig` | You log them | You log them |
| **Status** | Auto (done/failed) | You call `done()` | You call `run-finish` | Auto with `with` |

**Metrics always need explicit logging** — expTrack can't guess which numbers matter to you.

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

- **Experiment list** — filter by status, search by name/tag/param, sparkline charts inline
- **Detail view** — params, metrics with interactive charts, code changes, git diff, reproduce command with one-click copy
- **Compare** — pair (side-by-side params + overlay charts) or multi (bar charts across 3+ runs)
- **Timeline** — chronological cell executions, variable changes, artifact creation (notebooks)
- **Images** — gallery grid, lightbox, side-by-side/overlay/swipe comparison
- **Data files** — CSV, JSON, JSONL rendered as interactive sortable tables
- **Inline editing** — double-click any name, tag, or note to edit directly
- **Tag autocomplete**, **timezone selector**, **bulk operations**, **export** (JSON/Markdown/Text)

---

## Installation

```bash
# From GitHub
pip install git+https://github.com/mikylab/expTrack.git

# Local / development
git clone https://github.com/mikylab/expTrack.git
cd expTrack && pip install -e .
```

Zero external dependencies — stdlib only. Python 3.8+.

**Does it affect other packages?** No. Patches only activate when you explicitly use `exptrack run` or `%load_ext exptrack`, and they're removed when the script/session ends.

---

## Examples

The [`examples/`](examples/) directory has ready-to-run scripts:

| Example | What it shows |
|---------|---------------|
| [`basic_script.py`](examples/basic_script.py) | Zero-friction — no imports, just `exptrack run` |
| [`resnet_exptrack_run.py`](examples/resnet_exptrack_run.py) | Metric logging via `__exptrack__` global |
| [`resnet_python_api.py`](examples/resnet_python_api.py) | Same thing via explicit Python API |
| [`manual_tracking.py`](examples/manual_tracking.py) | Full lifecycle: params, metrics, tags, artifacts |
| [`notebook_example.py`](examples/notebook_example.py) | Notebook API as a plain script |
| [`pipeline_example.sh`](examples/pipeline_example.sh) | Shell/SLURM single-step pipeline |
| [`pipeline_multistep.sh`](examples/pipeline_multistep.sh) | Multi-step: train → test → analyze |

---

## Further Documentation

| Doc | What's in it |
|-----|-------------|
| [CLI Reference](docs/cli-reference.md) | All 24 subcommands at a glance |
| [Configuration](docs/configuration.md) | Every `.exptrack/config.json` option explained |
| [Python API](docs/python-api.md) | `Experiment` class properties and methods |
| [Plugins](docs/plugins.md) | Writing plugins, GitHub Sync |
| [How It Works](docs/how-it-works.md) | Capture mechanisms, storage design, schema |
| [FAQ](docs/faq.md) | Common questions |
| [Troubleshooting](docs/troubleshooting.md) | Solutions for common issues |
| [Contributing](docs/contributing.md) | Dev setup, linting, guidelines |

---

## License

MIT — see [LICENSE](https://opensource.org/licenses/MIT).
