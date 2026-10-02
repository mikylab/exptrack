"""Dashboard process lifecycle — state file, liveness, spawn, stop.

The state file is how `ui status` and `ui stop` work without shelling out to
fuser/lsof, which is what makes them function on Windows at all. These tests
cover the pure helpers; the spawn integration test lives in Task 3.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest

from exptrack.dashboard import daemon


def test_write_state_round_trips(tmp_project):
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")
    state = daemon.read_state()
    assert state["pid"] == 4321
    assert state["host"] == "127.0.0.1"
    assert state["port"] == 7331
    assert state["version"] == "1.9.0"
    assert "started_at" in state


def test_state_file_carries_no_token(tmp_project):
    """The token lives in .exptrack/dashboard_token, not here.

    One secret, one location. An earlier design duplicated it into this file.
    """
    daemon.write_state(pid=1, host="127.0.0.1", port=7331, version="1.9.0")
    raw = daemon.state_file_path().read_text()
    assert "token" not in raw.lower()


def test_read_state_returns_none_when_absent(tmp_project):
    assert daemon.read_state() is None


def test_read_state_returns_none_on_corrupt_file(tmp_project):
    daemon.state_file_path().write_text("{not json")
    assert daemon.read_state() is None


def test_clear_state_is_idempotent(tmp_project):
    daemon.write_state(pid=1, host="127.0.0.1", port=7331, version="1.9.0")
    daemon.clear_state()
    daemon.clear_state()
    assert daemon.read_state() is None


def test_pid_alive_true_for_this_process():
    assert daemon.pid_alive(os.getpid()) is True


def test_pid_alive_false_for_absurd_pid():
    assert daemon.pid_alive(2_000_000_000) is False


def test_pid_alive_true_for_a_genuinely_detached_process():
    """Regression: on Windows, os.kill(pid, 0) is not a liveness probe.

    signal.CTRL_C_EVENT == 0, so os.kill(pid, 0) routes to
    GenerateConsoleCtrlEvent, which only reaches processes in the caller's
    own console group. Every dashboard is spawned with CREATE_NO_WINDOW |
    CREATE_NEW_PROCESS_GROUP (spawn_detached), so it never shares that
    group — a same-process or same-console-group pid (the two prior tests)
    can't catch this. This spawns a real child the same way spawn_detached
    does and checks liveness across the console boundary, then again after
    the child exits.
    """
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"],
                            **kwargs)
    try:
        assert daemon.pid_alive(proc.pid) is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    assert daemon.pid_alive(proc.pid) is False


def test_port_listening_detects_a_bound_socket():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert daemon.port_listening("127.0.0.1", port) is True
    finally:
        srv.close()
    assert daemon.port_listening("127.0.0.1", port) is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes are inert on Windows")
def test_state_file_is_private(tmp_project):
    daemon.write_state(pid=1, host="127.0.0.1", port=7331, version="1.9.0")
    assert oct(daemon.state_file_path().stat().st_mode)[-3:] == "600"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes are inert on Windows")
def test_log_file_is_private(tmp_project):
    """dashboard.log matters as much as the token file: the startup banner it
    captures embeds the token (see app.py's `[exptrack] Dashboard: ...
    ?token=...` line), so a world-readable log leaks the same secret as a
    world-readable dashboard_token."""
    import os as _os
    import signal as _signal

    pid = daemon.spawn_detached("127.0.0.1", 0)
    try:
        assert oct(daemon.log_file_path().stat().st_mode)[-3:] == "600"
    finally:
        try:
            _os.kill(pid, _signal.SIGTERM)
        except OSError:
            pass


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privilege on Windows")
def test_open_private_refuses_a_symlink(tmp_project, tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("")
    link = daemon.state_file_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    with pytest.raises(OSError):
        daemon.write_state(pid=1, host="127.0.0.1", port=7331, version="1.9.0")


def test_gitignore_covers_the_new_files(tmp_project):
    from exptrack import config as cfg
    assert ".exptrack/dashboard.json" in cfg.GITIGNORE_RULES
    assert ".exptrack/dashboard.log" in cfg.GITIGNORE_RULES


def test_start_is_idempotent_when_already_running(tmp_project, monkeypatch):
    """`exptrack tunnel` chains `ui start && ui status` on every invocation,
    so re-starting an already-running dashboard is the normal case, not an
    error."""
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: True)
    spawned = []
    monkeypatch.setattr(daemon, "spawn_detached",
                        lambda host, port: spawned.append((host, port)))
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")

    result = daemon.start(host="127.0.0.1", port=7331)

    assert result["status"] == "already-running"
    assert result["pid"] == 4321
    assert spawned == []


def test_start_refuses_a_port_held_by_something_else(tmp_project, monkeypatch):
    """No recorded dashboard, but the port is taken — that is a conflict."""
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: True)
    with pytest.raises(daemon.DaemonError) as exc:
        daemon.start(host="127.0.0.1", port=7331)
    assert "7331" in str(exc.value)


def test_start_refuses_to_orphan_a_live_dashboard_on_another_port(tmp_project, monkeypatch):
    """`ui start --port 8000` with a live dashboard already recorded on 7331
    must not silently overwrite the single-slot state file with the new
    child — that would leave the first dashboard untracked (unreachable
    through `ui stop`/`ui status`, and on Windows unreachable at all, since
    find_pids_on_port always returns []). Refusing, naming the original port,
    is the correct scope; the state file stays single-slot.
    """
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: True)
    spawned = []
    monkeypatch.setattr(daemon, "spawn_detached",
                        lambda host, port: spawned.append((host, port)))
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")

    with pytest.raises(daemon.DaemonError) as exc:
        daemon.start(host="127.0.0.1", port=8000)

    assert "7331" in str(exc.value)
    assert "4321" in str(exc.value)
    assert spawned == [], "must not have spawned a second dashboard"


def test_start_reports_the_log_when_the_child_dies(tmp_project, monkeypatch):
    """A silent background failure is worse than a loud foreground one."""
    daemon.log_file_path().write_text("Traceback...\nOSError: nope\n")
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: False)
    monkeypatch.setattr(daemon, "spawn_detached", lambda host, port: 999999)
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: False)

    with pytest.raises(daemon.DaemonError) as exc:
        daemon.start(host="127.0.0.1", port=7331, timeout=0.5)
    assert "OSError: nope" in str(exc.value)
    assert daemon.read_state() is None


def test_tail_log_returns_the_last_lines(tmp_project):
    daemon.log_file_path().write_text("\n".join(f"line{i}" for i in range(50)))
    out = daemon.tail_log(lines=3)
    assert "line49" in out
    assert "line10" not in out


def test_tail_log_on_a_missing_file_is_empty(tmp_project):
    assert daemon.tail_log() == ""


def test_bound_port_ignores_a_stale_banner_before_the_spawn_offset(tmp_project, monkeypatch):
    """A previous invocation's banner surviving in the log must not be
    mistaken for the new child's ephemeral port (Finding 1)."""
    # A stale banner from an earlier crashed/restarted invocation, already
    # in the log before this `start()` call spawns anything.
    daemon.log_file_path().write_text(
        "[exptrack] Dashboard: http://127.0.0.1:9999/?token=old\n")

    def fake_spawn(host, port):
        # The real child appends its own banner *after* daemon.start already
        # captured the pre-spawn log offset.
        with open(daemon.log_file_path(), "a") as f:
            f.write("[exptrack] Dashboard: http://127.0.0.1:54321/?token=new\n")
        return 123456

    monkeypatch.setattr(daemon, "spawn_detached", fake_spawn)
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    # Both the stale and the fresh port "happen" to be listening, so a scan
    # that isn't offset-bounded would false-positive on the stale one (it
    # sorts first in the log and `_bound_port` returns on the first match).
    monkeypatch.setattr(daemon, "port_listening",
                        lambda h, p, timeout=0.25: p in (9999, 54321))

    result = daemon.start(host="127.0.0.1", port=0, timeout=2.0)

    assert result["status"] == "started"
    assert result["port"] == 54321


def test_await_ready_signals_a_child_that_never_binds(tmp_project, monkeypatch):
    """Deadline reached, child still alive: must not orphan it (Finding 2).

    Distinct from `test_start_reports_the_log_when_the_child_dies`, which
    covers the child exiting on its own -- here it never exits and never
    binds, so `start` must kill it before giving up.
    """
    killed = []
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: False)
    monkeypatch.setattr(daemon, "spawn_detached", lambda host, port: 555555)
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    with pytest.raises(daemon.DaemonError) as exc:
        daemon.start(host="127.0.0.1", port=7331, timeout=0.3)

    assert killed == [(555555, daemon.signal.SIGTERM)]
    assert "555555" in str(exc.value)
    assert daemon.read_state() is None


def test_start_serves_over_a_real_socket(tmp_project):
    """Full integration: a genuinely detached server that actually serves.

    port=0 makes the child bind an ephemeral port and report it in its startup
    banner, so this never collides with a real dashboard or a busy CI runner.
    """
    import os
    import signal as _signal
    import urllib.request

    result = daemon.start(host="127.0.0.1", port=0)
    try:
        assert result["status"] == "started"
        assert result["pid"] and daemon.pid_alive(result["pid"])
        req = urllib.request.Request(
            result["url"].split("?")[0] + "api/stats",
            headers={"Authorization": f"Bearer {result['token']}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
    finally:
        try:
            os.kill(result["pid"], _signal.SIGTERM)
        except OSError:
            pass
        daemon.clear_state()


def test_empty_first_tool_does_not_suppress_the_second(monkeypatch):
    """Regression for the false all-clear.

    cmd_ui_stop looped over fuser then lsof, but `continue` only fired when a
    binary was *missing*. If fuser existed and returned nothing, it printed
    "No process is listening" and returned — lsof was never tried. That is a
    confident all-clear while the server is still running, and it is why the
    user had to lsof and kill by hand.
    """
    calls = []

    class _Result:
        def __init__(self, out):
            self.stdout = out

    def fake_run(argv, **kwargs):
        calls.append(argv[0])
        return _Result("" if argv[0] == "fuser" else "4821\n")

    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    pids = daemon.find_pids_on_port(7331)

    assert "fuser" in calls and "lsof" in calls, "lsof must still be tried"
    assert pids == [4821]


def test_missing_binaries_are_skipped_not_fatal(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError(argv[0])
    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    assert daemon.find_pids_on_port(7331) == []


def test_stop_reports_not_running_only_after_every_method(tmp_project, monkeypatch):
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [])
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: False)
    result = daemon.stop(port=7331)
    assert result["stopped"] is False
    assert result["pids"] == []


def test_stop_on_a_different_port_does_not_signal_the_recorded_pid(tmp_project, monkeypatch):
    """`ui stop --port 8000` with a dashboard recorded on 7331 must not
    SIGTERM the 7331 process — the state-file pid was previously taken
    unconditionally, ignoring state["port"].
    """
    signalled = []
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [])
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: False)
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: signalled.append(pid))
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")

    result = daemon.stop(port=8000)

    assert 4321 not in signalled
    assert result["stopped"] is False


def test_stop_on_a_different_port_does_not_clear_the_recorded_state(tmp_project, monkeypatch):
    """Regression: `stop()`'s "nothing found on this port" branch called
    `clear_state()` unconditionally. `ui stop --port 9999` — a port with
    nothing on it — deleted the state of an unrelated, genuinely live
    dashboard recorded on a different port (e.g. 7402), so the very next `ui
    stop`/`ui status` reported nothing running even though the dashboard was
    still up: the exact untracked-process class this subsystem exists to
    eliminate, and on Windows (no fuser/lsof) unreachable through the CLI at
    all from that point on. The live dashboard's record must survive a stop
    call aimed at a different, empty port.
    """
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [])
    # The *other* dashboard (port 7402) is alive and listening; the port this
    # stop() call targets (9999) is not.
    monkeypatch.setattr(daemon, "port_listening",
                        lambda h, p, timeout=0.25: p == 7402)
    daemon.write_state(pid=26212, host="127.0.0.1", port=7402, version="1.9.0")

    result = daemon.stop(port=9999)

    assert result["stopped"] is False
    state = daemon.read_state()
    assert state is not None, "the live dashboard's record must survive"
    assert state["pid"] == 26212
    assert state["port"] == 7402


def test_stop_on_the_matching_port_still_clears_state_on_success(tmp_project, monkeypatch):
    """Guard against over-correcting into never clearing: a state file whose
    port matches the one just stopped must still be cleared."""
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [])
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: False)
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: None)
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")

    result = daemon.stop(port=7331)

    assert result["stopped"] is True
    assert daemon.read_state() is None


def test_stop_fails_loudly_when_the_port_stays_held(tmp_project, monkeypatch):
    """Success means stopped, not signal delivered."""
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: True)
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: None)

    with pytest.raises(daemon.DaemonError) as exc:
        daemon.stop(grace=0.3)
    assert "7331" in str(exc.value)


def test_stop_names_a_process_it_cannot_signal(tmp_project, monkeypatch):
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    # Ruling A: without this, a real lsof/fuser on the developer's machine can
    # inject extra pids and make the "4821 not in ..." assertion below
    # environment-dependent.
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [])
    # The port is genuinely still held here (unlike the stale-pid case below),
    # which is what makes "could not signal it" the right answer. Patched
    # explicitly rather than relying on nothing being bound on the real
    # port — that implicit dependency is what made the original bug's fix
    # wrong in its first pass (see test_stop_succeeds_when_the_stale_pid_s_
    # port_is_already_free).
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: True)

    def refuse(pid, sig):
        raise PermissionError("not yours")
    monkeypatch.setattr(daemon.os, "kill", refuse)

    with pytest.raises(daemon.DaemonError) as exc:
        daemon.stop(grace=0.3)
    assert "4821" not in str(exc.value)
    assert "4321" in str(exc.value)


def test_stop_succeeds_when_the_stale_pid_s_port_is_already_free(tmp_project, monkeypatch):
    """A refused signal must not be misread as 'still running'.

    A stale state-file pid can be reused by an unrelated process owned by
    someone else while the real dashboard has already exited. Every
    candidate pid refuses the signal, but the port is genuinely free — the
    goal state already holds, so this must report success (with a reason
    that says so), not a failure to stop. This is the mirror image of the
    original bug: that one said "nothing running" while it was; a naive fix
    said "failed to stop" while there was nothing left to stop.
    """
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [])
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: False)

    def refuse(pid, sig):
        raise PermissionError("not yours")
    monkeypatch.setattr(daemon.os, "kill", refuse)

    result = daemon.stop(grace=0.3)
    assert result["stopped"] is True
    assert "already" in result["reason"]


def test_stop_reports_a_partial_refusal_even_on_success(tmp_project, monkeypatch):
    """A pid that could not be signalled must not vanish on a successful stop."""
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [9999])
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: False)

    def kill(pid, sig):
        if pid == 9999:
            raise PermissionError("not yours")
    monkeypatch.setattr(daemon.os, "kill", kill)

    result = daemon.stop(grace=0.3)
    assert result["stopped"] is True
    assert "9999" in result["reason"]


def test_start_then_stop_over_a_real_socket(tmp_project):
    """Full integration: a genuinely detached server, reachable and stoppable."""
    import urllib.request

    result = daemon.start(host="127.0.0.1", port=0)
    try:
        assert result["status"] == "started"
        req = urllib.request.Request(
            result["url"].split("?")[0] + "api/stats",
            headers={"Authorization": f"Bearer {result['token']}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
    finally:
        daemon.stop()
    assert daemon.read_state() is None


def test_failed_start_does_not_clear_another_dashboards_state(tmp_project,
                                                              monkeypatch):
    """A start that fails must not delete a *different* dashboard's record.

    `_await_ready` runs before `write_state`, so any record on disk at that
    moment belongs to some other dashboard. Both of its failure paths used
    to `clear_state()` unconditionally, which orphaned that other dashboard:
    it kept serving while the CLI forgot it existed. A transient
    `port_listening` miss is enough to reach here with a live record on
    disk, which is why this is a real shape and not a contrived one.
    """
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")

    # The recorded dashboard reads as not-listening for one probe (the
    # transient miss), so `running_state` and the different-port refusal in
    # `start` both fall through and we reach the spawn.
    monkeypatch.setattr(daemon, "port_listening",
                        lambda h, p, timeout=0.25: False)
    # 4321 is alive (so `running_state` does not legitimately reap it as a
    # stale record); the spawned child is not, so we take the child-exited
    # path inside `_await_ready`.
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(daemon, "spawn_detached", lambda host, port: 999999)

    with pytest.raises(daemon.DaemonError):
        daemon.start(host="127.0.0.1", port=8000, timeout=0.3)

    state = daemon.read_state()
    assert state is not None, "a failed start deleted another dashboard's record"
    assert state["pid"] == 4321
    assert state["port"] == 7331


def test_failed_start_at_the_deadline_also_leaves_state_alone(tmp_project,
                                                              monkeypatch):
    """The deadline path has the same no-claim rule as the child-exited path."""
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="1.9.0")

    monkeypatch.setattr(daemon, "port_listening",
                        lambda h, p, timeout=0.25: False)
    # Both alive: 4321 so its record is not reaped as stale, and the child
    # so `_await_ready` reaches the deadline rather than the exited branch.
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: pid in (4321, 999999))
    monkeypatch.setattr(daemon, "spawn_detached", lambda host, port: 999999)
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: None)

    with pytest.raises(daemon.DaemonError):
        daemon.start(host="127.0.0.1", port=8000, timeout=0.3)

    state = daemon.read_state()
    assert state is not None, "the deadline path deleted another record"
    assert state["pid"] == 4321


def test_binding_does_not_do_a_reverse_dns_lookup(monkeypatch):
    """Binding must not call socket.getfqdn().

    HTTPServer.server_bind sets server_name from socket.getfqdn(host), a
    reverse lookup that blocks for tens of seconds where the resolver has no
    answer for a loopback address (an mDNS query with no responder on a CI
    runner). The socket is already bound by then, so the port listens while
    the startup banner — which `ui start` parses to learn an ephemeral port —
    has still not been printed: a dashboard that is serving is reported as
    "did not start" and killed. Nothing reads server_name, so the lookup buys
    nothing and this asserts it does not happen.
    """
    from exptrack.dashboard import app as _app
    from exptrack.dashboard.handler import DashboardHandler

    def _no_lookups(*a, **kw):
        raise AssertionError("server_bind performed a reverse DNS lookup")

    monkeypatch.setattr(socket, "getfqdn", _no_lookups)

    server = _app.DashboardServer(("127.0.0.1", 0), DashboardHandler)
    try:
        assert server.server_name == "127.0.0.1"
        assert server.server_port == server.server_address[1]
    finally:
        server.server_close()


# ── One dashboard, many projects ────────────────────────────────────────────
# The server has been multi-project since 2.0, but `ui start` was not: run in
# a second worktree it found no per-project state, spawned a second server,
# and that server died on EADDRINUSE — surfaced as "Port 7331 is already in
# use by something that is not an exptrack dashboard". These cover the
# user-global recording that makes the second `ui start` hand back a URL.

@pytest.fixture()
def shared_dashboard(tmp_path, monkeypatch):
    """A live dashboard, recorded user-globally, started by another project.

    The setup every test in this section needs: six of them repeated the same
    four lines, and the point under test was never the setup.
    """
    other = tmp_path / "other-worktree"
    (other / ".exptrack").mkdir(parents=True)
    _record_shared(other)
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "port_listening", lambda h, p, timeout=0.25: True)
    return other


def _record_shared(root, port=7331, pid=4321):
    """Write a user-global state file naming *root* as the serving project."""
    import json
    daemon.global_state_path().write_text(json.dumps({
        "pid": pid, "host": "127.0.0.1", "port": port,
        "started_at": "2026-09-21T00:00:00+00:00", "version": "2.0.0",
        "root": str(root), "project": "deadbeefdeadbeef",
    }))


def test_write_state_records_the_dashboard_user_globally(tmp_project, tmp_home):
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="2.0.0")
    shared = daemon.read_global_state()
    assert shared["pid"] == 4321
    assert shared["port"] == 7331
    # The serving project's root is what lets another checkout read its token.
    from pathlib import Path
    assert Path(shared["root"]).resolve() == tmp_project.resolve()
    assert shared["project"]


def test_global_state_carries_no_token(tmp_project, tmp_home):
    daemon.write_state(pid=1, host="127.0.0.1", port=7331, version="2.0.0")
    assert "token" not in daemon.global_state_path().read_text().lower()


def test_start_reuses_a_dashboard_started_from_another_project(
        tmp_project, shared_dashboard, monkeypatch):
    """The whole point of the release: three worktrees, one server."""
    spawned = []
    monkeypatch.setattr(daemon, "spawn_detached",
                        lambda host, port: spawned.append((host, port)))

    result = daemon.start(host="127.0.0.1", port=7331)

    assert spawned == [], "must not have spawned a second dashboard"
    assert result["status"] == "already-running"
    assert result["served_by"] == "other-worktree"
    # The URL names *this* project, which is what the browser tab binds to.
    from exptrack import projects
    assert f"project={projects.project_id(tmp_project)}" in result["url"]


def test_reuse_registers_this_project_so_the_switcher_lists_it(
        tmp_project, shared_dashboard, monkeypatch):
    """Handing back a URL is useless if the project is not in the switcher."""
    monkeypatch.setattr(daemon, "spawn_detached",
                        lambda host, port: pytest.fail("spawned"))

    daemon.start(host="127.0.0.1", port=7331)

    from exptrack import projects
    assert str(tmp_project.resolve()) in {e["path"] for e in projects.registered()}


def test_start_on_an_explicit_other_port_still_refuses_rather_than_reusing(
        tmp_project, shared_dashboard, monkeypatch):
    """`--port 8000` is a request for a server on 8000, not for a URL to the
    one on 7331. Reusing there would silently ignore what was asked for."""
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="2.0.0")
    _record_shared(shared_dashboard)      # write_state overwrote the slot
    monkeypatch.setattr(daemon, "spawn_detached",
                        lambda host, port: pytest.fail("spawned"))

    with pytest.raises(daemon.DaemonError) as exc:
        daemon.start(host="127.0.0.1", port=8000)
    assert "7331" in str(exc.value)


def test_a_dead_shared_recording_is_cleared_not_reused(
        tmp_project, shared_dashboard, monkeypatch):
    monkeypatch.setattr(daemon, "pid_alive", lambda pid: False)

    assert daemon.foreign_shared_state("127.0.0.1") is None
    assert daemon.read_global_state() is None


def test_running_state_falls_back_to_the_shared_recording(
        tmp_project, shared_dashboard, monkeypatch):
    """`ui status` in a worktree that did not start the dashboard used to say
    "Dashboard is not running" while the browser tab was being served."""

    state = daemon.running_state("127.0.0.1", 0)
    assert state and state["pid"] == 4321


def test_clear_state_leaves_another_projects_shared_recording_alone(
        tmp_project, tmp_home, tmp_path):
    """One project's cleanup must not erase another's only record."""
    other = tmp_path / "other-worktree"
    (other / ".exptrack").mkdir(parents=True)
    _record_shared(other)

    daemon.clear_state()

    assert daemon.read_global_state() is not None


def test_clear_state_drops_the_shared_recording_this_project_owns(
        tmp_project, tmp_home):
    daemon.write_state(pid=4321, host="127.0.0.1", port=7331, version="2.0.0")
    daemon.clear_state()
    assert daemon.read_global_state() is None


def test_describe_state_url_carries_both_token_and_project():
    out = daemon.describe_state({"host": "127.0.0.1", "port": 7331},
                                status="already-running", token="abc",
                                project="feedfacefeedface")
    assert out["url"] == "http://127.0.0.1:7331/?token=abc&project=feedfacefeedface"


def test_stop_from_another_worktree_clears_the_shared_recording(
        tmp_project, shared_dashboard, monkeypatch):
    """`ui stop` in a checkout that did not start the dashboard still stopped
    it, so leaving the shared record behind makes the next `ui start` probe a
    dead pid to learn what this call already knew."""
    monkeypatch.setattr(daemon, "_signal_all", lambda pids, sig: [])
    monkeypatch.setattr(daemon, "_released", lambda h, p, g: True)
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [])

    result = daemon.stop()

    assert result["stopped"] and result["pids"] == [4321]
    assert daemon.read_global_state() is None


def test_stop_leaves_a_shared_recording_for_a_dashboard_it_did_not_stop(
        tmp_project, shared_dashboard, monkeypatch):
    """The pid scoping is the whole safety of the clear above."""
    daemon.write_state(pid=999, host="127.0.0.1", port=8000, version="2.0.0")
    # write_state overwrote the shared slot with pid 999 / this project — so
    # re-record it as the *other* project's dashboard on 7331, which is the
    # recording the stop below must not touch.
    _record_shared(shared_dashboard)
    monkeypatch.setattr(daemon, "_signal_all", lambda pids, sig: [])
    monkeypatch.setattr(daemon, "_released", lambda h, p, g: True)
    monkeypatch.setattr(daemon, "find_pids_on_port", lambda port: [999])

    daemon.stop(port=8000)

    assert daemon.read_global_state() is not None


def test_windows_dashboard_has_a_hidden_console_not_none(tmp_project, monkeypatch):
    """A DETACHED_PROCESS dashboard has no console, so Windows opened a new
    visible console window for every `git` it ran — a dashboard left open
    filled the screen with terminals. CREATE_NO_WINDOW gives it an invisible
    console its children share."""
    import subprocess as _sp

    seen = {}

    class _Proc:
        pid = 4242

    def fake_popen(argv, **kw):
        seen.update(kw)
        return _Proc()

    import os as _os

    class _NtOs:   # only the daemon's view of `os` says Windows
        name = "nt"

        def __getattr__(self, attr):
            return getattr(_os, attr)

    monkeypatch.setattr(daemon, "os", _NtOs())
    monkeypatch.setattr(_sp, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(_sp, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(daemon.subprocess, "Popen", fake_popen)
    assert daemon.spawn_detached("127.0.0.1", 0) == 4242
    flags = seen["creationflags"]
    assert flags & 0x08000000, "CREATE_NO_WINDOW"
    assert not flags & 0x00000008, "DETACHED_PROCESS would pop a window per child"
