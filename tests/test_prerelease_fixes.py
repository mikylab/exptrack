"""Regression tests for the pre-1.0 release review fixes.

Each test pins one verified bug: the exact scenario that misbehaved, asserted
on the behavior a user sees rather than the implementation detail that caused
it. See CHANGELOG 1.0.0.
"""
from __future__ import annotations

import pytest


def _insert_exp(conn, exp_id, name="n", **cols):
    """Minimal experiments row, plus any extra columns the test cares about."""
    extra = "".join(f", {k}" for k in cols)
    marks = "".join(", ?" for _ in cols)
    conn.execute(
        f"INSERT INTO experiments (id, project, name, status, created_at, "
        f"updated_at{extra}) VALUES (?,'p',?,'done','t','t'{marks})",
        (exp_id, name, *cols.values()),
    )
    conn.commit()


# ── Shared diff bytes: deduped git diffs were sized at 0 ─────────────────────

def test_shared_diff_bytes_sizes_deduped_diffs(tmp_project, db_conn):
    """`_shared_diff_bytes` selected a column named `hash` from git_diffs
    (whose column is `diff_hash`); the error was swallowed, so every
    `[ref:sha256:…]` diff — the normal case for all new runs — was sized at 0
    and the storage report silently omitted diff bytes."""
    from exptrack.core.db import store_git_diff
    from exptrack.core.storage import _shared_diff_bytes

    body = "diff --git a/x b/x\n" + "x" * 4000
    marker = store_git_diff(db_conn, body)
    _insert_exp(db_conn, "e1", git_diff=marker)

    shares = _shared_diff_bytes(db_conn)
    assert marker in shares
    assert shares[marker] >= len(body)


def test_experiment_storage_counts_deduped_diff_bytes(tmp_project, db_conn):
    """The user-facing symptom: 'Largest runs' mis-ranked a run whose bulk is
    a big working-tree diff, because its diff share was 0."""
    from exptrack.core.db import store_git_diff
    from exptrack.core.storage import experiment_storage

    marker = store_git_diff(db_conn, "diff --git a/x b/x\n" + "y" * 50_000)
    _insert_exp(db_conn, "bigdiff", git_diff=marker)

    rows = experiment_storage(db_conn, limit=5)
    row = next(r for r in rows if r["id"] == "bigdiff")
    assert row["diff_bytes"] >= 50_000


# ── Context manager: explicit finish() inside the with-block ─────────────────

def test_explicit_finish_inside_with_block_does_not_double_finish(tmp_project):
    """__exit__ called finish() unconditionally, and finish() raises on a
    second call — so a clean block that finished itself crashed at exit."""
    from exptrack.core.experiment import Experiment

    with Experiment(name="explicit") as exp:
        exp.log_metric("loss", 1.0, step=0)
        exp.finish()
    assert exp.status == "done"


def test_exception_after_explicit_finish_propagates_the_users_error(tmp_project):
    """In the exception branch, fail() on an already-finished run raised
    RuntimeError — which replaced the user's real exception."""
    from exptrack.core.experiment import Experiment

    with pytest.raises(ValueError, match="the real error"), \
            Experiment(name="finished-then-raised") as exp:
        exp.finish()
        raise ValueError("the real error")


# The two commit-window regressions from this review live in
# tests/test_metric_commit_coalescing.py, beside that module's `_set_interval` /
# `_rows` helpers and the rest of the coalescing contract.


# ── Dashboard prune: the delete is the previewed set ─────────────────────────

def test_dashboard_prune_deletes_exactly_the_previewed_set(tmp_project):
    """The confirmed POST re-ran target selection from scratch, so metrics
    logged while the confirm dialog was open were deleted beyond what the
    dialog showed. The dry-run now hands back a token for its doomed set and
    the delete uses exactly that set."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.dashboard.routes.write_routes.admin import api_prune_metrics

    exp = Experiment(name="prunable")
    for i in range(50):
        exp.log_metric("loss", float(i), step=i)
    exp.finish()   # closes the thread's cached connection — re-fetch below

    pre = api_prune_metrics(get_db(), {"max_points": 10, "dry_run": True})
    assert pre["ok"] and pre["points"] > 0
    assert pre.get("preview_token")

    # Points logged after the preview (the dialog is open) must survive a
    # token-confirmed prune untouched.
    late = Experiment(name="late")
    for i in range(50):
        late.log_metric("acc", float(i), step=i)
    late.finish()

    conn = get_db()
    res = api_prune_metrics(
        conn, {"max_points": 10, "preview_token": pre["preview_token"]})
    assert res["ok"]
    assert res["deleted"] == pre["points"]

    n_late = conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE exp_id=?", (late.id,)
    ).fetchone()[0]
    assert n_late == 50, "a token-confirmed prune touched points logged after the preview"


def test_dashboard_prune_refuses_an_expired_preview_token(tmp_project):
    """A confirm built from a preview the server no longer holds must refuse,
    not silently delete a freshly-selected (different) set."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.dashboard.routes.write_routes.admin import api_prune_metrics

    exp = Experiment(name="prunable2")
    for i in range(30):
        exp.log_metric("loss", float(i), step=i)
    exp.finish()

    conn = get_db()
    res = api_prune_metrics(
        conn, {"max_points": 5, "preview_token": "not-a-real-token"})
    assert "error" in res
    n = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    assert n == 30, "an expired-token prune must not delete anything"


# ── Query-param ints are clamped to SQLite's integer range ───────────────────

def test_huge_offset_does_not_500(tmp_project, db_conn):
    """?offset= beyond 64 bits raised OverflowError out of the parameter
    binding — a 500 for a malformed but harmless request."""
    from exptrack.dashboard.routes.read_routes import api_experiments

    result = api_experiments(db_conn, {"offset": "99999999999999999999"})
    assert result == []


# ── Delete preview sizes every owned output dir, not just the first ──────────

def test_delete_preview_sizes_all_owned_output_dirs(tmp_project, db_conn):
    """The preview `break`-ed after the first existing candidate while the
    delete trashes all of them — an under-stated confirm whenever the recorded
    output_dir and the name-derived outputs/<name> diverged."""
    from exptrack.core.db import get_delete_preview, output_dirs_owned_by

    recorded = tmp_project / "old_outputs" / "runA"
    derived = tmp_project / "outputs" / "runA"
    recorded.mkdir(parents=True)
    derived.mkdir(parents=True)
    (recorded / "ckpt.bin").write_bytes(b"a" * 1000)
    (derived / "plot.png").write_bytes(b"b" * 2000)

    _insert_exp(db_conn, "runa", name="runA", output_dir=str(recorded))

    owned = output_dirs_owned_by(db_conn, "runa", "runA", str(recorded))
    assert len(owned) == 2, "test setup: both candidates must be owned"

    preview = get_delete_preview(db_conn, "runa")
    assert preview["output_dir_files"] == 2
    assert preview["output_dir_bytes"] == 3000
