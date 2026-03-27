# How It Works

## Capture Mechanisms

### Scripts: argparse patching

When you run `exptrack run train.py --lr 0.01`, exptrack patches `ArgumentParser.parse_args()` *before* your script starts. When your script calls `parse_args()`, the parsed arguments are logged as params. The patch is removed when the script exits.

If your script doesn't use argparse, exptrack falls back to parsing raw `sys.argv` (handles `--key value` and `--key=value`).

### Notebooks: IPython hooks

`%load_ext exptrack` registers a `post_run_cell` hook. After every cell:

1. The cell source is hashed (SHA-256) for content-addressed tracking
2. Changes are diffed against the previous version of that cell (30% similarity match)
3. New/changed variables are detected and fingerprinted
4. HP-like variables (`lr`, `batch_size`, etc.) are logged as params
5. Everything is recorded as timeline events

### Plots: matplotlib patching

`plt.savefig()` and `Figure.savefig()` are patched so saved figures are automatically copied to the experiment's output directory and registered as artifacts. Figures saved before the experiment starts are buffered and linked later.

### Output files: auto-detection

After a script finishes, exptrack scans the working directory for new files created during the run. Model checkpoints (`.pt`, `.pth`, `.ckpt`, `.safetensors`, `.h5`, `.onnx`), images, data files, and logs are registered as artifacts automatically. Files already registered (e.g. by the matplotlib patch) are not duplicated.

Artifacts are tracked by reference — exptrack never copies or moves your files. Large checkpoint directories are unaffected.

### Resume: auto-detection

When `exptrack run` sees `--resume` (or any flag listed in `resume_flags` config) in the script's argv, it resumes the **latest experiment for that script** instead of creating a new one. All metrics, artifacts, and params aggregate into the same experiment ID. The timeline continues from where it left off, and stdout/stderr logs append.

```bash
# These two commands produce a single experiment with metrics from both runs
exptrack run train.py --lr 0.01 --epochs 50
exptrack run train.py --lr 0.01 --epochs 100 --resume --ckpt model.pt
```

If your script uses a different flag (e.g. `--continue`, `--load-checkpoint`), add it to `resume_flags` in `.exptrack/config.json`:

```json
{ "resume_flags": ["--resume", "--continue", "--load-checkpoint"] }
```

Your output directory flag name doesn't matter (`--output_dir`, `--results_directory`, etc.) — exptrack doesn't look at it. It finds new files by scanning the working directory after the run finishes, regardless of where they were saved.

**What's visible after a resume:**

- A `resume` event in the timeline (visible in `exptrack timeline <id>` and the dashboard Timeline tab) showing the command that triggered it
- Metrics from all runs plotted on a single chart — step numbers continue seamlessly
- Artifacts from all runs listed together
- Updated params if the resumed run changed any values (e.g. `--epochs 100` overwrites the original `--epochs 50`)

## Storage Design

- **Diff-only** — script changes are diffed against `git HEAD`; notebooks store only cell diffs and variable change hashes. No full-source copies.
- **Single SQLite file** — WAL mode for safe concurrent reads. Portable, queryable, no server needed.
- **Per-project** — database lives in `.exptrack/` (gitignored). Config is safe to commit.
- **Content-addressed cells** — notebook cells identified by SHA-256 of source, so reordering and splitting cells doesn't break tracking.

## Database Schema

7 tables, all indexed for fast lookups:

| Table | Purpose |
|-------|---------|
| `experiments` | Run metadata, git state, status, timestamps |
| `params` | Key-value parameters (JSON-stringified values) |
| `metrics` | Float values with optional step and timestamp |
| `artifacts` | Output file paths with content hashes and sizes |
| `timeline` | Execution events (cell_exec, var_set, artifact, metric) |
| `cell_lineage` | Content-addressed notebook cell history |
| `code_baselines` | Position-based cell baselines |

## exptrack vs. TensorBoard

| | exptrack | TensorBoard |
|---|---|---|
| **Dependencies** | Zero | TensorFlow + protobuf |
| **Code changes** | None | Must add `SummaryWriter` calls |
| **Auto-captures** | Params, git state, diffs, variables | Nothing |
| **Storage** | SQLite (one queryable file) | Protobuf event files |
| **Experiment mgmt** | Built-in CLI: ls, compare, tag, rm | Viewer only |
| **Shell/SLURM** | First-class | Not designed for it |

They're complementary — use exptrack for "what code/params produced this run" and TensorBoard for rich visualizations.
