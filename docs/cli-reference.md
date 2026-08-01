# CLI Reference

All commands run from your project directory (where you ran `exptrack init`).

```
Setup
  exptrack init [name]              Initialize project, create .exptrack/, patch .gitignore
  exptrack init --here              Initialize in current dir (skip git root detection)

Script Tracking
  exptrack run script.py [args]     Run script with automatic param/artifact capture
                                    Auto-resumes if script args contain --resume (configurable)

Shell / SLURM Pipeline (works with any language — Python, C++, Julia, R, shell)
  exptrack run-start [--key val]    Start experiment, print env vars for eval $()
                     [--script name] Naming hint (label or filename)
                     [--study name] Group into a study
                     [--stage N]    Set stage number
                     [--stage-name] Stage label (train, eval, etc.)
                     [--tags t1 t2] Add tags
                     [--notes text] Add notes
                     [--resume [ID]] Resume previous experiment (default: latest for script)
  exptrack run-finish <id>          Mark done (--metrics file.json to log from JSON)
                      [--params K=V] Add extra params at finish time
  exptrack run-fail <id> [reason]   Mark failed
  exptrack log-metric <id> <k> <v>  Log metric (--step N, --file f.json)
  exptrack log-artifact <id> <path> Register output file (--label name, --stdin)
  exptrack log-output <id>          Capture piped stdout (cmd | exptrack log-output $ID)
  exptrack log-result <id> <k> <v>  Log final result (--file f.json, --source label)
  exptrack link-dir <id> <path>     Link a directory and scan its files (--label name)
  exptrack create --name <name>     Create manual experiment entry (--params, --metrics)

Inspect
  exptrack ls [-n 50]               List experiments (--tag, --study to filter)
  exptrack show <id> [--timeline]   Full details (params, metrics, artifacts, diff)
  exptrack timeline <id> [-c]       Execution timeline (--type to filter events)
  exptrack diff <id>                Colorized git diff from run time
  exptrack compare <id1> <id2>      Side-by-side params + metrics
  exptrack history <nb> [id]        Notebook cell snapshot history
  exptrack watch <id> [--interval]  Live-refresh a running experiment in the terminal
  exptrack studies                  List studies with run counts
  exptrack export <id> [--format]   Export as JSON, Markdown, CSV/TSV or params
                     [--full]       Every metric point + every artifact
                     [--max-artifacts N] Artifact list cap (0 = all)
  exptrack verify [id] [--backfill] Check artifact file integrity

Organize
  exptrack tag <id> <tag>           Add tag
  exptrack untag <id> <tag>         Remove tag
  exptrack delete-tag <tag>         Remove tag from all experiments
  exptrack study <id> <name>        Add to study
  exptrack unstudy <id> <name>      Remove from study
  exptrack delete-study <name>      Remove study from all experiments
  exptrack stage <id> <N> [--name]  Set stage number and label
  exptrack note <id> "text"         Append note
  exptrack edit-note <id> "text"    Replace notes
  exptrack variant-of <id> <base>   Compare this run against <base> instead of
                                      the previous run by time; omit <base> to
                                      clear the link
  exptrack finish <id>              Manually mark running experiment as done

Clean Up
  exptrack rm <id>                  Delete run (with confirmation)
  exptrack clean [--baselines]      Remove all failed runs (or clear code baselines)
                [--older-than 30d]  Delete runs older than N days
                [--all-statuses]    Include done runs (default: only failed)
                [--orphans]         Purge rows not linked to any run; reports
                                      orphaned output files (never deletes silently)
                [--vacuum]          Reclaim free space in the DB file (deletes nothing)
                [--reset]           Wipe every run and reset the DB
                [--dry-run]         List what would be deleted
  exptrack prune [id...]            Thin metric series you already logged
                 --max-points N     Thin each series to at most N points
                 --keep-every N     Keep every Nth point instead
                 [--key K]          Only this metric key (repeatable)
                 [--dry-run] [-y] [--vacuum]
                                    First, last, min and max of every series are
                                      always kept, so charts keep their shape
  exptrack compact [ids...]         Strip stored git diffs to save space
                   [--cells] [--timeline] [--snapshots] [--deep]
                   [--older-than 7d] [--export DIR] [--dry-run]
  exptrack stale --hours 24         Mark old running experiments as timed-out

Admin
  exptrack upgrade [--reinstall]    Run database schema migrations
  exptrack storage                  Show DB size, output size, Trash size,
                                      optimization tips
                   [--by-metric]    Break the metrics table down per metric key
                   [--top N]        List the N largest runs (0 to hide)
                   [--checkpoint]   Truncate the WAL and exit
  exptrack backup [path]            Copy the database to a backup file
  exptrack restore <path>           Restore the database from a backup
  exptrack ui [--port 7331]         Launch web dashboard (auto-generates an
                                      auth token and prints a URL with it
                                      embedded — Jupyter-style)
    --token <value>                   Persist an auth token to config
                                      (survives restarts)
    --clear-token                     Remove the persisted auth token
    --no-auth                         Disable the auto-generated token
                                      (trusted-local only)
    --host <addr>                     Bind address (default 127.0.0.1)
  exptrack ui-stop [--port 7331]    Kill a stale dashboard still holding
                                      the port (uses fuser / lsof)

Notebook
  exptrack notebook-guard           Print a paste-able guard cell so a notebook
                                      runs with OR without exptrack installed
                                      (session magics degrade to no-ops)

Session Trees (see docs/session-trees.md)
  exptrack sessions                 List sessions
  exptrack session show|nodes <id>  Inspect a session's tree
  exptrack session finalize <id>    Graduate nodes into experiments, group them
                                      into a study, then Trash the session
  exptrack session rm|restore|purge  Whole-session Trash operations
  exptrack session rm-node|restore-node|purge-node|empty-trash|trash
  exptrack session rename-node|promote-checkpoint|note
```

