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

## Files

### basic_script.py
**Zero-friction tracking** — A minimal training script using argparse. No exptrack imports needed; just wrap it with `exptrack run` and parameters are captured automatically.

```bash
exptrack run examples/basic_script.py --lr 0.01 --epochs 10
```

### manual_tracking.py
**Explicit Python API** — Shows how to use the `Experiment` class directly: context manager usage, logging params/metrics, tagging, notes, and saving output files.

```bash
python examples/manual_tracking.py
```

### notebook_example.py
**Notebook workflow** — Demonstrates the exptrack notebook API (`exptrack.notebook`) as a plain Python file. Shows the explicit function API (in a real notebook you'd use `%load_ext exptrack` instead).

```bash
python examples/notebook_example.py
```

### pipeline_example.sh
**Shell/SLURM pipeline** — Shows how to integrate exptrack into shell scripts and job schedulers using `run-start`, `log-metric`, `log-artifact`, and `run-finish`.

```bash
bash examples/pipeline_example.sh
```

## Viewing Results

After running any example:

```bash
exptrack ls        # list experiments
exptrack show <id> # full details
exptrack ui        # open the web dashboard
```
