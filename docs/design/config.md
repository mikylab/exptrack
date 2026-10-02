# Configuration in detail

Every `.exptrack/config.json` key with its default and the reasoning. `CLAUDE.md` lists the frequently-relevant ones; this is the full set.

**The file holds overrides, not the resolved settings.** `load()` merges the
defaults under whatever the file contains, and `save()` writes back only the
keys that still differ from `DEFAULTS` (recursively, so an untouched nested
section leaves no trace). Every setting command hands `save()` the dict `load()`
returned, so writing it verbatim froze all ~40 current defaults into the file —
and because `config.json` is documented as safe to commit, a later change to any
default then silently never applied to that project. One command worked around
it with a private JSON read-modify-write; the other ten did not.

**An unusable value degrades to the documented default, whatever its type.**
`_coerce_numeric` checks every key against its default's type — `int` is
genuinely coerced, and `bool`/`str`/`list`/`dict` are validated and fall back
with a message on stderr. Booleans are checked rather than coerced because
`bool` is an `int` subclass, so coercion would turn a stray `"yes"` into `True`
instead of rejecting it. A text-defaulted key also accepts a dict, since a few
(`primary_metric`) take either a bare name or a `{key, goal}` object.

## Keys

`.exptrack/config.json` defaults:

```json
{
  "db": ".exptrack/experiments.db",
  "outputs_dir": "outputs",
  "exports_dir": "exports",
  "notebook_history_dir": ".exptrack/notebook_history",
  "max_git_diff_kb": 256,
  "git_diff_exclude": ["*.ipynb"],
  "artifact_strategy": "reference",
  "hash_max_mb": 500,
  "var_fingerprint_max_mb": 100,
  "warn_duplicate_runs": true,
  "primary_metric": "",
  "primary_metric_by_study": {},
  "metric_aliases": {},
  "reference_run": "",
  "reference_run_by_study": {},
  "metric_keep_every": 1,
  "metric_max_points": 500,
  "metric_commit_interval_ms": 250,
  "max_assignment_expr_len": 500,
  "timezone": "",
  "resume_flags": ["--resume"],
  "auto_trash_failed": false,
  "snapshot_max_kb": 512,
  "snapshot_max_files": 50,
  "code_change_max_chars": 20000,
  "auto_capture": { "argparse": true, "argv": true, "notebook": true, "tensorboard": true,
                    "results_files": ["results.json", "metrics.json", "*_results.json", "*_metrics.json"],
                    "notebook_new_run_on_hp_change": true, "environment": true },
  "naming": { "max_param_keys": 4, "key_max_len": 8, "date_style": "readable" },
  "plugins": { "enabled": [] }
}
```

`metric_commit_interval_ms` (default 250): how long a metric write may sit
uncommitted, see the **Metric write cost at loop scale** pattern. `0` restores a
commit (one fsync) per `log_metric` call.

`auto_capture.results_files` (default `results.json`, `metrics.json`,
`*_results.json`, `*_metrics.json`): results files `exptrack run` reads metrics
from at finish — only files written during the run, in the cwd, the script's
directory or the run's output dir; top-level numbers, nested dicts flattened to
`outer/inner`; never a key the script already logged. `[]` turns it off; a
value that is not a list of strings degrades to the default
(`__main__._results_file_patterns`).

`auto_capture.notebook_new_run_on_hp_change` (default true): a notebook
hyperparameter changed after the active run logged a metric finishes that run
and starts a new one carrying the other hyperparameters
(`notebook.split_for_hp_change`). Never under Session Trees, never before a
result exists. See the **A notebook run ends where its result does** pattern.

`auto_capture.environment` (default true): record the `__version__` of each
third-party package the run imported (`core/environment.py`), stored once per
distinct environment in `code_snapshots` (`kind='environment'`).

`code_change_max_chars` (default 20000): cap on the `_code_changes` /
`_code_change/cell_N` summary string, applied by
`core/utils.summarize_changed_lines`. See the **A code-change summary must not
hide the change** pattern. An unusable value degrades to the default.

