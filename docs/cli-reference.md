# CLI Reference

All commands run from your project directory (where you ran `exptrack init`).

```
Setup
  exptrack init [name]              Initialize project, create .exptrack/, patch .gitignore
  exptrack init --here              Initialize in current dir (skip git root detection)

Script Tracking
  exptrack run script.py [args]     Run script with automatic param/artifact capture

Shell / SLURM Pipeline
  exptrack run-start [--key val]    Start experiment, print env vars for eval $()
                     [--study name] Group into a study
                     [--stage N]    Set stage number
                     [--stage-name] Stage label (train, eval, etc.)
  exptrack run-finish <id>          Mark done (--metrics file.json to log from JSON)
  exptrack run-fail <id> [reason]   Mark failed
  exptrack log-metric <id> <k> <v>  Log metric (--step N, --file f.json)
  exptrack log-artifact <id> <path> Register output file (--label name)

Inspect
  exptrack ls [-n 50]               List experiments (--tag, --study to filter)
  exptrack show <id> [--timeline]   Full details (params, metrics, artifacts, diff)
  exptrack timeline <id> [-c]       Execution timeline (--type to filter events)
  exptrack diff <id>                Colorized git diff from run time
  exptrack compare <id1> <id2>      Side-by-side params + metrics
  exptrack history <nb> [id]        Notebook cell snapshot history
  exptrack export <id> [--format]   Export as JSON or Markdown
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
  exptrack finish <id>              Manually mark running experiment as done

Clean Up
  exptrack rm <id>                  Delete run (with confirmation)
  exptrack clean [--baselines]      Remove all failed runs (or clear code baselines)
  exptrack stale --hours 24         Mark old running experiments as timed-out

Admin
  exptrack upgrade [--reinstall]    Run database schema migrations
  exptrack storage                  Show DB size, output size, optimization tips
  exptrack ui [--port 7331]         Launch web dashboard
```
