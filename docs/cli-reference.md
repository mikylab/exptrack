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
  exptrack unlink-artifact <id> <path>
                                    Detach a file from a run (record only —
                                      the file on disk is never touched)
  exptrack log-output <id>          Capture piped stdout (cmd | exptrack log-output $ID)
  exptrack log-result <id> <k> <v>  Log final result (--file f.json, --source label)
  exptrack link-dir <id> <path>     Link a directory and scan its files (--label name)
  exptrack create --name <name>     Create manual experiment entry (--params, --metrics)

Inspect
  exptrack ls [-n 50]               List experiments (--tag, --study to filter)
             [--script model_a]     Only runs of one model (substring match)
             [--since 7d]           Only runs since then (7d, 24h, or a date)
             [--param lr=0.01]      Only runs whose param matches (repeatable;
                                      values compare normalized)
  exptrack show <id> [--timeline]   Full details (params, metrics, artifacts, diff)
  exptrack timeline <id> [-c]       Execution timeline (--type to filter events)
  exptrack diff <id>                Colorized git diff from run time
    --patch [-o FILE]                 The raw diff only, for `git apply`
  exptrack compare <id1> <id2>      Side-by-side params + metrics
  exptrack compare <id1> <id2> <id3>...
                                    N-way table: one column per run, a script
                                      row when they differ, varying params only
    --format markdown|html            Print the comparison as tables instead —
                                      the document the dashboard's Compare Copy
                                      makes (--best: best point, not final)
  exptrack vs-reference             Every run measured against the pinned
                                      reference (--script, --study, -n)
  exptrack top [-l 10]              Rank runs by the primary metric
              [--script name]       Only one model
              [--study name]        Only one study
              [--best]              Rank by each run's best point, not its final
              [--include-running] [--exclude-failed]
  exptrack history <nb> [id]        Notebook cell snapshot history
  exptrack watch <id> [--interval]  Live-refresh a running experiment in the terminal
  exptrack studies                  List studies with run counts
  exptrack export <id> [--format]   Export as JSON, Markdown, text, HTML,
                                      CSV/TSV or params
                     [--full]       Every metric point + every artifact
                     [--max-artifacts N] Artifact list cap (0 = all)
  exptrack verify [id] [--backfill] Check artifact file integrity
  exptrack source [id]              Read back the code a run actually ran
                 [--all] [--out DIR]  (from its snapshot, or its notebook cells)

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

Analysis Settings
  exptrack primary-metric <key>     The metric runs are judged by, project-wide
                        [--goal max|min]  Which direction is better
                                            (default: inferred from the name)
                        [--study NAME]    Set for one study instead
                        [--run ID]        Set for one run instead
                        [--clear]         Clear it at that level
  exptrack primary-metric           Show what is set, and where
  exptrack reference <id>           Pin the run everything is measured against
                    [--study NAME]  Set for one study instead of the project
                    [--clear]       Clear it at that level
  exptrack reference                Show what is pinned, and where