`reference_run` (unset) / `reference_run_by_study` (`{}`): the run everything
else is measured against, project-wide and per study. See the **A pinned
reference is a target, not a lineage** pattern. Resolution stops at the project
level — it never falls through to an implicit substitute.

`warn_duplicate_runs` (default true): print a one-line stderr notice at finish
when a run repeats a configuration already run. See the **Three answers to "I
already ran this"** pattern. Advisory only — never blocks a run.

`primary_metric` (unset) / `primary_metric_by_study` (`{}`): the metric runs are
judged by, project-wide and per study. Either a bare key (`"val_acc"`) or
`{"key": …, "goal": "max"|"min"}`; an omitted goal is inferred from the name.
See the **One primary metric, four levels of saying so** pattern. An unusable
value falls through to the next level rather than leaving runs with no metric.

`metric_aliases` (`{}`): one name for one measurement, across models that name
it differently — `{"val_acc": ["accuracy", "val/acc"]}`. The key is the
**canonical** name every surface will show; the list is the spellings that mean
it. Matching is exact after normalization (case, `-`/space → `_`, and the path
prefix in `train/loss`), never fuzzy: a rule that guessed would eventually merge
two metrics that are genuinely different and average them. Canonicalization is
display-level — stored rows keep the key the run logged, so removing an alias
gives the original keys back — and every surface that folds spellings together
says which ones it folded, and it is applied at **every** metric read boundary — a missed one is not a partial feature but an inconsistent screen (see the "One name for one measurement" pattern). Without this, two models logging the same measurement
under different names shared no metric at all: the compare table was two rows of
`--` and consensus ranking excluded one of them. See `core/metric_alias.py`.

Metric aliases are also what make `exptrack top`, `vs-reference` and the
Compare surfaces able to rank models against each other at all: `consensus_metric`
picks the key most runs logged, and two spellings of one measurement split that
vote.

`auto_trash_failed` (default false): when true, a run that finishes `failed` is
moved straight to Trash at finish time, so the experiment list only shows runs
worth comparing. `snapshot_max_files` (default 50): how many project-local modules a
run snapshots alongside its entry script — `0` means the script only. Each module is
stored content-addressed, so unchanged files cost one copy across every run that
imported them; hitting the cap records `_code_files_truncated` rather than presenting a
partial capture as the whole of what ran. `snapshot_max_kb` (default 512): size cap for the content-addressed
script/shell-script source snapshot stored in `code_snapshots` (see the
**Run-vs-run loop** pattern).

## An unusable value degrades to the default — enforced at load, not per call site

Type checking covers **every** key, not just the numeric ones. It used to check
only integers, so a string-typed key given a number — `"db": 123` — reached
`get_db()` as an int and raised a `TypeError` on every single command. Text keys
also accept an object where one is documented (`primary_metric` takes either
`"val_acc"` or `{"key": …, "goal": …}`), and their own parser validates that.

`config.json` is documented as safe to hand-edit, so a value can be any JSON the
user types. Many numeric caps (`var_fingerprint_max_mb`, `max_cell_source_kb`,
`max_vars_per_cell`, `naming.max_param_keys`, …) are then read with a bare
`int(...)` deep in the capture path. That is the crash surface: a value like
`"var_fingerprint_max_mb": "lots"` passed straight through `load()` (which only
*merges* user JSON over the defaults, never validated types) and raised
`ValueError` inside `_capture_variables`. Caught only at the top-level capture
boundary, it aborted capture on **every notebook cell** — the run recorded
nothing while printing a traceback each time. That is the exact failure the
config invariant forbids: *an unusable value must always degrade to the
documented default; a hand-edited config must never be the reason a run records
nothing.*

`config._coerce_numeric(DEFAULTS, merged)` enforces it **once, at load**, rather
than at each of the scattered `int(...)` call sites (which would drift). For
every key whose default is an `int`, it coerces the merged value; a clean string
number (`"50"`) becomes `50`, and anything unparseable falls back to the default
with a one-line stderr note. Bools are skipped — `bool` is an `int` subclass but
the boolean settings are read as booleans, never through the `int` path — and it
recurses into nested dicts (`naming.*`). The consequence downstream: every
`int(_conf[...])` in the capture layer is now reading a value already guaranteed
to be an `int`, so the crash class is gone at the source rather than patched
reader by reader.

