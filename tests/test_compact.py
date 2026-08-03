"""Tests for exptrack compact — stripping git diffs while keeping results."""
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def _reset_config():
    """Reset cached config so each test starts fresh."""
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None


def _capture_stdout(func, *args):
    """Capture stdout from a function call, return the output string."""
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = buf = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        func(*args)
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
    return buf.getvalue()


def _setup_project():
    """Init a fresh project and return the db connection."""
    _reset_config()
    from exptrack import config as cfg
    cfg.init("test")
    from exptrack.core import get_db
    return get_db()


def _insert_experiment(conn, exp_id, name="test_exp", status="done",
                       git_diff="diff --git a/foo.py b/foo.py\n+hello\n-world",
                       git_commit="abc1234", git_branch="main"):
    """Insert a fake experiment directly into the DB."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO experiments (id, name, status, created_at, updated_at, "
        "git_diff, git_commit, git_branch) VALUES (?,?,?,?,?,?,?,?)",
        (exp_id, name, status, now, now, git_diff, git_commit, git_branch),
    )
    conn.commit()


def test_compact_strips_diff():
    """compact should replace git_diff with a summary marker."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "exp001", name="train_run")

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=[], all=False, older_than=None, dry_run=False, export=None)
        output = _capture_stdout(cmd_compact, args)

        assert "Compacted 1" in output

        row = conn.execute("SELECT git_diff FROM experiments WHERE id='exp001'").fetchone()
        assert row["git_diff"].startswith("[compacted")
        assert "abc1234" in row["git_diff"]
        print("  [PASS] test_compact_strips_diff")


def test_compact_dry_run():
    """--dry-run should not modify the database."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        original_diff = "diff --git a/foo.py b/foo.py\n+hello"
        _insert_experiment(conn, "exp002", git_diff=original_diff)

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=[], all=False, older_than=None, dry_run=True, export=None)
        output = _capture_stdout(cmd_compact, args)

        assert "Would compact" in output
        row = conn.execute("SELECT git_diff FROM experiments WHERE id='exp002'").fetchone()
        assert row["git_diff"] == original_diff, "dry-run should not change the diff"
        print("  [PASS] test_compact_dry_run")


def test_compact_skips_already_compacted():
    """compact should not re-compact already-compacted experiments."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "exp003", git_diff="[compacted — already done]")

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=["exp003"], all=False, older_than=None, dry_run=False, export=None)
        output = _capture_stdout(cmd_compact, args)
        assert "Nothing to compact" in output
        print("  [PASS] test_compact_skips_already_compacted")


def test_compact_skips_running_by_default():
    """compact should only target 'done' experiments by default."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "exp004", status="running")

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=[], all=False, older_than=None, dry_run=False, export=None)
        output = _capture_stdout(cmd_compact, args)
        assert "No matching experiments" in output or "Nothing to compact" in output

        # Verify diff is untouched
        row = conn.execute("SELECT git_diff FROM experiments WHERE id='exp004'").fetchone()
        assert not row["git_diff"].startswith("[compacted")
        print("  [PASS] test_compact_skips_running_by_default")


def test_compact_all_flag():
    """--all should compact experiments regardless of status."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "exp005", status="running")
        _insert_experiment(conn, "exp006", status="failed")

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=[], all=True, older_than=None, dry_run=False, export=None)
        output = _capture_stdout(cmd_compact, args)
        assert "Compacted 2" in output

        for eid in ["exp005", "exp006"]:
            row = conn.execute("SELECT git_diff FROM experiments WHERE id=?", (eid,)).fetchone()
            assert row["git_diff"].startswith("[compacted")
        print("  [PASS] test_compact_all_flag")


