"""Tests for exptrack/capture/notebook_hooks.py — IPython post_run_cell hook."""
from __future__ import annotations

import json


# ── Mock IPython objects ─────────────────────────────────────────────────────

class MockEvents:
    """Minimal IPython events manager."""
    def __init__(self):
        self._hooks: dict[str, list] = {}

    def register(self, event: str, fn):
        self._hooks.setdefault(event, []).append(fn)

    def unregister(self, event: str, fn):
        if event in self._hooks and fn in self._hooks[event]:
            self._hooks[event].remove(fn)
        else:
            raise ValueError("not registered")


class MockShell:
    """Minimal IPython shell for testing notebook hooks."""
    def __init__(self):
        self.user_ns = {"In": [""], "Out": {}}
        self.events = MockEvents()
        self.execution_count = 0


class MockResult:
    """Minimal execution result."""
    def __init__(self, raw_cell: str, result=None):
        self.info = type("Info", (), {"raw_cell": raw_cell, "result": result})()
        self.result = result
        self.error_in_exec = None
        self.error_before_exec = None


# ── Helper to reset hook state ───────────────────────────────────────────────

def _reset_nb_state():
    """Reset the notebook hooks global state to a clean slate."""
    from exptrack.capture.notebook_hooks import _nb_state
    _nb_state["exp"] = None
    _nb_state["ip"] = None
    _nb_state["nb_name"] = ""
    _nb_state["cell_history"] = {}
    _nb_state["var_snapshot"] = {}
    _nb_state["exec_count"] = 0
    _nb_state["cells_ran"] = []
    _nb_state["first_run"] = True
    _nb_state["deferred"] = False
    _nb_state["deferred_start_fn"] = None
    _nb_state["deferred_nb_file"] = ""
    _nb_state["last_cell_hash"] = None
    _nb_state["hash_to_last_exec_hash"] = {}


# ── Tests for _is_magic_only ─────────────────────────────────────────────────

def test_is_magic_only_true():
    from exptrack.capture.notebook_hooks import _is_magic_only
    assert _is_magic_only("%load_ext exptrack") is True
    assert _is_magic_only("%magic\n%another") is True
    assert _is_magic_only("# just a comment\n%magic") is True
    assert _is_magic_only("!pip install foo") is True


def test_is_magic_only_false():
    from exptrack.capture.notebook_hooks import _is_magic_only
    assert _is_magic_only("x = 1") is False
    assert _is_magic_only("%magic\nx = 1") is False
    assert _is_magic_only("print(42)") is False


# ── Tests for _get_cell_source ───────────────────────────────────────────────

def test_get_cell_source_from_result():
    from exptrack.capture.notebook_hooks import _get_cell_source
    ip = MockShell()
    result = MockResult("x = 42")
    source, output = _get_cell_source(result, ip)
    assert source == "x = 42"


def test_get_cell_source_from_In_fallback():
    from exptrack.capture.notebook_hooks import _get_cell_source
    ip = MockShell()
    ip.user_ns["In"] = ["", "fallback_source"]
    # result with no raw_cell
    result = type("R", (), {})()
    source, output = _get_cell_source(result, ip)
    assert source == "fallback_source"


def test_get_cell_source_none_result():
    from exptrack.capture.notebook_hooks import _get_cell_source
    ip = MockShell()
    source, output = _get_cell_source(None, ip)
    assert source is None or source == ""


# ── Tests for _handle_deferred_start ─────────────────────────────────────────

def test_deferred_skips_magic_cell(tmp_project):
    from exptrack.capture.notebook_hooks import _handle_deferred_start, _nb_state
    _reset_nb_state()
    _nb_state["deferred"] = True
    _nb_state["deferred_start_fn"] = lambda nb, ip=None: None
    ip = MockShell()

    # Magic cell should be skipped
    assert _handle_deferred_start("%load_ext exptrack", ip) is True
    # Still deferred after magic
    assert _nb_state["deferred"] is True


def test_deferred_starts_on_real_cell(tmp_project):
    from exptrack.capture.notebook_hooks import _handle_deferred_start, _nb_state
    _reset_nb_state()

    started = []

    def fake_start(nb_file, ip=None):
        from exptrack.core import Experiment
        exp = Experiment(script="notebook.py")
        _nb_state["exp"] = exp
        started.append(True)

    _nb_state["deferred"] = True
    _nb_state["deferred_start_fn"] = fake_start
    ip = MockShell()

    # Real cell should trigger start
    assert _handle_deferred_start("x = 1", ip) is False
    assert _nb_state["deferred"] is False
    assert len(started) == 1

    # Cleanup
    if _nb_state["exp"]:
        _nb_state["exp"].finish()


