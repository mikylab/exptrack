# FAQ

### Does expTrack capture print output or stdout?

No. Only explicitly logged metrics are stored. To capture terminal output, redirect to a file and register it:

```bash
exptrack run train.py 2>&1 | tee train.log
exptrack log-artifact <id> train.log --label "training log"
```

### What script format does it need?

Any Python script works. If it uses **argparse**, all arguments are captured automatically. If not, expTrack falls back to parsing `sys.argv` flags (`--lr 0.01` → param `lr=0.01`). Click, Fire, Typer, and manual parsing all work.

### Can I edit runs after they finish?

Yes — **name, tags, notes, artifacts, and metrics** are all editable (CLI or double-click in the dashboard). **Params and git state** are intentionally immutable for reproducibility.

### How do multi-step pipelines work?

Each `run-start` creates a separate experiment. Use `--study` to group steps and `--stage` to number them:

```bash
eval $(exptrack run-start --script train --study my-run --stage 1 --stage-name train --lr 0.01)
TRAIN_ID=$EXP_ID; python train.py; exptrack run-finish $TRAIN_ID

eval $(exptrack run-start --script test --study my-run --stage 2 --stage-name test)
TEST_ID=$EXP_ID; python test.py; exptrack run-finish $TEST_ID
```

### Studies vs. tags?

**Studies** = "which batch is this part of?" (pipeline steps, ablation sweeps).
**Tags** = "what kind of run?" (`baseline`, `production`, `needs-review`).
An experiment can have both.

### How are run names generated?

Pattern: `{script}__{params}__{MMDD}_{uid}` — e.g. `train__lr0.01_bs32__0312_a3f2`.

Override with `--name` on `exptrack run` or `run-start`. Customize param inclusion via `naming` in [config](configuration.md).

### Does it capture plots automatically?

Yes — `plt.savefig()` and `Figure.savefig()` are monkey-patched. Saved figures are copied to the experiment's output directory and registered as artifacts. Works with any library that calls matplotlib's savefig under the hood (seaborn, etc.).

### Does it need internet?

No. Everything is local — SQLite database + stdlib HTTP server. The dashboard loads Chart.js from a CDN for metric charts, but works without it.

### Performance overhead?

Negligible. Argparse patching adds microseconds. Git capture runs once at startup (~ms). Metrics are single SQLite inserts. Large git diffs are capped at 256 KB by default.

### Can I track across multiple machines?

expTrack is single-machine by design. To aggregate results: use `exptrack export <id> --format json`, enable the [GitHub Sync plugin](plugins.md), or query the SQLite database directly.

### How do I compare experiments?

**CLI:** `exptrack compare <id1> <id2>`
**Dashboard:** Click "Compare" → Pair (side-by-side) or Multi (bar charts across 3+ runs).

### What happens on rerun?

A new experiment is created each time. Old artifacts at conflicting paths are archived automatically (when `protect_on_rerun` is enabled).

### Can I view CSVs and data files in the dashboard?

Yes. CSV, TSV, JSON, and JSONL artifacts appear under the **Data Files** tab as interactive sortable tables.

### How do I view images?

Image artifacts (PNG, JPG, GIF, SVG, WebP) appear in the **Images** tab as a gallery grid. Click to enlarge. Pair Compare supports side-by-side, overlay, and swipe modes.