def test_compact_by_id_prefix():
    """compact with specific IDs should only target those experiments."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "aaa111", status="done")
        _insert_experiment(conn, "bbb222", status="done")

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=["aaa"], all=False, older_than=None, dry_run=False, export=None)
        output = _capture_stdout(cmd_compact, args)
        assert "Compacted 1" in output

        row_a = conn.execute("SELECT git_diff FROM experiments WHERE id='aaa111'").fetchone()
        row_b = conn.execute("SELECT git_diff FROM experiments WHERE id='bbb222'").fetchone()
        assert row_a["git_diff"].startswith("[compacted")
        assert not row_b["git_diff"].startswith("[compacted")
        print("  [PASS] test_compact_by_id_prefix")


def test_compact_export():
    """--export should save diffs as markdown files before stripping."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        diff_text = "diff --git a/model.py b/model.py\n+new_code\n-old_code"
        _insert_experiment(conn, "exp007", name="lr_sweep", git_diff=diff_text)

        export_dir = os.path.join(tmp, "exported_diffs")
        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=[], all=False, older_than=None, dry_run=False, export=export_dir)
        output = _capture_stdout(cmd_compact, args)

        assert "Exported" in output
        assert "Compacted 1" in output

        # Check the exported file exists and has correct content
        exported = list(Path(export_dir).glob("*.md"))
        assert len(exported) == 1, f"Expected 1 exported file, got {len(exported)}"

        content = exported[0].read_text()
        assert "# Diff: lr_sweep" in content
        assert "exp007" in content
        assert "+new_code" in content
        assert "```diff" in content

        # DB should be compacted
        row = conn.execute("SELECT git_diff FROM experiments WHERE id='exp007'").fetchone()
        assert row["git_diff"].startswith("[compacted")
        print("  [PASS] test_compact_export")


def test_compact_preserves_other_data():
    """compact should only touch git_diff, not params/metrics/other fields."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "exp008", name="important_run", git_commit="def5678")
        conn.execute("INSERT INTO params (exp_id, key, value) VALUES (?,?,?)",
                     ("exp008", "lr", '"0.01"'))
        conn.execute("INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)",
                     ("exp008", "loss", 0.5, 1, "2025-01-01"))
        conn.commit()

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=[], all=False, older_than=None, dry_run=False, export=None)
        _capture_stdout(cmd_compact, args)

        # Verify other data untouched
        exp = conn.execute("SELECT name, git_commit, status FROM experiments WHERE id='exp008'").fetchone()
        assert exp["name"] == "important_run"
        assert exp["git_commit"] == "def5678"
        assert exp["status"] == "done"

        params = conn.execute("SELECT * FROM params WHERE exp_id='exp008'").fetchall()
        assert len(params) == 1
        assert params[0]["key"] == "lr"

        metrics = conn.execute("SELECT * FROM metrics WHERE exp_id='exp008'").fetchall()
        assert len(metrics) == 1
        assert metrics[0]["value"] == 0.5
        print("  [PASS] test_compact_preserves_other_data")


def test_compact_file_summary_in_marker():
    """The compact marker should include file names from the diff."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        diff_text = (
            "diff --git a/model.py b/model.py\n"
            "+code\n"
            "diff --git a/train.py b/train.py\n"
            "-old\n"
        )
        _insert_experiment(conn, "exp009", git_diff=diff_text)

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=[], all=False, older_than=None, dry_run=False, export=None)
        _capture_stdout(cmd_compact, args)

        row = conn.execute("SELECT git_diff FROM experiments WHERE id='exp009'").fetchone()
        assert "2 file(s)" in row["git_diff"]
        assert "model.py" in row["git_diff"]
        assert "train.py" in row["git_diff"]
        print("  [PASS] test_compact_file_summary_in_marker")


def test_compact_no_diff():
    """Experiments with no git_diff should be skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "exp010", git_diff=None)
        _insert_experiment(conn, "exp011", git_diff="")

        from exptrack.cli.admin_cmds import cmd_compact
        args = SimpleNamespace(ids=["exp01"], all=False, older_than=None, dry_run=False, export=None)
        output = _capture_stdout(cmd_compact, args)
        assert "Nothing to compact" in output
        print("  [PASS] test_compact_no_diff")


def test_cli_diff_shows_compacted_message():
    """cmd_diff should show a clear message for compacted experiments."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "exp012",
                           git_diff="[compacted — 5.0 KB stripped — see git commit abc1234]")

        from exptrack.cli.inspect_cmds import cmd_diff
        args = SimpleNamespace(id="exp012")
        output = _capture_stdout(cmd_diff, args)
        assert "compacted" in output
        assert "git diff" in output  # recovery hint
        print("  [PASS] test_cli_diff_shows_compacted_message")


