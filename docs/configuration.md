# Configuration

exptrack stores config in `.exptrack/config.json`. Safe to commit — no secrets.

```jsonc
{
  // --- Paths ---
  "db":                    ".exptrack/experiments.db",   // where the SQLite database lives
  "outputs_dir":           "outputs",                    // experiment output files go here
  "exports_dir":           "exports",                    // "save exports to project folder" target
  "notebook_history_dir":  ".exptrack/notebook_history", // notebook cell snapshots

  // --- Limits ---
  "max_git_diff_kb":       256,       // skip diffs larger than this (saves DB space)
  "git_diff_exclude":      ["*.ipynb"], // pathspecs excluded from every captured diff
                                        // (notebook JSON churn would eat the diff budget)
  "hash_max_mb":           500,       // partial-hash files larger than this (speeds up large artifacts)
  "snapshot_max_kb":       512,       // size cap for the per-run script source snapshot
  "snapshot_max_files":    50,        // most project-local modules a run snapshots alongside
                                      // its script (0 = script only); each is stored once
                                      // across runs, content-addressed
  "var_fingerprint_max_mb": 100,      // objects larger than this fall back to a shape/dtype
                                      // signature instead of a content hash (notebook capture)
  "code_change_max_chars": 20000,     // cap on the "what changed in the code" summary;
                                      // truncation is always stated, never silent
  "max_source_diff_kb":    20,        // cap on a stored per-cell source diff
  "max_cell_source_kb":    50,        // cap on one captured notebook cell's source
  "max_cell_output_chars": 2000,      // cap on one captured cell's output text
  "max_vars_per_cell":     50,        // most variables fingerprinted per cell
  "max_assignment_expr_len": 500,     // longest assignment expression recorded verbatim
  "notebook_history":      false,     // write per-run notebook cell snapshots to disk

  // --- Secrets ---
  // Params whose *name* matches any of these (case-insensitive regex search) have
  // their value stored as ***REDACTED***. Replacing this list replaces the whole
  // rule — keep the entries you still want.
  "param_redact_patterns": ["api.key", "password", "token", "secret", "credential"],

  // --- Artifacts ---
  "artifact_strategy":     "reference",  // "reference" (default) = log path only; "copy" = copy file into outputs

  // --- Resume ---
  // Flags in your script's argv that trigger auto-resume of the latest experiment.
  // exptrack run train.py --resume  →  auto-detected, continues same experiment.
  "resume_flags":          ["--resume"],  // add "--continue", "--load-checkpoint", etc. as needed

  // --- Metrics ---
  "metric_keep_every":     1,    // store 1 of every N points your code logs, per metric key (see below)
  "metric_max_points":     500,  // max points shown on dashboard charts (server-side downsampling)
  "metric_commit_interval_ms": 250,  // how long a metric write may sit uncommitted. A commit is an
                                     // fsync, and metrics are the only thing written inside your
                                     // training loop — batching them is ~18x faster on a long run.
                                     // 0 restores a commit per log_metric() call.

  // --- Which metric a run is judged by ---
  // Resolution is run → study → project → heuristic. A configured metric is
  // never silently substituted: a run that didn't log it reports it as missing
  // rather than falling back to whatever else it happened to record.
  // Either a bare name or {"key": ..., "goal": "min"|"max"}.
  "primary_metric":          "",   // e.g. "val_acc", or {"key": "val_loss", "goal": "min"}
  "primary_metric_by_study": {},   // per study: {"sweep-a": "f1"}
  // Set from the CLI: exptrack primary-metric val_acc [--goal min] [--study S] [--run ID]

  // --- One name for one measurement ---
  // Two models rarely agree on what to call a number. Map a canonical name to
  // the spellings that mean it, and every surface compares them as one metric.
  // Display-level only: each run keeps the key it logged, and removing an alias
  // gives the original names back. Merges are always reported, never silent.
  "metric_aliases":        {},   // {"val_acc": ["accuracy", "val/acc"]}

  // --- The run everything is measured against ---
  "reference_run":          "",  // run id, set by: exptrack reference <id>
  "reference_run_by_study": {},  // per study: {"sweep-a": "<run id>"}
  // Read it with: exptrack vs-reference

  // --- Runs ---
  "auto_trash_failed":     false, // move a run that finishes `failed` straight to Trash,
                                  // so the list only shows runs worth comparing
  "warn_duplicate_runs":   true,  // warn when a run repeats a configuration already tried.
                                  // Three answers are kept distinct: identical rerun,
                                  // same params + different code, same params + different data
  "protect_on_rerun":      true,  // archive an existing run's artifacts on an output-path
                                  // conflict instead of writing over them
  "result_types": ["accuracy", "loss", "auroc", "f1", "precision", "recall",
                   "mse", "mae", "r2", "perplexity", "bleu"],  // result kinds the
                                  // dashboard's Results tab offers

  // --- Display ---
  "timezone":              "",   // dashboard timezone: "" = UTC, or e.g. "America/New_York"

  // --- Auto-capture toggles ---
  // Turn off specific capture mechanisms if they interfere with your setup
  "auto_capture": {
    "argparse":    true,   // patch ArgumentParser.parse_args()
    "argv":        true,   // fallback: parse raw sys.argv flags
    "notebook":    true,   // capture notebook cell changes (false = Session Trees standalone,
                           // runs started explicitly with %exp_start / start())
    "tensorboard": true,   // mirror SummaryWriter.add_scalar/add_scalars/add_histogram
                           // into exptrack's metrics table
    "results_files": ["results.json", "metrics.json", "*_results.json", "*_metrics.json"],
                           // `exptrack run` reads the numbers in these files as metrics
                           // at finish (written during the run; nested dicts -> a/b);
                           // never a key the script logged itself. [] turns it off
    "notebook_new_run_on_hp_change": true,
                           // a notebook hyperparameter changed after the run logged
                           // results finishes that run and starts a new one, instead
                           // of overwriting the value (not under Session Trees)
    "environment": true    // record __version__ of the third-party packages a run
                           // imported (stored once per distinct environment)
  },

  // --- Run naming ---
  // Controls the auto-generated run name: {MonDD}_{script}__{params}__{uid}
  "naming": {
    "max_param_keys": 4,          // max params included in name
    "key_max_len":    8,          // param key length limit in name
    "date_style":     "readable"  // "readable" (Jul28) or "numeric" (legacy MMDD)
  },

  // --- Plugins ---
  "plugins": {
    "enabled": []          // list of plugin module names, e.g. ["github_sync"]
  }
}
```

