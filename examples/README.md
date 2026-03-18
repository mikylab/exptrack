# expTrack Examples

Practical examples showing different ways to use expTrack. All examples use only the Python standard library — no external dependencies required beyond exptrack itself.

## Prerequisites

Install exptrack first:

```bash
# From the repo root:
pip install -e .

# Or from PyPI (once published):
pip install exptrack
```

Then initialize a project:

```bash
exptrack init
```

## Usage

Copy an example into your project directory (where you ran `exptrack init`), then run it. The script path must be relative to your current directory.

### basic_script.py
**Zero-friction tracking** — A minimal training script using argparse. No exptrack imports needed; just wrap it with `exptrack run` and parameters are captured automatically.

```bash
cp examples/basic_script.py .
exptrack run basic_script.py --lr 0.01 --epochs 10
```

### manual_tracking.py
**Explicit Python API** — Shows how to use the `Experiment` class directly: context manager usage, logging params/metrics, tagging, notes, and saving output files.

```bash
cp examples/manual_tracking.py .
python manual_tracking.py
```

### notebook_example.py
**Notebook workflow** — Demonstrates the exptrack notebook API (`exptrack.notebook`) as a plain Python file. Shows the explicit function API (in a real notebook you'd use `%load_ext exptrack` instead).

```bash
cp examples/notebook_example.py .
python notebook_example.py
```

### resnet_exptrack_run.py
**`exptrack run` with metrics** — A ResNet training loop (simulated) that logs multiple metrics per epoch via the `__exptrack__` global. Shows the zero-import approach: the script works with both `exptrack run` and plain `python`.

```bash
cp examples/resnet_exptrack_run.py .
exptrack run resnet_exptrack_run.py --lr 0.1 --epochs 90
# Also works standalone: python resnet_exptrack_run.py --lr 0.1 --epochs 90
```

### resnet_python_api.py
**Python API with metrics** — The same ResNet training, but using the explicit `Experiment` class. Shows `params=vars(args)`, `log_metrics()`, `log_metric()`, tagging, notes, and artifact saving.

```bash
cp examples/resnet_python_api.py .
python resnet_python_api.py --lr 0.1 --epochs 90
```

### pipeline_example.sh
**Shell/SLURM pipeline** — Shows how to integrate exptrack into shell scripts and job schedulers using `run-start`, `log-metric`, `log-artifact`, and `run-finish`. Single-step example.

```bash
cp examples/pipeline_example.sh .
bash pipeline_example.sh
```

### pipeline_multistep.sh
**Multi-step pipeline** — Demonstrates a train → test → analyze pipeline where each step is a separate experiment grouped into a study with numbered stages. Shows `--study`, `--stage`, and `--stage-name` flags.

```bash
cp examples/pipeline_multistep.sh .
bash pipeline_multistep.sh
```

## Viewing Results

After running any example:

```bash
exptrack ls        # list experiments
exptrack show <id> # full details
exptrack ui        # open the web dashboard
```
