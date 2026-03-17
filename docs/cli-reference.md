# CLI Reference

```
Project setup
  exptrack init [name]              Initialize project, patch .gitignore
  exptrack init --here              Initialize in current dir (not git root)

Script tracking
  exptrack run script.py [args]     Run script with automatic tracking

Shell/SLURM pipeline
  exptrack run-start [--key val]    Start experiment, print env vars for eval $()
                     [--study name] Add to study (groups pipeline steps)
                     [--stage N]    Set stage number
                     [--stage-name] Stage label (e.g. train, eval)
  exptrack run-finish <id>          Mark done (--metrics file.json)
  exptrack run-fail <id> [reason]   Mark failed
  exptrack log-metric <id> <k> <v>  Log metric (--step N, --file f.json)
  exptrack log-artifact <id> <path> Register output file (--label name)

Inspection
  exptrack ls [-n 50]               List experiments (--tag, --study filters)
  exptrack show <id> [--timeline]   Full details (params, metrics, artifacts, diff)
  exptrack timeline <id> [-c]       Execution timeline (--type event_type)
  exptrack diff <id>                Colorized git diff captured at run time
  exptrack compare <id1> <id2>      Side-by-side params + metrics
  exptrack history <nb> [id]        Notebook cell snapshot history
  exptrack export <id> [--format]   Export as JSON or Markdown
  exptrack verify [id] [--backfill] Check artifact file integrity

Management
  exptrack tag <id> <tag>           Add tag
  exptrack untag <id> <tag>         Remove tag
  exptrack delete-tag <tag>         Delete a tag from all experiments
  exptrack study <id> <name>        Add experiment to a study
  exptrack unstudy <id> <name>      Remove experiment from a study
  exptrack delete-study <name>      Delete a study from all experiments
  exptrack stage <id> <N> [--name]  Set stage number and optional label
  exptrack note <id> "text"         Append note
  exptrack edit-note <id> "text"    Replace notes
  exptrack rm <id>                  Delete run
  exptrack clean [--baselines]      Remove all failed runs (or clear baselines)
  exptrack finish <id>              Manually mark running experiment as done
  exptrack stale --hours 24         Mark old running experiments as timed-out

Admin
  exptrack upgrade [--reinstall]    Run schema migrations
  exptrack storage                  Show storage breakdown and optimization tips
  exptrack ui [--port 7331]         Launch web dashboard
```
