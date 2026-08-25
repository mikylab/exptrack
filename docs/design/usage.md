# Usage reference

The worked quick-reference for the CLI and the notebook magics: the shapes that are hard to guess from `--help` (multi-step pipelines, resume, Session Trees). `CLAUDE.md` has the common paths; `cli/main.py:_DISPATCH` is the authoritative command list, and the user-facing docs are `docs/cli-reference.md` and `docs/session-trees.md`.

## Commands and magics

```bash
# Initialize a project (creates .exptrack/ and patches .gitignore)
exptrack init [project_name]

# Wrap any training script
exptrack run train.py --lr 0.01 --data train
# Or: python -m exptrack train.py --lr 0.01

# Shell/SLURM pipeline integration (single step)
eval $(exptrack run-start --lr 0.01 --epochs 50)
# ... run training ...
exptrack run-finish $EXP_ID --metrics results.json
# or on failure:
exptrack run-fail $EXP_ID "reason"

# Multi-step pipeline (group steps in a study with numbered stages)
# First call sets EXP_STUDY and EXP_STAGE; subsequent calls inherit automatically
eval $(exptrack run-start --study my-run --stage 1 --stage-name train --lr 0.01)
python train.py; exptrack run-finish $EXP_ID
# EXP_STUDY inherited, EXP_STAGE auto-increments to 2
eval $(exptrack run-start --stage-name eval)
./evaluate; exptrack run-finish $EXP_ID

# Resume a previous experiment (auto-detected from script's --resume flag)
# All metrics, artifacts, and params aggregate into the same experiment
exptrack run train.py --output_dir results/ --resume --ckpt results/model.pt

# Shell pipeline resume
eval $(exptrack run-start --resume --lr 0.01)
# or resume a specific experiment:
eval $(exptrack run-start --resume abc123 --lr 0.01)

# Programmatic resume
from exptrack.core import Experiment
exp = Experiment.resume("abc123")    # by ID
exp = Experiment.resume("abc")       # by ID prefix

# Session Trees (notebook only — opt-in, no-op when not started)
#   %exptrack session start "name"        begin a session (must precede other magics)
#   %exptrack checkpoint "label"          mark stable point (snapshots per-checkpoint diff)
#   %exptrack branch "label"              declare intent for the next divergence
#   %%scratch                             cell magic — runs cell, never logged
#   %%setup                               cell magic — recorded-but-secondary prep code (builds a df you reference later): kept on the node's demoted setup store + a muted experiment event, out of cell lineage/diffs
#   %%pin "label"                         cell magic — runs cell, snapshots cell+output as artifact
#   %exptrack promote "label"             link active experiment to current node
#   %exptrack session end                 close session (open branches → abandoned)
#
# Log results after the notebook run has already finished
#   %exp_log test_acc=0.93 train_acc=0.98   attach metrics to this notebook's
#                                           latest run (works post-hoc)
#
# Compare a run against the run you *mean*, not the one that ran last
#   exptrack variant-of <id> <baseline>     declare this run a variant of another
#   exptrack variant-of <id>                clear the link (back to chronological)
#
# Compare different models
#   exptrack ls --script model_a            just one model's runs
#   exptrack top                            rank by the primary metric
#   exptrack compare <a> <b> <c> ...        N-way table (script row + varying params)
#   exptrack vs-reference                   every run vs the pinned reference
#   exptrack ls --since 7d --param lr=0.01  narrow the set by time and config
#   config "metric_aliases": {"val_acc": ["accuracy"]}   one name for one measurement
#
# Recoverable deletes from the terminal
#   exptrack rm <id> --trash                move to Trash instead of deleting
#   exptrack trash                          list what's in the Trash
#   exptrack restore-run <id>               bring it back
#
# Name the metric runs are judged by (project-wide, or one study / one run)
#   exptrack primary-metric val_acc                 project default
#   exptrack primary-metric val_loss --goal min     state the direction
#   exptrack primary-metric f1 --study sweep-a      one study
#   exptrack primary-metric                         show the current setting
#   exptrack primary-metric --clear                 clear (back to the heuristic)
#
# For the complete command list, ask the tool — this file shows the common
# paths, not every subcommand:
#   exptrack --help                 every command
#   exptrack <command> --help       one command's flags
# The authoritative registry is cli/main.py:_DISPATCH; docs/cli-reference.md is
# the user-facing writeup. Both drift less than a list transcribed by hand did.
```