def test_api_compact():
    """The dashboard API compact endpoint should work like the CLI."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        diff_text = "diff --git a/foo.py b/foo.py\n+hello\n-world"
        _insert_experiment(conn, "api001", name="api_test", git_diff=diff_text)

        from exptrack.dashboard.routes.write_routes import api_compact
        result = api_compact(conn, {"ids": ["api001"]})
        assert result["ok"] is True
        assert result["compacted"] == 1
        assert result["freed"] > 0

        row = conn.execute("SELECT git_diff FROM experiments WHERE id='api001'").fetchone()
        assert row["git_diff"].startswith("[compacted")
        print("  [PASS] test_api_compact")


def test_api_compact_skips_already_compacted():
    """API compact should skip already-compacted experiments."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "api002", git_diff="[compacted — already done]")

        from exptrack.dashboard.routes.write_routes import api_compact
        result = api_compact(conn, {"ids": ["api002"]})
        assert result["ok"] is True
        assert result["compacted"] == 0
        print("  [PASS] test_api_compact_skips_already_compacted")


def test_api_export_diff():
    """The export-diff endpoint should return markdown with the diff."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        diff_text = "diff --git a/model.py b/model.py\n+new_code"
        _insert_experiment(conn, "api003", name="export_test", git_diff=diff_text,
                           git_branch="main", git_commit="abc1234")

        from exptrack.dashboard.routes.write_routes import api_export_diff
        result = api_export_diff(conn, "api003")
        assert result["ok"] is True
        assert "```diff" in result["markdown"]
        assert "+new_code" in result["markdown"]
        assert "export_test" in result["markdown"]
        assert result["filename"].endswith(".md")
        print("  [PASS] test_api_export_diff")


def test_api_export_diff_compacted():
    """Export-diff should error for already-compacted experiments."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "api004", git_diff="[compacted — stripped]")

        from exptrack.dashboard.routes.write_routes import api_export_diff
        result = api_export_diff(conn, "api004")
        assert "error" in result
        assert result.get("compacted") is True
        print("  [PASS] test_api_export_diff_compacted")


