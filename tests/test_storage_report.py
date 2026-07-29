"""`exptrack storage` — the stats it gathers and the report it prints.

cmd_storage was a single 212-line function with 48 branches and no test
coverage. These tests split along the same seam the refactor does: the
gather half (collect_storage_stats, pure data) is asserted on directly, and
the render half is pinned by a golden-output test so the report's wording and
layout cannot drift unnoticed.

The golden test was written against the pre-refactor implementation, so it
doubles as proof the split changed nothing a user sees.
"""
from __future__ import annotations

import contextlib
import io
import re
from types import SimpleNamespace

import pytest

from exptrack.cli import admin_cmds
from exptrack.core import Experiment, get_db


def _run_storage(**kwargs):
    """Run cmd_storage and return its stdout with ANSI codes stripped."""
    args = SimpleNamespace(**{"checkpoint": False, **kwargs})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        admin_cmds.cmd_storage(args)
    return re.sub(r"\033\[[0-9;]*m", "", buf.getvalue())


@pytest.fixture
def project_with_data(tmp_project):
    """A project with one finished run, some metrics, and an output file."""
    exp = Experiment(name="storage-test", params={"lr": 0.01})
    exp.log_metric("acc", 0.9, step=1)
    exp.log_metric("acc", 0.95, step=2)
    exp.finish()
    outputs = tmp_project / "outputs"
    outputs.mkdir(exist_ok=True)
    (outputs / "model.pt").write_bytes(b"x" * 2048)
    return tmp_project


# ── the gather half ─────────────────────────────────────────────────────────

def test_collect_counts_rows(project_with_data):
    s = admin_cmds.collect_storage_stats(get_db())
    assert s["exp_count"] == 1
    assert s["param_count"] >= 1
    assert s["metric_count"] == 2
    assert s["db_size"] > 0


def test_collect_measures_outputs_dir(project_with_data):
    s = admin_cmds.collect_storage_stats(get_db())
    assert s["outputs_count"] == 1
    assert s["outputs_size"] == 2048


def test_collect_on_empty_project(tmp_project):
    """Every counter must be present and zero — the report indexes them all."""
    s = admin_cmds.collect_storage_stats(get_db())
    for key in ("exp_count", "param_count", "metric_count", "artifact_count",
                "timeline_count", "outputs_size", "outputs_count",
                "git_diff_inline", "dedup_count", "dedup_size", "ref_count",
                "timeline_size", "tl_diff_total", "cl_count", "cl_size",
                "cl_compacted", "sess_count", "snode_count", "hist_size"):
        assert s[key] == 0, f"{key} should be 0 on an empty project, got {s[key]!r}"


class _FlakyConn:
    """Wraps a real connection, failing any query mentioning `bad_table`.

    Stands in for an older DB that predates a table, which is the case the
    per-area try/except in the gather helpers exists for.
    """

    def __init__(self, conn, bad_table):
        self._conn, self._bad = conn, bad_table

    def execute(self, sql, *a, **k):
        if self._bad in sql:
            raise RuntimeError(f"no such table: {self._bad}")
        return self._conn.execute(sql, *a, **k)


def test_collect_survives_a_missing_table(project_with_data):
    """Stat gathering is best-effort — a broken query must not kill the report."""
    s = admin_cmds.collect_storage_stats(_FlakyConn(get_db(), "cell_lineage"))
    assert s["cl_count"] == 0
    assert s["cl_size"] == 0
    assert s["exp_count"] == 1  # every other area still gathered


def test_report_renders_with_a_missing_table(project_with_data, monkeypatch):
    """And the report itself still prints rather than raising."""
    monkeypatch.setattr(admin_cmds, "get_db",
                        lambda: _FlakyConn(get_db(), "session_nodes"))
    out = _run_storage()
    assert "Storage Report" in out
    assert "Database Health" in out


# ── the render half (golden output) ─────────────────────────────────────────

def test_report_sections_and_layout(project_with_data):
    out = _run_storage()
    for heading in ("Storage Report", "Database Breakdown",
                    "Storage Hotspots", "Database Health"):
        assert heading in out, f"missing section: {heading}"
    # section order matters — the report reads top-down
    assert (out.index("Storage Report") < out.index("Database Breakdown")
            < out.index("Storage Hotspots") < out.index("Database Health"))