def test_deferred_no_double_start(tmp_project):
    """If exp already set (by explicit start()), deferred_start_fn is not called."""
    from exptrack.capture.notebook_hooks import _handle_deferred_start, _nb_state
    from exptrack.core import Experiment

    _reset_nb_state()
    exp = Experiment(script="nb.py")
    _nb_state["exp"] = exp
    _nb_state["deferred"] = True

    called = []
    _nb_state["deferred_start_fn"] = lambda nb, ip=None: called.append(True)

    ip = MockShell()
    _handle_deferred_start("x = 1", ip)

    # start_fn should NOT have been called since exp already exists
    assert len(called) == 0

    exp.finish()


# ── Tests for attach_notebook ────────────────────────────────────────────────

def test_attach_registers_hook(tmp_project):
    from exptrack.capture.notebook_hooks import attach_notebook, _nb_state, _post_run_cell
    from exptrack.core import Experiment

    _reset_nb_state()
    exp = Experiment(script="test.py")
    ip = MockShell()

    attach_notebook(exp, nb_name="test_nb", ip=ip)

    assert _nb_state["exp"] is exp
    assert _nb_state["nb_name"] == "test_nb"
    assert _post_run_cell in ip.events._hooks.get("post_run_cell", [])

    exp.finish()


def test_detach_removes_hook(tmp_project):
    from exptrack.capture.notebook_hooks import (
        attach_notebook, detach_notebook, _nb_state, _post_run_cell
    )
    from exptrack.core import Experiment

    _reset_nb_state()
    exp = Experiment(script="test.py")
    ip = MockShell()

    attach_notebook(exp, nb_name="test_nb", ip=ip)
    _nb_state["ip"] = ip
    detach_notebook()

    assert _nb_state["exp"] is None
    assert _post_run_cell not in ip.events._hooks.get("post_run_cell", [])

    exp.finish()


# ── Tests for _capture_variables ─────────────────────────────────────────────

def test_capture_variables_new(tmp_project):
    """New variables are detected on first capture."""
    from exptrack.capture.notebook_hooks import _capture_variables, _nb_state
    _reset_nb_state()
    _nb_state["var_snapshot"] = {}

    ip = MockShell()
    ip.user_ns = {"In": [], "Out": {}, "x": 42, "name": "hello"}

    new_vars, changed_vars = _capture_variables(ip, {"x": "42", "name": "'hello'"})
    assert "x" in new_vars
    assert "name" in new_vars
    assert len(changed_vars) == 0


def test_capture_variables_changed(tmp_project):
    """Changed variables are detected on subsequent capture."""
    from exptrack.capture.notebook_hooks import _capture_variables, _nb_state
    _reset_nb_state()

    ip = MockShell()

    # First capture: set initial state
    ip.user_ns = {"In": [], "Out": {}, "x": 1}
    _capture_variables(ip, {"x": "1"})

    # Second capture: x changed
    ip.user_ns = {"In": [], "Out": {}, "x": 2}
    new_vars, changed_vars = _capture_variables(ip, {"x": "2"})
    assert "x" in changed_vars
    assert len(new_vars) == 0


def test_capture_variables_skips_internal(tmp_project):
    """Internal IPython names are skipped."""
    from exptrack.capture.notebook_hooks import _capture_variables, _nb_state
    _reset_nb_state()

    ip = MockShell()
    ip.user_ns = {"In": [], "Out": {}, "get_ipython": lambda: None, "_private": 1}

    new_vars, changed_vars = _capture_variables(ip, {})
    assert "In" not in new_vars
    assert "Out" not in new_vars
    assert "get_ipython" not in new_vars
    assert "_private" not in new_vars


# ── Tests for full _post_run_cell cycle ──────────────────────────────────────

def test_post_run_cell_creates_timeline_event(tmp_project):
    """Running _post_run_cell on a real cell creates a timeline event."""
    from exptrack.capture.notebook_hooks import (
        _post_run_cell, _nb_state, attach_notebook
    )
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    _reset_nb_state()
    exp = Experiment(script="test_nb.py")
    ip = MockShell()
    attach_notebook(exp, nb_name="test_nb", ip=ip)

    # Simulate cell execution
    result = MockResult("x = 42")
    ip.user_ns["x"] = 42
    _post_run_cell(result)

    # Check timeline has events
    conn = get_db()
    rows = conn.execute(
        "SELECT event_type, key FROM timeline WHERE exp_id=?", (exp.id,)
    ).fetchall()

    event_types = [r["event_type"] for r in rows]
    assert "cell_exec" in event_types

    exp.finish()


