# Examples

Ready-to-run scripts showing different ways to use expTrack.

## Setup

```bash
pip install -e .       # install exptrack
exptrack init          # initialize in your project
```

## Scripts

| Example | Run with | What it shows |
|---------|----------|---------------|
| `basic_script.py` | `exptrack run basic_script.py --lr 0.01 --epochs 10` | Zero-friction — no imports needed |
| `resnet_exptrack_run.py` | `exptrack run resnet_exptrack_run.py --lr 0.1 --epochs 90` | Metric logging via `__exptrack__` global |
| `resnet_python_api.py` | `python resnet_python_api.py --lr 0.1 --epochs 90` | Same thing via explicit Python API |
| `manual_tracking.py` | `python manual_tracking.py` | Full lifecycle: params, metrics, tags, artifacts |
| `notebook_example.py` | `python notebook_example.py` | Notebook API as a plain script |
| `shell_script_example.sh` | `bash shell_script_example.sh` | Pure shell workflow (no Python in the workload) |
| `pipeline_example.sh` | `bash pipeline_example.sh` | Shell/SLURM single-step pipeline |
| `pipeline_multistep.sh` | `bash pipeline_multistep.sh` | Multi-step: train → test → analyze |
| `pipeline_wrapper.sh` | `bash pipeline_wrapper.sh` | Wrapper: auto-inherited study + stage |
| `slurm_job.sh` | `sbatch slurm_job.sh` | SLURM job script with error trapping |

## View Results

```bash
exptrack ls        # list experiments
exptrack show <id> # full details
exptrack ui        # web dashboard
```
