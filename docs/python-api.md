# Python API

## Basic Usage

```python
from exptrack.core import Experiment

with Experiment(name="my_run", params={"lr": 0.01}) as exp:
    for epoch in range(100):
        loss, acc = train(...)
        exp.log_metrics({"loss": loss, "accuracy": acc}, step=epoch)

    path = exp.save_output("model.pt")
    torch.save(model.state_dict(), path)
```

The context manager auto-marks the run as done (or failed on exception).

## Manual Lifecycle

```python
exp = Experiment(params={"lr": 0.01})
exp.log_params({"optimizer": "adam", "scheduler": "cosine"})
exp.log_metrics({"val_loss": 0.23, "val_acc": 0.91}, step=10)
exp.add_tag("baseline")
exp.add_note("first run with new architecture")
exp.log_artifact("outputs/plot.png", label="training curve")
exp.finish()   # or exp.fail("reason")
```

## Resuming an Experiment

```python
from exptrack.core import Experiment

# Resume by ID (or prefix)
exp = Experiment.resume("abc123")

# All new metrics/artifacts append to the same experiment
for epoch in range(50, 100):
    loss = train(...)
    exp.log_metric("loss", loss, step=epoch)

exp.finish()
```

The original params, tags, timeline, and artifacts are preserved. New data appends to the same experiment ID. Status is set back to `"running"` until you call `finish()`.

With `exptrack run`, resume is auto-detected from the script's own `--resume` flag — no extra flags needed:

```bash
# First run creates a new experiment
exptrack run train.py --lr 0.01 --epochs 50

# Resume continues the same experiment
exptrack run train.py --lr 0.01 --epochs 100 --resume --ckpt model.pt
```

## `exptrack run` vs Python API

With `exptrack run train.py`, params and artifacts are captured automatically — you just need `exp = globals().get("__exptrack__")` to log metrics. With the Python API, you manage the full lifecycle yourself. Use `exptrack run` for minimal changes; use the API when you want full control.

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | str | Unique 12-char hex identifier |
| `name` | str | Run name (auto-generated or custom) |
| `status` | str | `"running"`, `"done"`, or `"failed"` |
| `created_at` | str | ISO timestamp |
| `duration_s` | float | Duration in seconds (set on finish) |
| `script` | str | Script path |
| `git_branch` | str | Git branch at run time |
| `git_commit` | str | Git commit hash |
| `git_diff` | str | Full uncommitted diff |
| `tags` | list | Tags |
| `notes` | str | Freeform notes |

## Methods

| Method | Description |
|--------|-------------|
| `log_param(key, value)` | Log a single parameter |
| `log_params(dict)` | Log multiple parameters |
| `log_metric(key, value, step=None)` | Log a single metric |
| `log_metrics(dict, step=None)` | Log multiple metrics at once |
| `last_metrics()` | Latest value for each metric key |
| `add_tag(tag)` | Add a tag |
| `remove_tag(tag)` | Remove a tag |
| `add_note(text)` | Append to notes |
| `set_note(text)` | Replace notes entirely |
| `output_path(filename)` | Get namespaced path (no artifact registration) |
| `save_output(filename)` | Get namespaced path + register as artifact |
| `log_artifact(path, label="")` | Register an existing file |
| `log_file(path, label="")` | Alias of `log_artifact` |
| `log_event(...)` | Append a custom timeline event |
| `batched_writes()` | *context manager* — collapse the writes inside it into one transaction |
| `flush_metrics()` | Commit any metrics still inside the batching window |
| `finish()` | Mark as done |
| `fail(error="", traceback=None)` | Mark as failed, storing the full traceback when given |
| `resume(exp_id)` | *classmethod* — Reopen a finished experiment to continue it |

## Constructor arguments

```python
Experiment(name=None, params=None, tags=None, notes="", script=None,
           command=None, thin_every=None)
```

`name` — omit it and exptrack generates one (`Jul28_train__lr0.01__2aac1081`)
and flags the run as auto-named, so the dashboard's **Needs naming** filter can
find it later. `thin_every=N` stores every Nth metric point for this run,
overriding the `metric_keep_every` config default. `command` records the real
launch command for the dashboard's reproduce box.

## Writing a lot of metrics

Metric writes are committed at most once per `metric_commit_interval_ms`
(default 250 ms), because a commit is an fsync and metrics are the only thing
exptrack writes inside your training loop. You don't need to do anything for
this — every ordinary exit flushes, including `finish()`, `fail()`, the context
manager, and interpreter shutdown on a script that never called `finish()`.

For a burst of *non-metric* writes (params, tags, timeline events), wrap them:

```python
with exp.batched_writes():
    exp.log_params(big_config_dict)
    exp.add_tag("sweep")
```

## Adoption under `exptrack run`

A script written for plain `python train.py` that creates its own bare
`Experiment()` does **not** get a second, metrics-less run when you launch it
with `exptrack run train.py` — it adopts the wrapper exptrack already created.
Adoption is deliberately narrow: only a bare `Experiment()` with no arguments
adopts, and only the first one. A sweep that constructs experiments with its own
names/params keeps its independent rows (and the empty wrapper is moved to
Trash rather than left behind).