def test_report_row_labels(project_with_data):
    out = _run_storage()
    for label in ("Database file:", "Outputs directory:", "Total:",
                  "Experiments:", "Params:", "Metrics:", "Artifacts:",
                  "Timeline:", "git_diff total:", "cell_lineage.source:",
                  "timeline.source_diff:", "notebook_history/:",
                  "Journal mode:", "WAL file:"):
        assert label in out, f"missing row: {label}"


def test_report_shows_counts(project_with_data):
    out = _run_storage()
    assert re.search(r"Experiments:\s+1 rows", out)
    assert re.search(r"Metrics:\s+2 rows", out)
    assert "(1 files)" in out


def test_checkpoint_flag_short_circuits(project_with_data):
    out = _run_storage(checkpoint=True)
    assert "WAL checkpoint complete." in out
    assert "Storage Report" not in out  # nothing else runs


def _strand(conn, where="1=1"):
    """Delete experiment rows only, as an older version's delete did.

    FKs are ON, so child rows pin their experiment; dropping the constraint
    produces exactly the state this report exists to describe — a legacy or
    hand-edited database carrying rows that belong to nothing.
    """
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(f"DELETE FROM experiments WHERE {where}")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")


def test_orphan_tip_when_rows_outlive_experiments(project_with_data):
    """The health section flags rows left behind with no experiment."""
    conn = get_db()
    _strand(conn)
    out = _run_storage()
    assert "orphaned row(s)" in out
    assert "metrics" in out
    assert "exptrack clean --orphans" in out


def test_orphan_tip_fires_while_other_experiments_remain(project_with_data):
    """The old check only fired on an empty database — this is the regression.

    A project with live runs *and* stranded rows reported perfect health, so
    the rows sat there invisibly: nothing joins to a missing experiment, but
    they still occupy the file.
    """
    conn = get_db()
    conn.execute(
        "INSERT INTO experiments (id, name, status, created_at, updated_at) "
        "VALUES ('live1', 'still here', 'done', datetime('now'), datetime('now'))")
    conn.commit()
    _strand(conn, "id != 'live1'")
    assert conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 1

    assert "orphaned row(s)" in _run_storage()


def test_no_orphan_tip_on_a_healthy_project(project_with_data):
    assert "orphaned row(s)" not in _run_storage()


def test_stale_running_tip(project_with_data):
    conn = get_db()
    conn.execute(
        "INSERT INTO experiments (id, name, status, created_at, updated_at) "
        "VALUES ('stale1', 'old', 'running', datetime('now', '-48 hours'), "
        "        datetime('now', '-48 hours'))"
    )
    conn.commit()
    out = _run_storage()
    assert "running for >24h" in out


def test_empty_project_still_renders(tmp_project):
    """No runs, no outputs dir — must not raise or divide by zero."""
    out = _run_storage()
    assert "Storage Report" in out
    assert "Database Health" in out


# ── the shared byte formatter ───────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (0, "0 B"),
    (512, "512 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1024 ** 2, "1.0 MB"),
    (1024 ** 3, "1.00 GB"),
    (5 * 1024 ** 3, "5.00 GB"),
])
def test_fmt_bytes(value, expected):
    from exptrack.cli.formatting import fmt_bytes
    assert fmt_bytes(value) == expected


def test_fmt_bytes_is_shared_not_duplicated():
    """admin_cmds, mutate_cmds and compact.py used to carry divergent copies.

    Asserts no module defines its own byte formatter, rather than that a
    particular alias exists — an alias would satisfy the latter while the
    duplication it was meant to rule out came back.
    """
    import inspect

    from exptrack.cli import mutate_cmds
    from exptrack.dashboard.routes.write_routes import compact

    for mod in (admin_cmds, mutate_cmds, compact):
        src = inspect.getsource(mod)
        assert "def fmt_bytes" not in src, f"{mod.__name__} redefines fmt_bytes"
        assert "def _fmt" not in src, f"{mod.__name__} has its own byte formatter"
