"""Integration tests for failure capture in `python -m exptrack <script>`.

These run the wrapper in a subprocess (it calls sys.exit) and assert that a
crashing script's traceback (file + line) is surfaced in three places:
  - the terminal (the child's stderr),
  - the run's stderr.log on disk,
  - the captured `_error_traceback` param in the DB.

Covers both the plain-exception path and the common SystemExit path where a
script catches an error and calls sys.exit(1) (the cause is chained on
SystemExit.__context__ and must not be swallowed behind "SystemExit(code)").
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


def _make_project(root: Path):
    (root / ".exptrack").mkdir()
    (root / ".exptrack" / "config.json").write_text(json.dumps({
        "db": ".exptrack/experiments.db",
        "outputs_dir": "outputs",
    }))


def _run(root: Path, script_name: str):
    return subprocess.run(
        [sys.executable, "-m", "exptrack", script_name],
        cwd=str(root), capture_output=True, text=True,
    )


def _latest_params(root: Path):
    db = root / ".exptrack" / "experiments.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        exp = conn.execute(
            "SELECT id, status FROM experiments ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        rows = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?", (exp["id"],)
        ).fetchall()
        return exp, {r["key"]: json.loads(r["value"]) for r in rows}
    finally:
        conn.close()


def _stderr_log(root: Path) -> str:
    logs = sorted((root / "outputs").glob("*/stderr.log"),
                  key=lambda p: p.stat().st_mtime)
    return logs[-1].read_text() if logs else ""


def test_uncaught_exception_traceback_captured(tmp_path):
    _make_project(tmp_path)
    (tmp_path / "boom.py").write_text(
        "def crash():\n"
        "    x = [1, 2, 3]\n"
        "    return x[99]\n"
        "crash()\n"
    )
    r = _run(tmp_path, "boom.py")
    assert r.returncode == 1
    # Terminal: the traceback with the offending line is printed.
    assert "IndexError" in r.stderr
    assert "x[99]" in r.stderr
    # stderr.log on disk has it too (was blank before the fix).
    assert "IndexError" in _stderr_log(tmp_path)
    # DB: full traceback captured, not just the message.
    exp, params = _latest_params(tmp_path)
    assert exp["status"] == "failed"
    assert "IndexError" in params["_error_traceback"]
    assert "boom.py" in params["_error_traceback"]


def test_sysexit_chained_cause_not_swallowed(tmp_path):
    _make_project(tmp_path)
    # The common shape: catch an error, then sys.exit(1).
    (tmp_path / "se.py").write_text(
        "import sys\n"
        "def train():\n"
        "    raise ValueError('bad config: lr must be > 0')\n"
        "try:\n"
        "    train()\n"
        "except Exception:\n"
        "    sys.exit(1)\n"
    )
    r = _run(tmp_path, "se.py")
    assert r.returncode == 1
    # The real cause — not just SystemExit(1) — reaches the terminal and log.
    assert "ValueError: bad config" in r.stderr
    assert "ValueError: bad config" in _stderr_log(tmp_path)
    exp, params = _latest_params(tmp_path)
    assert exp["status"] == "failed"
    assert params["error"] == "SystemExit(1)"
    assert "ValueError: bad config" in params["_error_traceback"]


def test_bare_sysexit_no_spurious_traceback(tmp_path):
    _make_project(tmp_path)
    # A deliberate non-zero exit with no underlying error: record the code,
    # but don't invent a traceback.
    (tmp_path / "bare.py").write_text("import sys\nsys.exit(3)\n")
    r = _run(tmp_path, "bare.py")
    assert r.returncode == 3
    exp, params = _latest_params(tmp_path)
    assert exp["status"] == "failed"
    assert params["error"] == "SystemExit(3)"
    assert "_error_traceback" not in params
