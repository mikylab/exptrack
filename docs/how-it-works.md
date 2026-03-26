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