Clean Up
  exptrack rm <id>                  Delete run (with confirmation)
             [--trash]              Move to Trash instead (recoverable)
             [--keep-files]         Delete records only, leave output files
             [--shared-files keep|delete]
                                    Files another run also uses, or written
                                      after this run ended: keep them (the
                                      default) or delete them too. Interactive
                                      runs are asked; --yes does not answer this
             [--yes]                Skip the prompt (required to script it)
  exptrack trash                    List runs in the Trash
  exptrack restore-run <id>         Bring a run back out of the Trash
  exptrack clean [--baselines]      Remove all failed runs (or clear code baselines)
                [--older-than 30d]  Delete runs older than N days
                [--all-statuses]    Include done runs (default: only failed)
                [--orphans]         Purge rows not linked to any run; reports
                                      orphaned output files (never deletes silently)
                [--vacuum]          Reclaim free space in the DB file (deletes nothing)
                [--reset]           Wipe every run and reset the DB
                [--dry-run]         List what would be deleted
                [--yes]             Skip the prompt (required to script it)
                                    One selection at a time; --vacuum runs after
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
  exptrack ui [--port 7331]         Launch web dashboard in the foreground
                                      (auto-generates an auth token, prints a
                                      URL with it embedded and opens it in
                                      your browser — Jupyter-style)
    --token <value>                   Persist an auth token to
                                      .exptrack/dashboard_token (gitignored,
                                      mode 600; survives restarts). Without
                                      this a token is generated on first start
                                      and reused afterwards
    --clear-token                     Remove the persisted auth token; the
                                      next start generates a new one, logging
                                      out every browser
    --no-auth                         Disable the auto-generated token
                                      (trusted-local only)
    --host <addr>                     Bind address (default 127.0.0.1)
    --no-browser                      Don't open the dashboard in a browser.
                                      Skipped anyway over SSH, or on Linux
                                      with no display

  exptrack ui start [--port 7331]   Run the dashboard detached in the
                     [--host addr]    background and open it in a browser
                     [--no-browser]   (as `ui` does). Polls until the port
                                      accepts connections; if the child dies
                                      first (e.g. EADDRINUSE) this reports the
                                      tail of the log and exits non-zero
                                      instead of a false "started". Running it
                                      against an already-running dashboard is
                                      success — `exptrack tunnel` chains it on
                                      every invocation. One dashboard serves
                                      every project, so run in a second
                                      worktree it starts nothing: it registers
                                      this project, names the checkout the
                                      dashboard was started from, and prints
                                      the URL that opens *this* project
                                      (`?project=<id>`) with the serving
                                      project's token. An explicit --port that
                                      differs from the running dashboard's is
                                      still refused, since that asks for a
                                      second server on a stated port
  exptrack ui stop [--port]         Stop the background dashboard. Verifies
                   [--force]          the port was actually released, not
                                      merely that a signal was sent; tries
                                      every PID-lookup tool before concluding
                                      nothing is listening. --force escalates
                                      to SIGKILL
  exptrack ui status [--json]       Show whether the background dashboard is
                                      running, its URL (with token) and
                                      version. --json emits machine-readable
                                      output (used by `exptrack tunnel`). Reads
                                      the user-global record
                                      (~/.exptrack/dashboard.json) as well as
                                      this project's, so it answers about the
                                      shared dashboard from a checkout that did
                                      not start it, and the URL names the
                                      project you ran it in. `ui stop` reads
                                      the same record, which is how the shared
                                      dashboard is stopped from anywhere
  exptrack ui logs [-n N] [-f]      Show (or follow, -f) the background
                                      dashboard's log
  exptrack ui-stop [--port 7331]    Deprecated alias for `exptrack ui stop`
                   [--force]

Remote access
  exptrack tunnel add <name>        Save a remote dashboard (stored in
                     --host user@host  ~/.exptrack/remotes.json)
                     --dir DIR         Project directory on the remote
                     [--remote-port]   Remote dashboard port (default 7331)
                     [--local-port]    Local forwarded port (default:
                                      remote-port)
                     [--exptrack-bin]  Path to exptrack on the remote
                                      (default: <dir>/.venv/bin/exptrack)
  exptrack tunnel list              List saved remotes
  exptrack tunnel rm <name>         Remove a saved remote
  exptrack tunnel stop <name>       Close an open tunnel (stops the local SSH
                                      forward; does not stop the remote
                                      dashboard). On Windows, pid lookup
                                      (fuser/lsof) isn't available, so a
                                      running tunnel can't be told apart from
                                      a free local port — close the ssh
                                      process by hand instead
  exptrack tunnel connect <name>    Start the dashboard on the remote (via
                                      `ui start`), forward its port over SSH
                                      in the background, and print a local
                                      URL with the token already in it. Warns
                                      on a version mismatch between the two
                                      machines
  exptrack tunnel <name>            Shorthand for `exptrack tunnel connect
                                      <name>` — but if a remote is ever named
                                      "add", "list", "rm", "stop" or
                                      "connect", it must be reached with the
                                      explicit `exptrack tunnel connect
                                      <name>` form, since the bare form can't
                                      tell a remote name from a subcommand