## Keys the full listing above did not cover

`protect_on_rerun` (default `true`) — on an output-path conflict, archive the
existing run's artifacts rather than writing over them.

`result_types` (default: `accuracy`, `loss`, `auroc`, `f1`, `precision`,
`recall`, `mse`, `mae`, `r2`, `perplexity`, `bleu`) — the named result kinds the
dashboard's Results tab offers.

`notebook_history` (default `false`) — whether per-run notebook cell snapshots
are written under `notebook_history_dir`. Off by default; the in-database
timeline is unaffected either way.

`max_cell_output_chars` (2000), `max_source_diff_kb` (20), `max_cell_source_kb`
(50), `max_vars_per_cell` (50), `max_assignment_expr_len` (500) — per-cell
capture caps. All truncate *visibly*: the stored value carries its truncation
marker, because a silently shortened diff reads as a smaller change than
actually happened.

`param_redact_patterns` (default `["api.key", "password", "token", "secret",
"credential"]`) — case-insensitive **regex** patterns matched against a
parameter's *name*; a match stores `***REDACTED***` as the value. Setting this
key **replaces** the list rather than extending it, so a project adding one
pattern of its own must repeat the entries it still wants — worth stating,
because the failure is silent and un-redacts secrets.

## User-global state: `~/.exptrack/projects.json`

Everything above is per-project and lives in that project's
`.exptrack/config.json`. The project *registry* is the other kind of fact — a
property of the machine and the user rather than of any one checkout — so it
lives in `config.user_dir()`, which is `~/.exptrack/` (created 0700), beside
`remotes.json`. Being outside every project **and outside every virtualenv** is
the point: a machine with a venv-local exptrack per checkout still has one set
of known projects, because whichever install's `exptrack` you run reads the same
file.

The file is a single JSON object keyed by the project's resolved absolute path:

```json
{
  "/work/proj": { "name": "proj" },
  "/work/proj-featureX": { "name": "proj-featureX" }
}
```

`name` defaults to the directory's own name and is what `exptrack project list`
and the dashboard's switcher display. The path is the key because it is the
identity; the id the dashboard uses (`projects.project_id`) is derived from it
and is never stored.

**Mode 0600, written atomically.** The file is created through
`config.open_private`, so the mode is set at creation rather than after it, and
a write lands on a temp file beside the target which `os.replace` then swaps in.
An in-place truncating write that is interrupted would leave unparseable JSON;
that degrades to "nothing registered" on the next read, and the *next*
`register()` would then write only its own entry over the empty file, silently
losing every other project the user had.

**Who writes it.** `exptrack init` and `exptrack ui start`, and nothing else.
Registering from arbitrary commands would mean a user-global file write from
every CLI invocation, including ones inside a training loop. Discovery does not
depend on the registry alone: the other worktrees of the current repository are
found through `git worktree list` and need no registration, though a worktree is
only offered as a project once it actually has an `.exptrack/` directory —
otherwise every worktree of the repository, including ones nobody ever ran
exptrack in, would be listed as a project with no data.

Entries are removed with `exptrack project forget <name|path>`, or from the
dashboard's switcher, whose dismiss control posts to `/api/project/forget` and
calls the same `projects.forget` function rather than reimplementing it. The
browser names the project by its **server-issued id**, never by a path — the id
is resolved against the same discovery listing the switcher was drawn from, and
an id that listing does not contain is refused rather than guessed at. Either
way, forgetting edits this file and nothing else: the project's database and
every file under its root are left exactly as they were, and the in-process
discovery cache is invalidated, so the next listing already shows the removal.

An unreadable or hand-mangled registry degrades to "no projects registered"
rather than raising — the same rule `config.json` holds for per-project
settings. A *registered* project whose directory or database has gone is still
listed, marked `stale`: an entry that silently disappears is indistinguishable
from discovery being broken.
