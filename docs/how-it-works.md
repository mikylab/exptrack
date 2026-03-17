# How It Works

## Capture mechanisms

**Argparse patching** -- expTrack monkey-patches `ArgumentParser.parse_args()` and `parse_known_args()` before your script runs. When your script calls `parser.parse_args()`, expTrack intercepts the result and logs all arguments as params. The patch is removed when the script exits. If your script doesn't use argparse, expTrack falls back to parsing raw `sys.argv`.

**Notebook hooks** -- `%load_ext exptrack` registers an IPython `post_run_cell` hook. After every cell execution, the hook:
1. Computes a content-addressed hash of the cell source
2. Diffs the cell against its parent version (30% similarity threshold)
3. Scans the namespace for new/changed variables
4. Enriches variable displays with assignment expressions from the cell source
5. Logs timeline events for code changes, variable changes, and observational cells

**Matplotlib patching** -- `plt.savefig()` and `Figure.savefig()` are patched to copy saved figures into the experiment's output directory and register them as artifacts. Figures saved before the experiment starts are buffered and flushed when it begins.

## Storage design

- **Diff-only** -- script changes are diffed against `git HEAD`; notebook snapshots store only cell diffs and variable change hashes. No full-source copies.
- **Per-project** -- database and notebook history live in `.exptrack/` (gitignored). Config is committable.
- **SQLite WAL mode** -- safe for concurrent reads. Single file, queryable, portable.
- **Content-addressed cell lineage** -- notebook cells are identified by SHA-256 of their source content, enabling accurate tracking across cell reordering and splits.

## Database schema

| Table | Purpose |
|-------|---------|
| `experiments` | Run metadata, git state, status, timestamps |
| `params` | Key-value parameters (JSON-stringified values) |
| `metrics` | Float values with optional step and timestamp |
| `artifacts` | Output file paths with content hashes and size |
| `timeline` | Execution events (cell_exec, var_set, artifact, metric, observational) |
| `cell_lineage` | Content-addressed notebook cell history |
| `code_baselines` | Position-based cell baselines (legacy) |

## expTrack vs. TensorBoard

| | expTrack | TensorBoard |
|---|---|---|
| **Dependencies** | Zero (stdlib only) | TensorFlow/tensorboard + protobuf |
| **Code changes** | None required | Must add `SummaryWriter` calls everywhere |
| **Auto-captures** | Params, git state, full diff, cell diffs, variable changes | Nothing automatic |
| **Storage** | SQLite (one file, queryable, portable) | Protobuf event files (need TB to read) |
| **Experiment management** | Built-in: `ls`, `show`, `diff`, `compare`, `tag`, `note`, `rm`, `clean` | None -- TB is a viewer only |
| **Reproducibility** | Full `git diff` at run time | No git integration |
| **Shell/SLURM** | First-class: `eval $(exptrack run-start ...)` | Not designed for non-Python workflows |
| **Rich media** | No (metrics, params, artifacts only) | Yes (images, audio, histograms, graphs) |

**They work together** -- use expTrack for "what params and code produced this run" and TensorBoard for rich media visualization. They don't conflict.
