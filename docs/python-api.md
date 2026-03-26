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
| `finish()` | Mark as done |
| `fail(error="")` | Mark as failed |
