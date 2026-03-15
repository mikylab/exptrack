"""Tests for exptrack/plugins — plugin registry and lifecycle hooks."""
import sys


class MockPlugin:
    """A test plugin that records lifecycle events."""
    name = "mock"

    def __init__(self, config=None):
        self.events = []
        self.config = config or {}

    def on_start(self, exp):
        self.events.append(("start", exp.id))

    def on_finish(self, exp):
        self.events.append(("finish", exp.id))

    def on_fail(self, exp, error):
        self.events.append(("fail", exp.id, error))

    def on_metric(self, exp, key, value, step):
        self.events.append(("metric", exp.id, key, value, step))


class FailingPlugin:
    """A plugin that raises errors — should be isolated."""
    name = "failing"

    def __init__(self, config=None):
        pass

    def on_start(self, exp):
        raise RuntimeError("plugin start crash")

    def on_finish(self, exp):
        raise RuntimeError("plugin finish crash")

    def on_fail(self, exp, error):
        raise RuntimeError("plugin fail crash")

    def on_metric(self, exp, key, value, step):
        raise RuntimeError("plugin metric crash")


def test_registry_dispatches_lifecycle(tmp_project):
    """Registry correctly dispatches lifecycle events to plugins."""
    from exptrack.plugins import _Registry

    reg = _Registry()
    mock = MockPlugin()
    reg._plugins = [mock]
    reg._loaded = True

    from exptrack.core import Experiment
    exp = Experiment(script="train.py")

    reg.on_start(exp)
    reg.on_metric(exp, "loss", 0.5, 1)
    reg.on_finish(exp)

    assert len(mock.events) == 3
    assert mock.events[0][0] == "start"
    assert mock.events[1] == ("metric", exp.id, "loss", 0.5, 1)
    assert mock.events[2][0] == "finish"

    exp.finish()


def test_registry_isolates_plugin_errors(tmp_project, capsys):
    """Failing plugins don't crash the app — errors are printed to stderr."""
    from exptrack.plugins import _Registry

    reg = _Registry()
    failing = FailingPlugin()
    mock = MockPlugin()
    reg._plugins = [failing, mock]
    reg._loaded = True

    from exptrack.core import Experiment
    exp = Experiment(script="train.py")

    reg.on_start(exp)
    reg.on_metric(exp, "loss", 0.5, 1)

    # Mock should still receive events despite failing plugin
    assert len(mock.events) == 2

    captured = capsys.readouterr()
    assert "plugin start crash" in captured.err
    assert "plugin metric crash" in captured.err

    exp.finish()


def test_registry_load_from_config_only_once(tmp_project):
    """load_from_config is idempotent — only loads once."""
    from exptrack.plugins import _Registry

    reg = _Registry()
    conf = {"plugins": {"enabled": []}}

    reg.load_from_config(conf)
    assert reg._loaded is True

    # Second call is a no-op
    reg.load_from_config(conf)
    assert len(reg._plugins) == 0


def test_on_fail_dispatches(tmp_project):
    """on_fail correctly passes error string."""
    from exptrack.plugins import _Registry

    reg = _Registry()
    mock = MockPlugin()
    reg._plugins = [mock]
    reg._loaded = True

    from exptrack.core import Experiment
    exp = Experiment(script="train.py")

    reg.on_fail(exp, "out of memory")

    assert mock.events[0] == ("fail", exp.id, "out of memory")

    exp.finish()