def test_stats_include_diff_info():
    """Stats should include diff storage info and config limit."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        conn = _setup_project()
        _insert_experiment(conn, "stat001", git_diff="x" * 1000)
        _insert_experiment(conn, "stat002", git_diff="[compacted — should not count]")

        from exptrack.core.queries import get_stats
        stats = get_stats(conn)
        assert "diff_total_bytes" in stats
        assert stats["diff_total_bytes"] == 1000  # only the non-compacted one
        assert stats["diff_count"] == 1
        assert "max_diff_kb" in stats
        print("  [PASS] test_stats_include_diff_info")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


# ── Deduplicated diff bodies are actually reclaimed ─────────────────────────
#
# `store_git_diff` content-addresses every diff into `git_diffs` and leaves a
# `[ref:sha256:…]` pointer on the run. Compaction replaces that pointer — which
# by itself frees nothing, because the body survives until nothing references
# it. On a project whose diffs were 90% of the database, `compact` reclaimed 0
# bytes while reporting success, and `clean`'s default path never swept them.

def _compact_args(**kw):
    base = dict(ids=[], all=False, older_than=None, dry_run=False, export=None,
                cells=False, timeline=False, snapshots=False, deep=False,
                dedup=False, code_changes=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _diff_blob_count(conn):
    return conn.execute("SELECT COUNT(*) FROM git_diffs").fetchone()[0]


def _run_with_stored_diff(conn, exp_id, body):
    from exptrack.core.db import store_git_diff
    ref = store_git_diff(conn, body)
    _insert_experiment(conn, exp_id, git_diff=ref)
    conn.commit()
    return ref


def test_compact_reclaims_an_unreferenced_diff_body():
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        conn = _setup_project()
        body = "diff --git a/a.py b/a.py\n" + "+x = 1\n" * 400
        _run_with_stored_diff(conn, "solo", body)
        assert _diff_blob_count(conn) == 1

        from exptrack.cli.admin_cmds import cmd_compact
        _capture_stdout(cmd_compact, _compact_args())

        # Nothing points at the body any more, so it must be gone — not merely
        # unreferenced and still occupying the file.
        assert _diff_blob_count(conn) == 0


def test_compact_keeps_a_body_another_run_still_shares():
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        conn = _setup_project()
        body = "diff --git a/a.py b/a.py\n" + "+x = 1\n" * 400
        ref = _run_with_stored_diff(conn, "first", body)
        _insert_experiment(conn, "second", git_diff=ref)   # same shared body
        conn.commit()

        from exptrack.cli.admin_cmds import cmd_compact
        _capture_stdout(cmd_compact, _compact_args(ids=["first"]))

        # `second` still resolves its diff, so the body must survive.
        assert _diff_blob_count(conn) == 1
        row = conn.execute(
            "SELECT git_diff FROM experiments WHERE id='second'").fetchone()
        assert row[0].startswith("[ref:sha256:")


def test_dry_run_estimates_the_body_not_the_pointer():
    """`diff_len` is the length of the column, which for a deduplicated diff is
    a ~45-byte pointer — so the dry-run promised ~1 KB where 1.7 MB would go."""
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        conn = _setup_project()
        body = "diff --git a/a.py b/a.py\n" + "+x = 1\n" * 2000
        _run_with_stored_diff(conn, "big", body)

        from exptrack.cli.admin_cmds import cmd_compact
        out = _capture_stdout(cmd_compact, _compact_args(dry_run=True))
        assert "KB" in out or "MB" in out, out
        assert " B," not in out, f"reported the pointer, not the body: {out}"


def test_dry_run_reports_nothing_reclaimable_for_a_shared_body():
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        conn = _setup_project()
        body = "diff --git a/a.py b/a.py\n" + "+x = 1\n" * 2000
        ref = _run_with_stored_diff(conn, "first", body)
        _insert_experiment(conn, "second", git_diff=ref)
        conn.commit()

        from exptrack.cli.admin_cmds import cmd_compact
        out = _capture_stdout(cmd_compact, _compact_args(ids=["first"], dry_run=True))
        assert "~0 B" in out, out


def test_dashboard_freed_counts_the_body_once_not_once_per_run():
    """Shared bodies used to be counted per run: 30 runs sharing one 34 KB body
    reported ~1 MB freed when 34 KB left the database."""
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        conn = _setup_project()
        body = "diff --git a/a.py b/a.py\n" + "+x = 1\n" * 2000
        ref = _run_with_stored_diff(conn, "run0", body)
        for i in range(1, 8):
            _insert_experiment(conn, f"run{i}", git_diff=ref)
        conn.commit()
        ids = [f"run{i}" for i in range(8)]

        from exptrack.dashboard.routes.write_routes import api_compact
        res = api_compact(conn, {"ids": ids, "mode": "diff"})

        # One body left the database, so that is what may be reported.
        assert _diff_blob_count(conn) == 0
        assert res["freed"] == len(body), (res["freed"], len(body))


def test_dashboard_dry_run_and_write_agree_on_freed_bytes():
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        conn = _setup_project()
        body = "diff --git a/a.py b/a.py\n" + "+x = 1\n" * 2000
        ref = _run_with_stored_diff(conn, "a", body)
        _insert_experiment(conn, "b", git_diff=ref)
        conn.commit()
        ids = ["a", "b"]

        from exptrack.dashboard.routes.write_routes import api_compact
        preview = api_compact(conn, {"ids": ids, "mode": "diff", "dry_run": True})
        wrote = api_compact(conn, {"ids": ids, "mode": "diff"})
        assert preview["total_bytes"] == wrote["freed"] == len(body)


def test_cli_and_dashboard_compact_report_the_same_bytes():
    """The two entry points share one implementation — they had drifted, and
    only the CLI's copy was fixed to sweep the bodies it orphaned."""
    def _freed(fn):
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            conn = _setup_project()
            body = "diff --git a/a.py b/a.py\n" + "+x = 1\n" * 900
            ref = _run_with_stored_diff(conn, "one", body)
            _insert_experiment(conn, "two", git_diff=ref)
            conn.commit()
            return fn(conn, ["one", "two"]), _diff_blob_count(conn)

    from exptrack.core.storage import compact_git_diffs
    from exptrack.dashboard.routes.write_routes import api_compact
    dash, dash_blobs = _freed(
        lambda c, ids: api_compact(c, {"ids": ids, "mode": "diff"})["freed"])
    core, core_blobs = _freed(lambda c, ids: compact_git_diffs(c, ids)["bytes"])
    assert dash == core and dash_blobs == core_blobs == 0
