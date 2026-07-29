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
  "var_fingerprint_max_mb": 100,      // objects larger than this fall back to a shape/dtype
                                      // signature instead of a content hash (notebook capture)

  // --- Artifacts ---
  "artifact_strategy":     "reference",  // "reference" (default) = log path only; "copy" = copy file into outputs

  // --- Resume ---
  // Flags in your script's argv that trigger auto-resume of the latest experiment.
  // exptrack run train.py --resume  →  auto-detected, continues same experiment.
  "resume_flags":          ["--resume"],  // add "--continue", "--load-checkpoint", etc. as needed

  // --- Metrics ---
  "metric_keep_every":     1,    // store every Nth metric point (increase to thin large series during training)
  "metric_max_points":     500,  // max points shown on dashboard charts (server-side downsampling)
  "metric_commit_interval_ms": 250,  // how long a metric write may sit uncommitted. A commit is an
                                     // fsync, and metrics are the only thing written inside your
                                     // training loop — batching them is ~18x faster on a long run.
                                     // 0 restores a commit per log_metric() call.

  // --- Runs ---
  "auto_trash_failed":     false, // move a run that finishes `failed` straight to Trash,
                                  // so the list only shows runs worth comparing

  // --- Display ---
  "timezone":              "",   // dashboard timezone: "" = UTC, or e.g. "America/New_York"

  // --- Auto-capture toggles ---
  // Turn off specific capture mechanisms if they interfere with your setup
  "auto_capture": {
    "argparse":    true,   // patch ArgumentParser.parse_args()
    "argv":        true,   // fallback: parse raw sys.argv flags
    "notebook":    true,   // capture notebook cell changes (false = Session Trees standalone,
                           // runs started explicitly with %exp_start / start())
    "tensorboard": true    // mirror SummaryWriter.add_scalar/add_scalars/add_histogram
                           // into exptrack's metrics table
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

Two capture settings are also editable from the dashboard under **Settings →
Capture** (`auto_capture.notebook` and `var_fingerprint_max_mb`); both take
effect on the next notebook kernel restart.

## Secrets

`config.json` is meant to be committed, so nothing secret belongs in it. The
dashboard auth token lives in `.exptrack/dashboard_token` (mode 600,
gitignored) — `exptrack ui --token <value>` writes it there. A token found in
an older `config.json` still works, and exptrack prints how to move it.
