# How It Works

## Capture Mechanisms

### Scripts: argparse patching

When you run `exptrack run train.py --lr 0.01`, exptrack patches `ArgumentParser.parse_args()` *before* your script starts. When your script calls `parse_args()`, the parsed arguments are logged as params. The patch is removed when the script exits.

If your script doesn't use argparse, exptrack falls back to parsing raw `sys.argv` (handles `--key value` and `--key=value`).

### Notebooks: IPython hooks

`%load_ext exptrack` registers `pre_run_cell` and `post_run_cell` hooks. The pre-hook tees `sys.stdout` so the cell's `print()` output is captured while still showing in the notebook. After every cell:

1. The cell source is hashed (SHA-256) for content-addressed tracking
2. Changes are diffed against the previous version of that cell (30% similarity match)
3. New/changed variables are detected and fingerprinted
4. HP-like variables (`lr`, `batch_size`, etc.) are logged as params
5. The cell's output — captured `print()` stdout plus the trailing-expression value — is recorded (capped at 4000 chars) and shown in the dashboard Timeline's **Out** panel
6. Everything is recorded as timeline events

### Plots: matplotlib patching

`plt.savefig()` and `Figure.savefig()` are patched so saved figures are automatically copied to the experiment's output directory and registered as artifacts. Figures saved before the experiment starts are buffered and linked later.

### Metrics: TensorBoard mirroring

If your code already logs through TensorBoard, exptrack patches
`SummaryWriter.add_scalar`, `add_scalars` and `add_histogram` (on both
`torch.utils.tensorboard` and `tensorboardX`) and *mirrors* those values into
its own metrics table. `add_scalars` expands to `<main_tag>/<sub_tag>` keys;
`add_histogram` is summarised to `<tag>/{mean,std,min,max}`. The original call
always runs, and a capture failure never crashes training.

It patches the writer at the call site rather than parsing `.tfevents`, so it
needs no `tensorboard`/`protobuf` dependency — and it only captures values
logged *after* the patch installs, with nothing read retroactively from old
event files. Disable with `auto_capture.tensorboard: false`.

This is the only *automatic* path for metrics; a loop that merely `print()`s a
loss has no library call to intercept and still needs an explicit
`log_metric()`.

### Inputs: dataset fingerprinting

When a run finishes, exptrack scans its captured params for dataset-shaped
values — an existing data file by extension (`.csv`, `.parquet`, `.npy`, …) or
a dataset-shaped key (`--data_dir`, `--train`, `--test`) pointing at an existing
path — and records a fingerprint per input: size plus a partial content hash for
files, a sorted `(relpath, size)` listing for directories (no byte reads, so a
multi-GB dataset stays fast). The dashboard shows these as a **Datasets**
section on the run.

### Failures: the traceback, not just the message

A crashed run records the full formatted traceback (file and line) as well as
the short error message, whether it crashed under `exptrack run`, inside a
`with Experiment(...)` block, or via `sys.exit(1)` after catching an exception —
in that last case exptrack follows the chained cause rather than recording a
bare `SystemExit`. The dashboard renders it as a **Run failed** panel.

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
- **Content-addressed blobs** — a run's script source and its full git diff are stored once per distinct content and reference-counted, so re-running an unchanged file costs nothing and sibling session branches share one diff body.
- **Batched metric writes** — a commit is an fsync, and metrics are the only thing written inside your training loop, so they are committed at most once per `metric_commit_interval_ms` (default 250 ms). Every ordinary exit flushes; only `kill -9` can lose a window.

## Database Schema

10 tables, all indexed for fast lookups:

| Table | Purpose |
|-------|---------|
| `experiments` | Run metadata, git state, status, timestamps, soft-delete marker |
| `params` | Key-value parameters (JSON-stringified values) |
| `metrics` | Float values with optional step, timestamp, source, session node |
| `artifacts` | Output file paths with content hashes and sizes |
| `timeline` | Execution events (cell_exec, var_set, artifact, metric) |
| `cell_lineage` | Content-addressed notebook cell history |
| `code_baselines` | Position-based cell baselines |
| `code_snapshots` | Content-addressed full script source per run |
| `sessions` | Session Trees containers |
| `session_nodes` | Session Trees nodes (checkpoints, branches, cells, plots) |

Schema migrations run automatically when a newer version first opens the
database; `exptrack upgrade` forces the check.

## exptrack vs. TensorBoard

| | exptrack | TensorBoard |
|---|---|---|
| **Dependencies** | Zero | TensorFlow + protobuf |
| **Code changes** | None | Must add `SummaryWriter` calls |
| **Auto-captures** | Params, git state, diffs, variables, datasets, tracebacks | Nothing |
| **Your TensorBoard scalars** | Mirrored automatically | Native |
| **Storage** | SQLite (one queryable file) | Protobuf event files |
| **Experiment mgmt** | Built-in CLI: ls, compare, tag, rm | Viewer only |
| **Shell/SLURM** | First-class | Not designed for it |

They're complementary — use exptrack for "what code/params produced this run" and TensorBoard for rich visualizations. You don't have to choose: exptrack mirrors the scalars you already write to a `SummaryWriter` (see **Metrics: TensorBoard mirroring** above), so both stay populated from one set of calls.
