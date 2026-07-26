"""
exptrack/plugins — Plugin base class + event registry

Plugins hook into experiment lifecycle events:
  on_start(exp)            — experiment just created
  on_finish(exp)           — experiment finished successfully
  on_fail(exp, error)      — experiment failed
  on_metric(exp, key, val) — metric logged
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Experiment


def make_exp_proxy(conn, exp_id: str, status: str = "done", duration_s=None):
    """Build a plugin-facing experiment stand-in from DB rows.

    The lifecycle-command paths (``exptrack finish``, ``exptrack run-finish``)
    have no live ``Experiment`` object to hand to plugins, so they build a
    lightweight namespace from the DB. Plugins like ``github_sync`` read the
    full interface (``project``, ``created_at``, ``duration_s``, ``script``,
    ``git_*``, ``_params``, ``last_metrics()``, ``tags`` as a **list**,
    ``notes``); an incomplete proxy makes every sync silently ``AttributeError``
    inside the registry's try/except. This is the single, complete builder both
    paths use.
    """
    from .. import config as cfg
    from ..core.queries import get_params_batch, last_metrics
    row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
    # SIM118 is suppressed below: `row` is a sqlite3.Row, not a dict —
    # iterating it yields values, so .keys() is the only way to get the
    # column names and `for k in row` would be a bug.
    p = types.SimpleNamespace(**{k: row[k] for k in row.keys()})  # noqa: SIM118
    p.status = status
    p.duration_s = duration_s if duration_s is not None else row["duration_s"]
    p.tags = json.loads(row["tags"] or "[]")
    # `project` may be NULL on manually-created rows; derive it like Experiment.
    p.project = row["project"] or cfg.load().get("project", cfg.project_root().name)
    # Reuse the batch param loader (tolerates malformed JSON values).
    p._params = get_params_batch(conn, [exp_id]).get(exp_id, {})
    p.last_metrics = lambda: last_metrics(conn, exp_id)
    return p


class Plugin:
    """Base class for exptrack plugins."""
    name: str = ""

    def __init__(self, config: dict) -> None:
        pass

    def on_start(self, exp: Experiment) -> None:
        pass

    def on_finish(self, exp: Experiment) -> None:
        pass

    def on_fail(self, exp: Experiment, error: str) -> None:
        pass

    def on_metric(self, exp: Experiment, key: str, value: float, step: int | None) -> None:
        pass


class _Registry:
    """Singleton that holds loaded plugin instances and dispatches events."""

    def __init__(self) -> None:
        self._plugins: list[Plugin] = []
        self._loaded = False

    def load_from_config(self, conf: dict) -> None:
        if self._loaded:
            return
        self._loaded = True

        plugin_conf = conf.get("plugins", {})
        enabled = plugin_conf.get("enabled", [])

        for name in enabled:
            try:
                mod = importlib.import_module(f".{name}", package=__name__)
                cls = getattr(mod, "plugin_class", None)
                if cls is None:
                    print(f"[exptrack] Plugin '{name}' has no plugin_class", file=sys.stderr)
                    continue
                instance = cls(plugin_conf.get(name, {}))
                self._plugins.append(instance)
            except Exception as e:
                print(f"[exptrack] Failed to load plugin '{name}': {e}", file=sys.stderr)

    def on_start(self, exp: Experiment) -> None:
        for p in self._plugins:
            try:
                p.on_start(exp)
            except Exception as e:
                print(f"[exptrack] Plugin {p.name} on_start error: {e}", file=sys.stderr)

    def on_finish(self, exp: Experiment) -> None:
        for p in self._plugins:
            try:
                p.on_finish(exp)
            except Exception as e:
                print(f"[exptrack] Plugin {p.name} on_finish error: {e}", file=sys.stderr)

    def on_fail(self, exp: Experiment, error: str) -> None:
        for p in self._plugins:
            try:
                p.on_fail(exp, error)
            except Exception as e:
                print(f"[exptrack] Plugin {p.name} on_fail error: {e}", file=sys.stderr)

    def on_metric(self, exp: Experiment, key: str, value: float, step: int | None) -> None:
        for p in self._plugins:
            try:
                p.on_metric(exp, key, value, step)
            except Exception as e:
                print(f"[exptrack] Plugin {p.name} on_metric error: {e}", file=sys.stderr)


registry = _Registry()
