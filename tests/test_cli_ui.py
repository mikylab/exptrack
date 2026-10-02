"""The `exptrack ui` subcommand surface."""
from __future__ import annotations

import json

from conftest import capture

from exptrack.cli import admin_cmds
from exptrack.cli.main import _build_parser


def test_bare_ui_still_parses_as_foreground():
    """`exptrack ui --port 8000` must not become ambiguous."""
    args = _build_parser().parse_args(["ui", "--port", "8000"])
    assert args._subcmd == "ui"
    assert getattr(args, "ui_sub", None) is None
    assert args.port == 8000


def test_ui_start_parses():
    args = _build_parser().parse_args(["ui", "start", "--port", "9000"])
    assert args.ui_sub == "start"
    assert args.port == 9000


def test_ui_stop_force_parses():
    args = _build_parser().parse_args(["ui", "stop", "--force"])
    assert args.ui_sub == "stop"
    assert args.force is True


def test_ui_status_json_parses():
    args = _build_parser().parse_args(["ui", "status", "--json"])
    assert args.ui_sub == "status"
    assert args.json is True


def test_status_reports_not_running(tmp_project):
    args = _build_parser().parse_args(["ui", "status"])
    out, err = capture(admin_cmds.cmd_ui, args)
    assert "not running" in (out + err).lower()


def test_status_json_is_parseable_when_not_running(tmp_project):
    args = _build_parser().parse_args(["ui", "status", "--json"])
    out, _err = capture(admin_cmds.cmd_ui, args)
    assert json.loads(out)["running"] is False


def test_status_json_carries_the_url_and_version(tmp_project, monkeypatch):
    from exptrack.dashboard import daemon
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: True)
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")

    args = _build_parser().parse_args(["ui", "status", "--json"])
    out, _err = capture(admin_cmds.cmd_ui, args)
    payload = json.loads(out)
    assert payload["running"] is True
    assert payload["port"] == 7331
    assert payload["version"] == "1.9.0"
    assert payload["url"].startswith("http://127.0.0.1:7331/")


def test_logs_prints_the_tail(tmp_project):
    from exptrack.dashboard import daemon
    daemon.log_file_path().write_text("alpha\nbeta\ngamma\n")
    args = _build_parser().parse_args(["ui", "logs", "-n", "2"])
    out, _err = capture(admin_cmds.cmd_ui, args)
    assert "gamma" in out
    assert "alpha" not in out


def test_ui_stop_alias_still_works():
    args = _build_parser().parse_args(["ui-stop", "--port", "7331"])
    assert args._subcmd == "ui-stop"


def test_status_reports_running_for_a_real_detached_process(tmp_project):
    """End-to-end regression for the Windows pid_alive bug.

    A mocked `pid_alive` (as in test_status_json_carries_the_url_and_version)
    can't catch a bug *in* pid_alive itself. This spawns a genuinely detached
    child the same way spawn_detached does, binds a real listening socket so
    port_listening also has something true to find, and drives `ui status`
    through the CLI dispatcher with no mocking of either helper — the same
    path that reported "not running" for a live dashboard on Windows before
    pid_alive was fixed to use OpenProcess instead of os.kill(pid, 0).
    """
    import socket
    import subprocess
    import sys as _sys

    from exptrack.dashboard import daemon

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    kwargs = {}
    if _sys.platform == "win32":
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([_sys.executable, "-c", "import time; time.sleep(10)"],
                            **kwargs)
    try:
        daemon.write_state(pid=proc.pid, host="127.0.0.1", port=port,
                           version="1.9.0")
        args = _build_parser().parse_args(["ui", "status", "--json"])
        out, _err = capture(admin_cmds.cmd_ui, args)
        assert json.loads(out)["running"] is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        srv.close()
