# Configuration

exptrack stores config in `.exptrack/config.json`. Safe to commit — no secrets.

```jsonc
{
  // --- Paths ---
  "db":                    ".exptrack/experiments.db",   // where the SQLite database lives
  "outputs_dir":           "outputs",                    // experiment output files go here
  "notebook_history_dir":  ".exptrack/notebook_history", // notebook cell snapshots

  // --- Limits ---
  "max_git_diff_kb":       256,       // skip diffs larger than this (saves DB space)
  "hash_max_mb":           500,       // partial-hash files larger than this (speeds up large artifacts)

  // --- Artifacts ---
  "artifact_strategy":     "reference",  // "reference" (default) = log path only; "copy" = copy file into outputs

  // --- Resume ---
  // Flags in your script's argv that trigger auto-resume of the latest experiment.
  // exptrack run train.py --resume  →  auto-detected, continues same experiment.
  "resume_flags":          ["--resume"],  // add "--continue", "--load-checkpoint", etc. as needed

  // --- Metrics ---
  "metric_keep_every":     1,    // store every Nth metric point (increase to thin large series during training)
  "metric_max_points":     500,  // max points shown on dashboard charts (server-side downsampling)

  // --- Display ---
  "timezone":              "",   // dashboard timezone: "" = UTC, or e.g. "America/New_York"

  // --- Auto-capture toggles ---
  // Turn off specific capture mechanisms if they interfere with your setup
  "auto_capture": {
    "argparse":  true,     // patch ArgumentParser.parse_args()
    "argv":      true,     // fallback: parse raw sys.argv flags
    "notebook":  true      // capture notebook cell changes
  },

  // --- Run naming ---
  // Controls the auto-generated run name: {script}__{params}__{MMDD}_{uid}
  "naming": {
    "max_param_keys": 4,   // max params included in name
    "key_max_len":    8    // param key length limit in name
  },

  // --- Plugins ---
  "plugins": {
    "enabled": []          // list of plugin module names, e.g. ["github_sync"]
  }
}
```

All values are optional — exptrack uses sensible defaults. You only need to add the keys you want to change.