Projects (the dashboard's switcher reads the same list)
  exptrack project list             List every project this machine knows
                                      about — the user-global registry
                                      (~/.exptrack/projects.json, written by
                                      `exptrack init` and `exptrack ui start`)
                                      plus those other worktrees of the current
                                      repository that already contain an
                                      .exptrack/ directory. A worktree nobody
                                      ever ran exptrack in is not offered as a
                                      project. Each line is a name and a path;
                                      a project that is not healthy also
                                      carries its status and, below it, what to
                                      do about it — `stale` when its .exptrack/
                                      is there but no database was found,
                                      `needs-upgrade` or `too-new` when its
                                      database was written by a different
                                      version of exptrack. Listing those beats
                                      dropping them, which looks like discovery
                                      is broken. A registered project whose
                                      .exptrack/ is gone entirely is the one
                                      case that *is* dropped — and pruned from
                                      the registry, since it cannot come back
                                      on its own. An absence that cannot be
                                      confirmed (an unplugged disk, an
                                      unmounted share) is left alone
  exptrack project forget <name>    Remove a project from the registry by its
                                      name or its path. Registry only: nothing
                                      on disk is touched, and a project that is
                                      still a worktree of the current
                                      repository (and still has its .exptrack/)
                                      keeps being discovered

Permissions
  exptrack fix-perms                Make .exptrack/ private (mode 0700), so
                                      only your account can read the runs
                                      database and the dashboard token. This
                                      is what the "accessible to other users"
                                      warning tells you to run. POSIX only —
                                      on Windows it says so and does nothing,
                                      because access there is governed by NTFS
                                      permissions inherited from your user
                                      profile. exptrack creates the directory
                                      0700 and deliberately never tightens an
                                      existing one on its own, since a
                                      directory you chose to share is yours to
                                      decide about; this command is how you
                                      say otherwise

Notebook
  exptrack notebook-guard           Print a paste-able guard cell so a notebook
                                      runs with OR without exptrack installed
                                      (session magics degrade to no-ops)

Learn / self-documenting
  exptrack examples                 List runnable examples bundled in the install
  exptrack examples <name>          Print one example's source (stdout; run hint
                                      to stderr, so `> train.py` stays clean)
  exptrack examples <name> --copy   Copy it into the current directory
                                      (--force to overwrite)
  exptrack docs [topic]             Open the docs in a browser; omit topic to
                                      list topics (URL always printed as fallback)

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

The three readable forms carry the same content, laid out as tables:

- `markdown` — tables for the run's fields, parameters, metrics, artifacts and
  timeline, then the code changes.
- `text` — the same, aligned into columns for a terminal or a plain-text note.
- `html` — a standalone page with real tables. Open it in a browser, or import
  it into OneNote or Word. `exptrack export <id> --format html > run.html`.

**Code changes** come from the run's stored `git diff`, and come last so they
copy in one go. A table lists each changed file, how many lines were added and
removed, and which lines of the *committed* file each change replaces — the
place it goes. Then **What changed**: each changed line beside the line it
replaced, with both line numbers and the words that changed marked (struck
through / bold in markdown, red / green when pasted into OneNote or Word,
`^` under them in plain text). Last, each file's patch, verbatim: context,
indentation and all, so it applies with `git apply`. When the repository's `origin` is on GitHub,
GitLab or Bitbucket, the commit and each changed range link to that file at
that commit (read from `.git/config`; credentials in the remote URL are never
copied into a link). A run with no stored diff (no git, a compacted or failed
capture) still shows the changed lines it recorded, and says why that is all
there is.

Paths are shown relative to the project root, which the export states once,
and the command is shown as run from that root.

The same file table and patches appear wherever code changes are exported:
the diff document (**Export Diff** / **Copy Diff**, `exptrack compact
--export`), and a two-run comparison (**Compare → Copy / Export .md**,
`exptrack compare <a> <b> --format markdown|html`), where they show the code
change from the older run to the newer one. In CSV/TSV the `code_changes`
cell summarises the same thing per file — `model.py +8/-4 @1-10; train.py
+4/-2 @4-13` — and JSON carries the raw diff as `git_diff`.

