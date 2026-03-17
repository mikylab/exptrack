# FAQ

### If I run a script and it prints results, will that be logged?

No. expTrack does **not** capture stdout/stderr output. Only explicitly logged metrics are recorded. If your script prints `accuracy: 0.95` to the terminal, that value is not stored anywhere in expTrack. To capture it, use the `__exptrack__` global:

```python
exp = globals().get("__exptrack__")
if exp:
    exp.log_metric("accuracy", 0.95)
```

Print statements, progress bars, and terminal output are not tracked — only params, metrics, artifacts, and git state.

### What format does my script need to be in for auto-logging?

Any Python script works. There are no format requirements. Just run it with `exptrack run`:

```bash
exptrack run train.py --lr 0.01 --epochs 20
```

If your script uses **argparse**, all arguments are captured automatically as params. If it doesn't use argparse, expTrack falls back to parsing raw `sys.argv` flags (e.g. `--lr 0.01` becomes param `lr=0.01`). Scripts using Click, Fire, or manual `sys.argv` parsing all work — expTrack captures whatever flags it can find.

The only thing that requires explicit logging is **metrics** (loss, accuracy, etc.) — expTrack can't guess which numbers matter to you.

### Can I edit runs after they finish?

Yes. You can edit several fields after a run completes:

- **Name:** `exptrack show <id>` displays the current name; in the dashboard, double-click the name to rename
- **Tags:** `exptrack tag <id> baseline` / `exptrack untag <id> baseline`, or double-click tags in the dashboard
- **Notes:** `exptrack note <id> "text"` (appends) / `exptrack edit-note <id> "text"` (replaces), or double-click notes in the dashboard
- **Artifacts:** Add new ones with `exptrack log-artifact <id> path/to/file`, or manage them in the dashboard detail view
- **Metrics:** Log additional metrics via `exptrack log-metric <id> key value` or from the dashboard

You **cannot** change params or git state after the fact — those are captured at run time and are intentionally immutable for reproducibility.

### Does expTrack work with scripts that don't use argparse?

Yes. If argparse isn't detected, expTrack parses `sys.argv` directly. It recognizes `--key value` and `--key=value` patterns. Scripts using Click, Fire, Typer, or manual argument parsing will have their CLI flags captured as params. Single-dash flags like `-lr 0.01` are also captured.

### Can I use expTrack with SLURM or multi-step pipelines?

Yes, this is a first-class use case. Use the shell pipeline commands:

```bash
eval $(exptrack run-start --script train --lr 0.01 --epochs 50)
python train.py --lr 0.01 --epochs 50
exptrack log-metric $EXP_ID val_loss 0.234 --step 10
exptrack run-finish $EXP_ID --metrics results.json
```

SLURM environment variables (`SLURM_JOB_ID`, `SLURM_NODELIST`, etc.) are captured automatically.

### Does expTrack capture plots and figures automatically?

Yes — if you use matplotlib. expTrack monkey-patches `plt.savefig()` and `Figure.savefig()` so any saved figure is automatically copied to the experiment's output directory and registered as an artifact. If you save figures before the experiment starts, they're buffered and linked when it begins.

Other plotting libraries (plotly, seaborn wrapping matplotlib, etc.) work too as long as they ultimately call `plt.savefig()`.

### Does expTrack need an internet connection?

No. Everything is local. The database is a single SQLite file in `.exptrack/experiments.db`. The dashboard uses stdlib `http.server` on localhost. The only network request is the Chart.js CDN script in the dashboard — and the UI still works without it (you just won't see metric charts).

### Can I track experiments across multiple machines?

expTrack is designed for single-machine, local-first use. Each machine has its own `.exptrack/` database. If you need to aggregate results, you can:

- Use `exptrack export <id> --format json` and collect the JSON files
- Enable the GitHub Sync plugin to append run metadata to a shared JSONL file in a GitHub repo
- Query the SQLite database directly

### How do I compare two experiments?

**CLI:** `exptrack compare <id1> <id2>` shows a side-by-side diff of params and metrics.

**Dashboard:** Click "Compare" in the toolbar, select two experiments for Pair Compare (params, metrics, charts, images), or select 3+ for Multi Compare (bar charts across all selected runs).

### What happens if I rerun the same script?

A new experiment is created each time. If the new run would overwrite artifact files from a previous run, expTrack archives the old artifacts first (when `protect_on_rerun` is enabled in config). Params and metrics are stored independently per run.

### Can I delete experiments?

Yes. `exptrack rm <id>` deletes a single run (with confirmation). `exptrack clean` bulk-deletes all failed runs. In the dashboard, select experiments and use the Delete bulk action. Deletion removes the database records but does not delete output files on disk — use `rm -rf outputs/<run_name>` for that.

### Does expTrack affect my script's performance?

The overhead is negligible. Argparse patching adds microseconds to `parse_args()`. Git state capture (branch, commit, diff) runs once at startup and takes a few milliseconds. Metric logging is a SQLite insert per call. The only potentially slow operation is capturing very large git diffs, which is capped at 256 KB by default (`max_git_diff_kb` in config).

### Can I use expTrack in a Jupyter notebook?

Yes. Add `%load_ext exptrack` in your first cell. expTrack will automatically track cell executions, variable changes, code diffs, and artifacts. See the [Notebooks](../README.md#notebooks) section for details.

### How do I log metrics from a training loop?

It depends on your setup:

- **`exptrack run`:** Use the injected `__exptrack__` global (see [Scripts](../README.md#scripts))
- **Notebook (magic):** `import exptrack.notebook as exp; exp.metric("loss", 0.5, step=1)`
- **Notebook (explicit):** Same as above
- **Python API:** `exp.log_metric("loss", 0.5, step=1)`
- **Shell pipeline:** `exptrack log-metric $EXP_ID loss 0.5 --step 1`

### How do I view images in the dashboard?

Image artifacts (PNG, JPG, GIF, SVG, WebP) appear in the **Images** tab of the detail view as a gallery grid. Click a thumbnail to see the full-size image in a lightbox. In Pair Compare, use the image comparison tool with side-by-side, overlay, or swipe modes.

### Can I view CSVs and data files in the dashboard?

Yes. CSV, TSV, JSON, and JSONL artifacts are rendered as interactive tables under the **Data Files** tab. Register them with `exp.out("results.csv")` in notebooks or `exptrack log-artifact <id> results.csv` from the CLI.

### How do I capture training logs?

expTrack does not auto-capture stdout/stderr. Redirect output to a file and register it as an artifact:

```bash
exptrack run train.py 2>&1 | tee train.log
exptrack log-artifact <id> train.log --label "training log"
```

In notebooks, use `exp.out("log.txt")` and write to that path.
