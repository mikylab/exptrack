# Python API

For programmatic use beyond the notebook API:

```python
from exptrack.core import Experiment

# Context manager (auto finish/fail)
with Experiment(name="my_run", params={"lr": 0.01}) as exp:
    exp.log_metric("loss", 0.5, step=1)
    exp.log_metric("loss", 0.3, step=2)
    path = exp.save_output("model.pt")
    torch.save(model.state_dict(), path)

# Manual lifecycle
exp = Experiment(params={"lr": 0.01})
exp.log_params({"optimizer": "adam", "scheduler": "cosine"})
exp.log_metrics({"val_loss": 0.23, "val_acc": 0.91}, step=10)
exp.add_tag("baseline")
exp.add_note("first run with new architecture")
exp.log_artifact("outputs/plot.png", label="training curve")
exp.finish()
```

## Experiment properties

| Property | Description |
|----------|-------------|
| `exp.id` | Unique 12-char hex identifier |
| `exp.name` | Run name (auto-generated or custom) |
| `exp.status` | `"running"`, `"done"`, or `"failed"` |
| `exp.created_at` | ISO timestamp |
| `exp.duration_s` | Duration in seconds (set on finish) |
| `exp.script` | Script path |
| `exp.git_branch` | Git branch at run time |
| `exp.git_commit` | Git commit hash at run time |
| `exp.git_diff` | Full uncommitted diff |
| `exp.tags` | List of tags |
| `exp.notes` | Freeform notes string |

## Experiment methods

| Method | Description |
|--------|-------------|
| `log_param(key, value)` | Log a single parameter |
| `log_params(dict)` | Log multiple parameters |
| `log_metric(key, value, step=None)` | Log a metric value |
| `log_metrics(dict, step=None)` | Log multiple metrics |
| `last_metrics()` | Get latest value for each metric key |
| `add_tag(tag)` | Add a tag |
| `remove_tag(tag)` | Remove a tag |
| `add_note(text)` | Append text to notes |
| `set_note(text)` | Replace notes entirely |
| `output_path(filename)` | Get namespaced path (no artifact registration) |
| `save_output(filename)` | Get namespaced path + register as artifact |
| `log_artifact(path, label="")` | Register an existing file |
| `finish()` | Mark as done |
| `fail(error="")` | Mark as failed |
