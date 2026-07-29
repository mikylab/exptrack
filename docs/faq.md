# FAQ

### Does exptrack capture print output or stdout?

**In notebooks, yes.** Each cell's `print()` output is captured (alongside the trailing-expression value) and shown in the dashboard Timeline's **Out** panel and on Session Trees nodes, mirroring what you saw in the notebook. It's capped at 4000 chars per cell so a chatty loop can't bloat the database.

**For scripts run via `exptrack run`, no** — stdout/stderr aren't captured as a full transcript; only explicitly logged metrics are stored. To capture a script's terminal output, redirect to a file and register it:

```bash
exptrack run train.py 2>&1 | tee train.log
exptrack log-artifact <id> train.log --label "training log"
```

### What script format does it need?

Any Python script works. If it uses **argparse**, all arguments are captured automatically. If not, exptrack falls back to parsing `sys.argv` flags (`--lr 0.01` → param `lr=0.01`). Click, Fire, Typer, and manual parsing all work.

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

Pattern: `{MonDD}_{script}__{params}__{uid}` — e.g. `Jul28_train__lr0.01_bs32__2aac1081`.

Override with `--name` on `exptrack run` or `run-start`. Customize param inclusion via `naming` in [config](configuration.md) (`naming.date_style: "numeric"` restores the older `MMDD` layout). A run that kept its generated name is flagged, so the dashboard's **Needs naming** filter can find it later.

### Does it capture plots automatically?

If you use matplotlib, yes. `plt.savefig()` and `Figure.savefig()` are patched so saved figures are copied to the experiment's output directory and registered as artifacts. This also works with libraries that call matplotlib under the hood (seaborn, etc.).

### Does it need internet?

exptrack is fully local, with no external requests at all. The database is SQLite and the dashboard uses the standard library HTTP server; Chart.js is vendored into the package and served from your own machine, and no webfont is loaded. It works air-gapped.

### What's the performance overhead?

Minimal. Argparse patching adds microseconds to `parse_args()`. Git state capture runs once at startup and takes a few milliseconds. Large git diffs are capped at 256 KB by default (`max_git_diff_kb` in config).

Metrics get the most attention because they are the only thing exptrack writes inside your training loop: each is one SQLite insert, and the commits behind them are batched at most once per `metric_commit_interval_ms` (default 250 ms) — a commit is an fsync, and committing every call made a 100k-iteration run spend 151s inside exptrack instead of 8s. A `kill -9` can lose at most that window; every ordinary exit flushes.

### How big is an empty project?

About **148 KB** for the database and **nothing** for the WAL.

The database file is created on first use, not by `exptrack init` — `.exptrack/` starts out holding only `config.json` (~1 KB). Once anything opens it, the schema (10 tables plus their indexes, 34 objects) takes 37 pages of 4 KB = 151,552 bytes. That is the floor; it doesn't shrink.

The `-wal` and `-shm` files exist only while a connection is open and are removed when the last one closes, so a project at rest shows just `experiments.db`. While something *is* connected, a few hundred KB of WAL is normal — schema creation alone writes ~346 KB into it before the first checkpoint — and it is reclaimed by a checkpoint, which exptrack runs on exit and on `exptrack clean`.

A WAL that stays large is worth a look: `exptrack storage` flags one over 10 MB, or one more than twice the size of the database. `exptrack storage --checkpoint` truncates it. (Do that when no run is writing — a truncating checkpoint waits on active writers.)

### I deleted runs but the database file is the same size

The rows are gone — deleting a run removes its metrics, params, artifacts and
timeline events immediately, and you can verify that with `exptrack storage`
(the row counts and the per-table bytes both drop). What doesn't change is the
size of the *file*: SQLite puts the freed pages on the database's internal free
list and reuses them as it grows, rather than handing them back to the operating
system. Nothing shrinks a SQLite file except a VACUUM.

So a delete reports what it freed, and `exptrack storage` shows it as part of
the file:

```
$ exptrack rm 9850f7
Deleted 1 experiment(s) (including output files).
  ~4.0 MB freed inside the database file — reusable immediately.
  Run "exptrack clean --vacuum" to return it to the filesystem.

$ exptrack storage
  Database file:     12.1 MB
    of which free:     4.0 MB  (33% reusable — deleted rows, ...)

$ exptrack clean --vacuum
Reclaimed 4.2 MB (12.1 MB → 8.0 MB).
```

