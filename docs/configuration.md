# Configuration

expTrack stores config in `.exptrack/config.json`. This file is safe to commit (no secrets).

```jsonc
{
  // Database and storage paths
  "db":                    ".exptrack/experiments.db",
  "outputs_dir":           "outputs",
  "notebook_history_dir":  ".exptrack/notebook_history",

  // Limits
  "max_git_diff_kb":       256,        // skip diffs larger than this
  "hash_max_mb":           500,        // partial-hash files larger than this

  // Artifact handling
  "artifact_strategy":     "reference", // "reference" or "copy"
  "protect_on_rerun":      true,        // archive old artifacts on path conflict

  // Timezone for dashboard display
  "timezone":              "",          // "" = UTC, or "America/New_York", etc.

  // Auto-capture toggles
  "auto_capture": {
    "argparse":  true,                  // patch ArgumentParser.parse_args()
    "argv":      true,                  // fallback: parse raw sys.argv
    "notebook":  true                   // capture notebook cell changes
  },

  // Run naming
  "naming": {
    "max_param_keys": 4,                // max params included in run name
    "key_max_len":    8                  // param key length limit in name
  },

  // Plugins
  "plugins": {
    "enabled": []                       // list of plugin module names
  }
}
```