All values are optional — exptrack uses sensible defaults. You only need to add the keys you want to change.

## Metric thinning (`metric_keep_every`)

This is the one setting that discards data as your run writes it, so it's worth
being precise about what it does.

`metric_keep_every: N` stores **1 of every N points your code logs**, counted
per metric key, and always keeps a key's first point. It counts *points*, not
step numbers — so it behaves the same whether you log every step, every 5th
step, or with no `step` at all:

```python
for i in range(1000):
    if (i + 1) % 5 == 0:
        exp.log_metric("loss", loss, step=i + 1)   # 200 points logged
# metric_keep_every: 10  →  20 points stored
```

**It is a divisor, not a budget.** `metric_keep_every: 1000` does not mean
"keep 1,000 points" — it means "keep one point in every thousand I log", and
there is no write-time setting that caps a series at a target count. The
difference is large in practice: a loop that already logs every 5th step of a
100,000-step run logs 20,000 points, and `metric_keep_every: 1000` stores 20 of
them. If what you want is a readable chart rather than a smaller database, leave
this at `1` — `metric_max_points` already downsamples for display.

Points it drops are never written to the database, so thinning cannot be undone
afterwards. If you aren't sure you want it, leave it at `1` and thin later with
[`exptrack prune`](cli-reference.md), which works on what you already recorded
and always keeps each series' first, last, minimum and maximum point. A run with
thinning active prints a one-line notice to stderr the first time it drops a
point, and states how many points it stored out of how many you logged when it
finishes.

`metric_max_points` is unrelated and non-destructive: it's how many points the
dashboard *draws*, downsampled server-side from everything you stored.

Two capture settings are also editable from the dashboard under **Settings →
Capture** (`auto_capture.notebook` and `var_fingerprint_max_mb`); both take
effect on the next notebook kernel restart.

## Secrets

`config.json` is meant to be committed, so nothing secret belongs in it. The
dashboard auth token lives in `.exptrack/dashboard_token` (mode 600,
gitignored) — `exptrack ui --token <value>` writes it there. A token found in
an older `config.json` still works, and exptrack prints how to move it.