For the patch alone, `exptrack diff <id> --patch -o run.patch` writes the raw
diff for `git apply` (the dashboard's **Patch** button downloads the same file).
Prefer `-o` to a shell redirect on Windows, where PowerShell 5's `>` re-encodes
the file and `git apply` then rejects it.

Nothing the old one-line-per-field layout carried was dropped; metric values
keep full precision (only the duration is rounded, to the millisecond). The
dashboard's **Copy → Markdown / tables** puts the markdown and its HTML on the
clipboard together, so a paste into OneNote/Word is tables and a paste into a
markdown editor is markdown. `exptrack compare <a> <b> --format markdown|html`
prints a comparison the same way.

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

---

## Comparing different models

Two models rarely agree on what to call a number. One logs `val_acc`, another
`accuracy`, a TensorBoard writer contributes `val/acc`. Every surface that
matches metrics matches them by name, so those runs shared no metric at all —
the compare table was two rows of `--`. Tell exptrack they are the same
measurement, once, in `.exptrack/config.json`:

```json
{
  "metric_aliases": {
    "val_acc": ["accuracy", "val/acc", "eval_accuracy"],
    "val_loss": ["loss", "eval_loss"]
  }
}
```

The key is the **canonical** name every surface will show; the list is the
spellings that mean it. Nothing is rewritten in the database — remove the alias
and the original keys come back — and any surface that folds two spellings
together says so.

With that in place, the usual loop works across models:

```bash
exptrack ls --script model_a        # just one model's runs
exptrack ls --since 7d --param lr=0.01   # this week's runs at one setting
exptrack top                        # who won, by the primary metric
exptrack top --script model_b       # ...within one model
exptrack compare <a> <b> <c>        # side by side, script row included
exptrack vs-reference               # everything against the run you must beat
```

`compare` with three or more ids prints one column per run, showing the script
when the runs aren't all the same model and only the parameters that actually
vary — with five runs, the constant ones push the differences off screen.

Duplicate detection knows about models too: `model_a.py --lr 0.01` and
`model_b.py --lr 0.01` are reported as *different scripts sharing a
configuration*, not as "you already ran this".

## Which metric a run is judged by

Nearly every summary — the table's **Result** column, the parameter matrix, the
rankings, the charts a run opens on — needs one answer to "what is *the* number
here". `exptrack primary-metric` sets it, and the answer resolves through four
levels, most specific first:

```
run override  →  study override  →  project default  →  heuristic
```

```bash
exptrack primary-metric val_acc              # project default
exptrack primary-metric val_loss --goal min  # state the direction explicitly
exptrack primary-metric f1 --study sweep-a   # just this study
exptrack primary-metric auroc --run abc123   # just this run
exptrack primary-metric                      # show what's set, and where
exptrack primary-metric --clear              # back to the heuristic
```

Two properties are worth knowing, because they are what make the number
trustworthy:

- **A configured metric is never silently substituted.** If the project is
  judged by `val_auroc` and a run never logged it, that run reports the metric
  as *not logged* rather than falling back to whatever it did record. A column
  whose rows each mean a different metric reads as comparable when it isn't.
- **Every answer says where it came from.** The level is reported alongside the
  value, so a *heuristic* pick — exptrack guessing from the keys the run
  happened to log — is shown as a guess rather than as your setting. The
  heuristic runs only when nothing has been configured at any level.

The level is chosen explicitly rather than inferred, because writing to the
wrong one leaves a setting that appears to do nothing: a study or run override
shadows the project default, so setting the project default while a study
override exists changes nothing you can see.

`--goal` states which direction is better. Left off, it is inferred from the
metric's name (`loss`, `err`, `rmse`, `latency`… are lower-is-better), which is
also what colours the deltas in the dashboard.

---

## The run everything is measured against

exptrack already resolves a baseline for every run *chronologically* — the
previous run of the same script, overridable per run with `exptrack variant-of`.
That answers "what did I change since last time". A parameter search asks a
different question constantly: "is this better than the thing I'm trying to
beat?" — where the comparison point is one fixed run, not a moving one.

```bash
exptrack reference abc123               # pin it, project-wide
exptrack reference abc123 --study sweep-a
exptrack reference                      # show what's pinned, and where
exptrack reference --clear
```

The two baselines are kept separate on purpose, and pinning a reference never
rewrites any run's chronological baseline — a run declares what it descends
from, the project declares what it is measured against. In the dashboard they
appear as two strips side by side: **vs previous run** and **vs reference**.

Resolution is study level → project level, and it **stops there**. It never
continues on to "the best run so far" or "the previous run": a baseline that
moves on its own as data arrives is one you cannot reason about. If nothing is
pinned there is no reference, and the comparison is absent rather than quietly
substituted. A reference pointing at a deleted or trashed run is reported as
broken — naming what was set and at which level — rather than reading as "no
reference set", which would hide that the comparison you had been reading
stopped happening.
