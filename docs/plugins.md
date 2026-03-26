# Plugins

Plugins run automatically when experiments start, finish, fail, or log metrics.

## Writing a Plugin

```python
# exptrack/plugins/slack_notify.py
import json, urllib.request
from exptrack.plugins import Plugin

class SlackNotify(Plugin):
    name = "slack_notify"

    def __init__(self, config):
        self.webhook = config.get("webhook_url", "")

    def on_finish(self, exp):
        self._post(f"Run *{exp.name}* finished in {exp.duration_s:.0f}s")

    def on_fail(self, exp, error):
        self._post(f"Run *{exp.name}* FAILED: {error}")

    def _post(self, text):
        if not self.webhook: return
        data = json.dumps({"text": text}).encode()
        urllib.request.urlopen(
            urllib.request.Request(self.webhook, data, {"Content-Type": "application/json"})
        )

plugin_class = SlackNotify
```

## Lifecycle Hooks

| Hook | When |
|------|------|
| `on_start(self, exp)` | Experiment created |
| `on_finish(self, exp)` | Completed successfully |
| `on_fail(self, exp, error)` | Failed |
| `on_metric(self, exp, key, value, step)` | Metric logged |

Override only the hooks you need.

## Enabling

Add to `.exptrack/config.json`:

```json
{
  "plugins": {
    "enabled": ["slack_notify"],
    "slack_notify": {
      "webhook_url": "https://hooks.slack.com/services/T.../B.../xxx"
    }
  }
}
```

## Built-in: GitHub Sync

Appends one JSON line per run to a file in your GitHub repo:

```json
{
  "plugins": {
    "enabled": ["github_sync"],
    "github_sync": {
      "repo": "yourname/yourrepo",
      "file": "experiment_log/runs.jsonl",
      "branch": "main",
      "token_env": "GITHUB_TOKEN"
    }
  }
}
```
