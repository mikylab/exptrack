"""Tests for `exptrack run-start --resume`.

These drive through main() with a patched sys.argv (not cmd_run_start directly)
because the bug lived in the pre-argparse interception block in main.py, which
the cmd_* tests bypass. --resume was omitted from that mini-parser, so it landed
in `unknown` → stored as a junk `resume` param on a brand-new run instead of
resuming.
"""
from __future__ import annotations

import io
import sys

from conftest import exp_id_from_stdout as _exp_id


def _run_main(argv, monkeypatch):
    """Invoke exptrack main() with argv, returning captured stdout."""
    # exptrack.cli re-exports the main() function as `exptrack.cli.main`, which
    # shadows the submodule attr — import_module returns the real module.
    import importlib
    main_mod = importlib.import_module("exptrack.cli.main")

    monkeypatch.setattr(sys, "argv", ["exptrack", *argv])
    old_out = sys.stdout
    sys.stdout = out = io.StringIO()
    try:
        main_mod.main()
    finally:
        sys.stdout = old_out
    return out.getvalue()


def _params(exp_id):
    from exptrack.core.db import get_db
    return {
        r["key"]: r["value"] for r in get_db().execute(
            "SELECT key, value FROM params WHERE exp_id=?", (exp_id,)
        ).fetchall()
    }


def _fixed_script(monkeypatch, path="/tmp/fake_train.sh"):
    """Pin the detected calling script so `--resume latest` matches by script."""
    monkeypatch.setattr(
        "exptrack.cli.pipeline_cmds._detect_calling_script", lambda: path)


def test_run_start_resume_by_id(tmp_project, monkeypatch):
    _fixed_script(monkeypatch)
    first = _run_main(["run-start", "--lr", "0.01"], monkeypatch)
    eid = _exp_id(first)
    assert eid

    second = _run_main(["run-start", "--resume", eid, "--lr", "0.02"], monkeypatch)
    assert _exp_id(second) == eid          # same run resumed, not a new one

    params = _params(eid)
    assert "resume" not in params          # --resume not stored as a junk param
    assert params["lr"] == "0.02"          # value updated on resume


def test_run_start_resume_latest(tmp_project, monkeypatch):
    _fixed_script(monkeypatch)
    first = _run_main(["run-start", "--lr", "0.01"], monkeypatch)
    eid = _exp_id(first)

    second = _run_main(["run-start", "--resume", "--epochs", "5"], monkeypatch)
    assert _exp_id(second) == eid          # bare --resume resumes the latest


def test_run_start_resume_no_previous(tmp_project, monkeypatch, capsys):
    _fixed_script(monkeypatch)
    out = _run_main(["run-start", "--resume"], monkeypatch)
    assert _exp_id(out)                     # a fresh run is created
    assert "No previous experiment" in capsys.readouterr().err


def test_run_start_resume_before_params(tmp_project, monkeypatch):
    _fixed_script(monkeypatch)
    first = _run_main(["run-start", "--lr", "0.01"], monkeypatch)
    eid = _exp_id(first)

    _run_main(["run-start", "--resume", "latest", "--lr", "0.05"], monkeypatch)
    params = _params(eid)
    assert params["lr"] == "0.05"           # lr captured
    assert "resume" not in params           # resume not captured
