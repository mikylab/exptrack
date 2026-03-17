# expTrack Examples

Practical examples showing different ways to use expTrack. All examples use only the Python standard library — no external dependencies required.

## Files

### basic_script.py
**Zero-friction tracking** — A minimal training script using argparse. No exptrack imports needed; just wrap it with `exptrack run` and parameters are captured automatically.

### manual_tracking.py
**Explicit Python API** — Shows how to use the `Experiment` class directly: context manager usage, logging params/metrics, tagging, notes, and saving output files.

### notebook_example.py
**Notebook workflow** — Demonstrates the exptrack notebook API (`exptrack.notebook`) as a plain Python file. Shows both the `%load_ext` magic approach and the explicit function API.

### pipeline_example.sh
**Shell/SLURM pipeline** — Shows how to integrate exptrack into shell scripts and job schedulers using `run-start`, `log-metric`, `log-artifact`, and `run-finish`.

## Getting Started

1. Initialize exptrack in your project:
   ```bash
   exptrack init
   ```

2. Run any example:
   ```bash
   exptrack run examples/basic_script.py --lr 0.01 --epochs 10
   python examples/manual_tracking.py
   bash examples/pipeline_example.sh
   ```

3. View results:
   ```bash
   exptrack ls
   exptrack ui
   ```