The dashboard shows the same two things: a **of which free** row in
Settings → Database, and a note after a permanent delete saying how much it
freed. If you're about to log a lot more runs, there's no need to vacuum at all
— that space gets reused. Vacuum when you want the disk back, and do it with
the dashboard closed, since VACUUM needs exclusive access to the database.

The WAL is cleaned up on its own: the CLI truncates it when the command exits,
and the dashboard truncates it after a permanent delete (with a short, bounded
wait, so it can never sit blocking on a live training run).

### Does deleting from the dashboard remove the metrics too?

Yes — a **permanent** delete removes the run's metrics, params, artifacts and
timeline events, plus its content-addressed script snapshot and git diff if no
other run still references them. The dashboard's default **Move to Trash** is
not a delete: it hides the run and keeps every row so Restore stays lossless
(see the Trash question below for what that costs).

### What about orphaned rows from older versions?

An orphan is a row pointing at an experiment that no longer exists. exptrack
doesn't create them — a delete removes the children first, and the schema's
foreign keys would refuse it otherwise — but a database written by an older
version, edited by hand, or left behind by a process killed mid-delete can
contain them. They show up nowhere in the UI while still occupying the file.

They are found and reported now, not silently carried:

```
$ exptrack storage
  Database Health
  --------------------------------------------------
  ...
    40,003 orphaned row(s) (~4.0 MB): 40,000 metrics, 2 artifacts, 1 git_diffs
    Rows whose experiment no longer exists — swept automatically when a CLI
    command exits, or now with "exptrack clean --orphans".
```

Any CLI command sweeps them on exit, so in practice they disappear the first
time you run `exptrack ls`. The dashboard deliberately does *not* sweep on its
own (the check is an anti-join across metrics/params/timeline — far too
expensive to run per request), so if you only ever use the UI, Settings →
Database shows an **Orphaned rows** section with a **Clean…** button. Removing
them frees space inside the file, which `exptrack clean --vacuum` returns to
disk.

### How much space is my Trash using?

`exptrack storage` has a **Trash** section, and the dashboard shows the same figures in Settings → Database and at the top of the Trash view. Soft delete is the default everywhere, so nothing is reclaimed until you say so — the report splits that into what a permanent delete gives back and what it doesn't:

- **Database bytes** held by trashed runs and trashed session nodes. Freed by permanently deleting; the pages return to the *filesystem* only after `exptrack clean --vacuum`.
- **Output files still on disk** — soft delete never touches files. Only removed if you tick "also move files to system Trash" in the permanent-delete confirm, and only for directories no surviving run also claims.
- **`.exptrack/trash/`** — the fallback directory for files exptrack could not hand to the OS Trash. Nothing but you removes these.

### Can I track across multiple machines?

exptrack is single-machine by design. To aggregate results: use `exptrack export <id> --format json` (add `--full` if the receiving side needs every metric point — see [Export formats](cli-reference.md#export-formats)), enable the [GitHub Sync plugin](plugins.md), or query the SQLite database directly.

### Why does my JSON export not contain every metric point?

Because a run logging every iteration would otherwise emit tens of thousands of JSON objects and bury the params and final numbers. The default export gives one entry per metric key (`count`/`first`/`last`/`min`/`max` with steps) and caps the artifact list, with an `artifacts_summary` naming what was left out by type and directory. Pass `--full` for the complete payload, or `--max-artifacts N` to change just the artifact cap. See [Export formats](cli-reference.md#export-formats).

### How do I compare experiments?

**CLI:** `exptrack compare <id1> <id2>`
**Dashboard:** Click "Compare" → Pair (side-by-side) or Multi (bar charts across 3+ runs).

### What happens on rerun?

A new experiment is created each time. Old artifacts at conflicting paths are archived automatically (when `protect_on_rerun` is enabled).

### Can I view CSVs and data files in the dashboard?

Yes. CSV, TSV, JSON, and JSONL artifacts appear under the **Data Files** tab as interactive sortable tables.

### How do I view images?

Image artifacts (PNG, JPG, GIF, SVG, WebP) appear in the **Images** tab as a gallery grid. Click to enlarge. Pair Compare supports side-by-side, overlay, and swipe modes.