---

## Export formats

`exptrack export <id> --format <fmt>` supports `json` (default), `markdown`,
`csv`, `tsv`, and the params-only forms `params`, `params-flags`, `params-json`,
`params-md`, `params-tsv`. `--all` exports every run as a batch.

### Summary by default

A run that logs every iteration stores tens of thousands of metric points, and a
checkpoint-per-epoch run registers thousands of artifacts. Emitting one JSON
object per point and one per file made the export unreadable — the params and
the final numbers were buried under raw data. So **every format, JSON included,
is a summary by default**:

- **Metrics** — one entry per key rather than one per logged point:

  ```json
  "metrics": {
    "val/acc": {
      "count": 2000,
      "first": 0.12, "first_step": 0,
      "last": 0.914, "last_step": 1999,
      "min": 0.12,   "min_step": 0,
      "max": 0.914,  "max_step": 1999
    }
  }
  ```

- **Artifacts** — the list is capped (25 by default) and an `artifacts_summary`
  states the shape of what was left out, by type and by containing directory:

  ```json
  "artifacts_summary": {
    "total": 4000, "listed": 25, "omitted": 3975,
    "by_type": [{"type": "model", "count": 3990}, {"type": "image", "count": 10}],
    "by_dir":  [{"dir": "outputs/ckpts", "count": 3990}],
    "dirs_omitted": 0
  }
  ```

Truncation is never silent — `omitted` always says how many are missing.

### Getting everything

```bash
exptrack export <id> --full             # raw metrics_series + every artifact
exptrack export <id> --max-artifacts 0  # keep the metric summary, list all artifacts
exptrack export <id> --max-artifacts 100
```

`--full` is the round-trippable form: it adds the complete `metrics_series`
(every point, as stored) alongside the summary and lists every artifact. In the
dashboard the same payload is **Export → JSON (full)**, or
`GET /api/export/<id>?format=json&full=1` directly.

---

## Reading `exptrack storage`

- **Database file / Outputs directory** — real sizes on disk. `of which free`
  is space inside the database file left behind by deleted rows: SQLite reuses
  it as the database grows, but only `exptrack clean --vacuum` returns it to
  the filesystem, so a delete never shrinks the file on its own.
- **Database Breakdown / Storage Hotspots** — where the bytes went. Per-table
  figures come from SQLite's own page accounting and are exact; per-metric-key
  and per-run figures apportion that total by row count and are labelled
  *estimated*.
- **Largest Experiments** — which run to prune or delete, largest first.
- **Trash** — what soft delete is holding: database bytes for trashed runs and
  session nodes, their output files still on disk (soft delete never touches
  files), and the `.exptrack/trash/` OS-trash fallback directory. Shown only
  when the Trash isn't empty. The database part is freed by deleting
  permanently, and returned to the filesystem by `exptrack clean --vacuum`.
- **Database Health** — journal mode and WAL size, plus warnings for a large
  WAL and runs stuck in `running`. Orphaned rows (rows whose experiment no
  longer exists — from an older version, a hand-edited database, or a process
  killed mid-delete) are counted here with their estimated cost. Any CLI
  command sweeps them on exit; `exptrack clean --orphans` does it on demand.

An empty project is about **148 KB** of database (the schema's 37 pages) and no
WAL at rest — the `-wal`/`-shm` files exist only while a connection is open.
