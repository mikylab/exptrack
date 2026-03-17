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
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Experiment


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