def test_post_run_cell_detects_variable(tmp_project):
    """post_run_cell emits var_set event for new variables."""
    from exptrack.capture.notebook_hooks import (
        _post_run_cell, _nb_state, attach_notebook
    )
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    _reset_nb_state()
    exp = Experiment(script="test_nb.py")
    ip = MockShell()
    attach_notebook(exp, nb_name="test_nb", ip=ip)

    result = MockResult("lr = 0.01")
    ip.user_ns["lr"] = 0.01
    _post_run_cell(result)

    conn = get_db()
    rows = conn.execute(
        "SELECT event_type, key FROM timeline WHERE exp_id=? AND event_type='var_set'",
        (exp.id,)
    ).fetchall()

    var_keys = [r["key"] for r in rows]
    assert "lr" in var_keys

    exp.finish()


def test_post_run_cell_hp_auto_param(tmp_project):
    """HP-named variables (lr, epochs, etc.) are auto-logged as params."""
    from exptrack.capture.notebook_hooks import (
        _post_run_cell, _nb_state, attach_notebook
    )
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    _reset_nb_state()
    exp = Experiment(script="test_nb.py")
    ip = MockShell()
    attach_notebook(exp, nb_name="test_nb", ip=ip)

    result = MockResult("lr = 0.001")
    ip.user_ns["lr"] = 0.001
    _post_run_cell(result)

    # lr should be logged as a top-level param
    assert exp._params.get("lr") == 0.001

    exp.finish()


def test_post_run_cell_observational(tmp_project):
    """Observational cells get event_type='observational'."""
    from exptrack.capture.notebook_hooks import (
        _post_run_cell, _nb_state, attach_notebook
    )
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    _reset_nb_state()
    exp = Experiment(script="test_nb.py")
    ip = MockShell()
    attach_notebook(exp, nb_name="test_nb", ip=ip)

    result = MockResult("print(42)")
    _post_run_cell(result)

    conn = get_db()
    rows = conn.execute(
        "SELECT event_type FROM timeline WHERE exp_id=?", (exp.id,)
    ).fetchall()

    event_types = [r["event_type"] for r in rows]
    assert "observational" in event_types

    exp.finish()


def test_post_run_cell_error_does_not_crash(tmp_project):
    """A cell execution error (e.g., bad result object) doesn't crash the hook."""
    from exptrack.capture.notebook_hooks import (
        _post_run_cell, _nb_state, attach_notebook
    )
    from exptrack.core import Experiment

    _reset_nb_state()
    exp = Experiment(script="test_nb.py")
    ip = MockShell()
    attach_notebook(exp, nb_name="test_nb", ip=ip)

    # Pass a broken result object — should not raise
    broken_result = type("Broken", (), {})()
    _post_run_cell(broken_result)

    exp.finish()


def test_post_run_cell_no_exp_is_noop(tmp_project):
    """If no experiment is attached, _post_run_cell is a no-op."""
    from exptrack.capture.notebook_hooks import _post_run_cell, _nb_state

    _reset_nb_state()
    ip = MockShell()
    _nb_state["ip"] = ip

    # Should not raise
    result = MockResult("x = 1")
    _post_run_cell(result)


def test_post_run_cell_cell_lineage_stored(tmp_project):
    """Cell lineage is stored after execution."""
    from exptrack.capture.notebook_hooks import (
        _post_run_cell, _nb_state, attach_notebook
    )
    from exptrack.capture.cell_lineage import cell_hash, get_cell_source
    from exptrack.core import Experiment

    _reset_nb_state()
    exp = Experiment(script="test_nb.py")
    ip = MockShell()
    attach_notebook(exp, nb_name="test_nb", ip=ip)

    source = "result = 2 + 2"
    result = MockResult(source)
    ip.user_ns["result"] = 4
    _post_run_cell(result)

    # Cell source should be retrievable by hash
    ch = cell_hash(source)
    stored = get_cell_source(ch)
    assert stored == source

    exp.finish()


def test_post_run_cell_multiple_cells(tmp_project):
    """Multiple cells execute sequentially with proper exec_count tracking."""
    from exptrack.capture.notebook_hooks import (
        _post_run_cell, _nb_state, attach_notebook
    )
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    _reset_nb_state()
    exp = Experiment(script="test_nb.py")
    ip = MockShell()
    attach_notebook(exp, nb_name="test_nb", ip=ip)

    # Cell 1
    result1 = MockResult("a = 1")
    ip.user_ns["a"] = 1
    _post_run_cell(result1)

    # Cell 2
    result2 = MockResult("b = 2")
    ip.user_ns["b"] = 2
    _post_run_cell(result2)

    assert _nb_state["exec_count"] == 2

    conn = get_db()
    cell_events = conn.execute(
        "SELECT key FROM timeline WHERE exp_id=? AND event_type='cell_exec' ORDER BY seq",
        (exp.id,)
    ).fetchall()

    assert len(cell_events) == 2
    assert cell_events[0]["key"] == "cell_1"
    assert cell_events[1]["key"] == "cell_2"

    exp.finish()
