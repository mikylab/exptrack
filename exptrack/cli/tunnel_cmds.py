"""
exptrack/cli/tunnel_cmds.py — reaching a remote dashboard in one command.

Reaching a dashboard on another machine used to mean: ssh in, cd to a
directory that differs per machine, activate a venv, run `exptrack ui`, copy
the token out of its output, open a second terminal, forward the port, paste
the token into the browser.

Two of those steps are the ones that go wrong, and both have the same cause.
`ssh host 'command'` runs a *non-interactive* shell, which does not source
.bashrc — so `source .venv/bin/activate` and `conda activate` frequently fail
there. A venv's bin/ holds the console script with the interpreter baked into
its shebang, so calling it by absolute path needs no activation at all. And
the token could not be retrieved programmatically until `ui status --json`
existed.

This module builds commands; it does not trust remotes.json, which is an
ordinary file the user edits by hand. Every interpolated value is quoted.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import config as cfg
from .formatting import G, Y, col, die, dim


class TunnelError(Exception):
    """A tunnel operation failed, with a message meant for the user."""


def remotes_load() -> dict:
    """Saved remotes, or {} if none. A corrupt file reads as empty."""
    try:
        data = json.loads(cfg.remotes_file_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def remotes_save(data: dict) -> Path:
    """Persist the remotes map 0600. Holds hostnames and paths, not secrets,
    but it maps out the user's infrastructure.

    Routed through config.open_private rather than write_text()+chmod(): the
    same create-then-chmod window and followable-symlink exposure that
    applied to the dashboard token applies here too — this module was written
    after open_private existed, so it should have used it from the start.
    """
    p = cfg.remotes_file_path()
    fd = cfg.open_private(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2))
    return p


def validate_host(host: str) -> str:
    """Return *host*, or raise if ssh would read it as a flag.

    A value beginning with "-" is parsed by ssh as an option rather than a
    destination — `-oProxyCommand=...` in a hostname field is arbitrary local
    command execution.
    """
    host = (host or "").strip()
    if not host:
        raise ValueError("A remote host is required.")
    if host.startswith("-"):
        raise ValueError(f"Invalid host {host!r}: must not begin with '-'.")
    return host


def build_remote_command(directory: str, exptrack_bin: str | None,
                          port: int) -> str:
    """The shell command run on the remote host.

    The cd is load-bearing: config.project_root() resolves from the working
    directory, so without it the remote dashboard serves the wrong project.
    """
    d = shlex.quote(directory.rstrip("/"))
    # `'quoted-dir'/.venv/bin/exptrack` is one shell word: adjacent quoted and
    # unquoted text concatenate, so this is exactly as safe as quoting the
    # whole path in one shlex.quote() call would be (shlex.quote always
    # returns either a closed quote or a metacharacter-free bare word, and the
    # appended suffix is only "/", "." and letters — neither form lets
    # anything escape). Building it this way keeps the *quoted substring* for
    # a given directory identical wherever it appears (cd vs. default binary),
    # which is what the tests key off of.
    b = shlex.quote(exptrack_bin) if exptrack_bin else f"{d}/.venv/bin/exptrack"
    p = shlex.quote(str(int(port)))
    # `ui start` writes its banner/errors to stderr only and nothing to
    # stdout (see cmd_ui_start / DaemonError) — >/dev/null silences the
    # banner on a successful start without touching stderr, so a *failed*
    # start's diagnostic (including the remote log tail DaemonError carries)
    # still flows up ssh's stderr channel instead of being discarded by a
    # blanket `2>&1 >/dev/null`.
    return (f"cd {d} && {b} ui start --port {p} >/dev/null "
            f"&& {b} ui status --json")


def build_forward_argv(host: str, local_port: int, remote_port: int) -> list[str]:
    """The ssh argv that backgrounds the port forward.

    The bind address is explicit. The bare `-L <port>:...` form is
    loopback-only by default, but a user's `GatewayPorts yes` in ~/.ssh/config
    silently widens it to every interface — publishing the tunnel to the
    network. Naming 127.0.0.1 makes local configuration unable to change that.

    -f -N because `ssh -N -L` blocks the terminal exactly as `exptrack ui`
    used to, which would move the problem rather than solve it.
    """
    return ["ssh", "-f", "-N",
            "-L", f"127.0.0.1:{int(local_port)}:localhost:{int(remote_port)}",
            validate_host(host)]


# Matches `"token": "..."` or `token=...` however parse_status's error path
# quotes it, so a partially garbled status line never echoes a live token
# into a terminal or a CI log — that path exists to show the user *why*
# parsing failed, not to hand them (or an onlooker) a working credential.
_TOKEN_RE = re.compile(r'("?token"?\s*[:=]\s*)"?[^"\s,}]+"?', re.IGNORECASE)


def _redact_token(text: str) -> str:
    return _TOKEN_RE.sub(lambda m: m.group(1) + '"<redacted>"', text)


def parse_status(output: str, local_port: int) -> dict:
    """Turn `ui status --json` output into local connection details."""
    try:
        payload = json.loads(output.strip())
    except (ValueError, TypeError) as e:
        detail = _redact_token((output or "").strip()[:400]) or "(no output)"
        raise TunnelError(
            "The remote did not return dashboard status. It said:\n" + detail
        ) from e
    if not isinstance(payload, dict):
        # Valid JSON that isn't an object (`null`, `123`, `[]`, ...) — .get()
        # on it would raise AttributeError, the opaque traceback this
        # function exists to prevent.
        detail = _redact_token(str(payload)[:400])
        raise TunnelError(
            "The remote did not return dashboard status. It said:\n" + detail)
    if not payload.get("running"):
        raise TunnelError("The remote dashboard is not running.")
    token = payload.get("token", "")
    url = f"http://localhost:{int(local_port)}/"
    if token:
        url += f"?token={token}"
    return {"url": url, "token": token, "version": payload.get("version", ""),
            "remote_port": payload.get("port")}


def version_skew_message(remote: str, local: str) -> str:
    """A warning when the two installs differ, else "".

    Cheap here, and it addresses a real confusion: a dashboard behaving like a
    version other than the one you believe you are running, because a checkout
    sat on a different branch or an editable install's metadata went stale.
    """
    if not remote or not local or remote == local:
        return ""
    return (f"Remote is running exptrack {remote}; this machine has {local}. "
            f"The dashboard's behaviour is the remote's.")


# ── Command entry points ──────────────────────────────────────────────────────
#
# Everything above this line is pure and covered directly by tests/test_tunnel.py.
# Everything below shells out (ssh) and is exercised through those pure
# functions plus an injectable runner, never a live network.

def _run(argv, timeout=None):
    """The one place a subprocess is spawned — tests monkeypatch this.

    Uses real temp files for stdout/stderr, not pipes. `ssh -f` daemonizes by
    forking and re-execing with the *noclose* flag, so the backgrounded child
    keeps the parent's stdout/stderr fds open for the tunnel's entire
    lifetime. `subprocess.run(capture_output=True)` reads pipes until it sees
    EOF, which would not happen until the tunnel itself exits — not until the
    short-lived `ssh -f` parent (which already reported success and exited)
    does. A real file needs no EOF: the bytes already written are there to
    read the moment .run() returns, regardless of who still holds the fd.
    """
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as out, \
         tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as err:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out,
                              stderr=err, timeout=timeout)
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(argv, proc.returncode,
                                           out.read(), err.read())


def cmd_tunnel(args):
    """Dispatch for `exptrack tunnel [add|list|rm|stop|connect] <name>`.

    The bare `exptrack tunnel <name>` form arrives here as `tunnel_sub ==
    "connect"` — `main()` rewrites argv to insert that token before argparse
    ever runs, since an optional positional ahead of add_subparsers() cannot
    coexist with the subparser (see the parser comment in main.py).
    """
    sub = getattr(args, "tunnel_sub", None)
    if sub == "add":
        return _tunnel_add(args)
    if sub == "list":
        return _tunnel_list(args)
    if sub == "rm":
        return _tunnel_rm(args)
    if sub == "stop":
        return _tunnel_stop(args)
    if sub == "connect":
        return _tunnel_connect(args)
    die("Usage: exptrack tunnel <name> | add|list|rm|stop <name>")


def _tunnel_add(args):
    try:
        host = validate_host(args.host)
    except ValueError as e:
        die(str(e))
    remotes = remotes_load()
    remotes[args.name] = {
        "host": host,
        "dir": args.dir,
        "remote_port": args.remote_port,
        "local_port": args.local_port or args.remote_port,
        "exptrack_bin": args.exptrack_bin,
    }
    try:
        path = remotes_save(remotes)
    except OSError as e:
        # A read-only $HOME (or a symlink planted at remotes.json — see
        # open_private) must die() like every other failure in this module,
        # not surface as a raw OSError traceback.
        die(f"Could not save {cfg.remotes_file_path()}: {e}")
    print(col(f"Saved remote {args.name!r} to {path}", G), file=sys.stderr)


def _tunnel_list(args):
    """List saved remotes — a malformed entry is marked, never a crash.

    This is the one command whose entire job is showing what is in
    remotes.json, so a hand-edited bad entry must not take down the listing
    of every *other* remote with a raw KeyError.
    """
    remotes = remotes_load()
    if not remotes:
        print(dim("No remotes configured. Add one with: "
                   "exptrack tunnel add <name> --host user@box --dir /path"),
              file=sys.stderr)
        return
    for name, r in sorted(remotes.items()):
        issues = _remote_issues(r)
        if issues:
            print(col(f"{name:<16} invalid entry — {'; '.join(issues)}", Y),
                  file=sys.stderr)
            continue
        print(f"{name:<16} {r['host']}:{r['dir']}  "
              f"local:{r.get('local_port')} -> remote:{r.get('remote_port')}")


def _tunnel_rm(args):
    remotes = remotes_load()
    if remotes.pop(args.name, None) is None:
        die(f"No remote named {args.name!r}.")
    try:
        remotes_save(remotes)
    except OSError as e:
        die(f"Could not save {cfg.remotes_file_path()}: {e}")
    print(col(f"Removed remote {args.name!r}.", G), file=sys.stderr)


def _remote_issues(r: dict) -> list[str]:
    """Everything wrong with a raw remotes.json entry, or [] if it's usable.

    A pure predicate so both the fatal path (`_validated_remote`, used
    wherever a single remote must be usable or the command cannot proceed)
    and the non-fatal path (`_tunnel_list`, which must show every remote it
    can rather than dying on the first bad one) share one definition of
    "valid" — remotes.json is an ordinary file the user can hand-edit (see
    the module docstring), so both paths need it.
    """
    if not isinstance(r, dict):
        return ["is not a valid entry"]
    missing = [k for k in ("host", "dir", "remote_port", "local_port")
               if k not in r]
    if missing:
        # Further checks would themselves KeyError on the same keys.
        return [f"missing: {', '.join(missing)}"]
    issues = []
    for key in ("remote_port", "local_port"):
        try:
            int(r[key])
        except (TypeError, ValueError):
            issues.append(f"non-numeric {key!r}: {r[key]!r}")
    if not isinstance(r.get("host"), str) or not isinstance(r.get("dir"), str):
        issues.append("'host' and 'dir' must be strings")
    bin_ = r.get("exptrack_bin")
    if bin_ is not None and not isinstance(bin_, str):
        issues.append(f"non-string 'exptrack_bin': {bin_!r}")
    return issues


def _validated_remote(name: str, r: dict) -> dict:
    """Validate and coerce a raw remotes.json entry, or die naming the file.

    An incomplete or mistyped entry must produce a message naming the file
    and what is wrong, never a bare KeyError/ValueError/AttributeError
    traceback from deep inside ssh plumbing.
    """
    issues = _remote_issues(r)
    if issues:
        die(f"Remote {name!r} in {cfg.remotes_file_path()} is invalid: "
            f"{'; '.join(issues)}.")
    out = dict(r)
    out["remote_port"] = int(out["remote_port"])
    out["local_port"] = int(out["local_port"])
    return out


def _remote_or_die(name: str) -> dict:
    r = remotes_load().get(name)
    if not r:
        die(f"No remote named {name!r}. List them with: exptrack tunnel list")
    return _validated_remote(name, r)


def _run_ssh_or_die(argv: list[str], timeout: int, what: str):
    """`_run(argv)`, turning the ways ssh itself can fail into a named error.

    `ssh` missing from PATH is realistic on Windows; a slow or unresponsive
    host hits the timeout. Both would otherwise surface as a raw traceback
    with no indication which of the two ssh calls (start, or forward) failed.
    """
    try:
        return _run(argv, timeout=timeout)
    except FileNotFoundError:
        die("Could not run 'ssh' — is an OpenSSH client installed and on "
            "PATH?")
    except subprocess.TimeoutExpired:
        die(f"{what} timed out after {timeout}s.")


def _diagnose_remote_failure(name: str, host: str, r: dict, stderr: str) -> str:
    """One message per likely cause, naming exactly what was tried.

    A failed `cd` and a missing exptrack binary used to share one message
    that always suggested --exptrack-bin, which is the wrong remediation for
    a directory that simply does not exist on the remote.
    """
    text = stderr or "(no output)"
    directory = r["dir"]
    if re.search(r"\bcd\b.{0,40}No such file or directory", text) or \
            f"cd: {directory}" in text or f"cd: {shlex.quote(directory)}" in text:
        return (f"The remote directory does not exist: {host}:{directory}\n"
                f"{text}")
    default_bin = f"{directory.rstrip('/')}/.venv/bin/exptrack"
    binary = r.get("exptrack_bin") or default_bin
    if "No such file or directory" in text or "command not found" in text:
        return (f"Could not run exptrack on the remote at {binary}\n{text}\n"
                f"If that is not the right path, set it with: "
                f"exptrack tunnel add {name} --host {host} --dir {directory} "
                f"--exptrack-bin <path>")
    return f"Could not start the remote dashboard on {host}.\n{text}"


def _start_remote_dashboard(name: str, host: str, r: dict) -> dict:
    """Run the remote start+status chain over ssh and parse its output."""
    remote_cmd = build_remote_command(r["dir"], r.get("exptrack_bin"),
                                       r["remote_port"])
    proc = _run_ssh_or_die(["ssh", host, remote_cmd], 120,
                           f"Starting the remote dashboard on {host}")
    if proc.returncode != 0:
        # ui start's success banner (never seen here — its stdout is a JSON
        # line only) prints the dashboard URL, token and all, to stderr; if
        # `ui start` succeeded and the *second* command in the chain
        # (`ui status --json`) is what failed, that URL is sitting in this
        # same stderr blob. Redact before it reaches a terminal or CI log —
        # the same requirement F9 already applies to parse_status's echo.
        stderr = _redact_token((proc.stderr or "").strip()[:800])
        die(_diagnose_remote_failure(name, host, r, stderr))
    try:
        return parse_status(proc.stdout, local_port=r["local_port"])
    except TunnelError as e:
        die(str(e))


def _tunnel_connect(args):
    """Start the remote dashboard, forward the port, print the local URL."""
    from .. import __version__ as local_version
    from ..dashboard import daemon

    if not args.name:
        die("A remote name is required. List saved remotes with: "
            "exptrack tunnel list")

    r = _remote_or_die(args.name)
    try:
        host = validate_host(r["host"])
    except ValueError as e:
        die(str(e))

    if daemon.port_listening("127.0.0.1", r["local_port"]):
        # `exptrack tunnel gpu01` must be safe to run repeatedly — that's the
        # normal usage (each invocation re-asserts the tunnel; the remote
        # `ui start` it chains is itself idempotent). With a tunnel already
        # up, the local port is held *by that tunnel*, so dying here broke
        # the one workflow this command exists for. Identify what holds the
        # port before deciding: an existing ssh forward is success, anything
        # else is a real conflict and must be named, not just refused.
        pids = daemon.find_pids_on_port(r["local_port"])
        for pid in pids:
            name = _process_name(pid)
            if name and "ssh" in name.lower():
                print(col(f"Tunnel to {args.name} is already up.", G),
                      file=sys.stderr)
                print(f"  http://localhost:{r['local_port']}/", file=sys.stderr)
                print(dim(f"  Close it with: exptrack tunnel stop {args.name}"),
                      file=sys.stderr)
                return
        holder = f"{_process_name(pids[0])} (pid {pids[0]})" if pids else "another process"
        die(f"Local port {r['local_port']} is already in use by {holder}, "
            f"not a tunnel to {args.name}. "
            f"Edit the remote with a different --local-port.")

    info = _start_remote_dashboard(args.name, host, r)

    fwd = _run_ssh_or_die(
        build_forward_argv(host, r["local_port"],
                           info["remote_port"] or r["remote_port"]),
        30, "The port forward")
    if fwd.returncode != 0:
        stderr = _redact_token((fwd.stderr or "").strip()[:400])
        die(f"Port forward failed.\n{stderr}")

    skew = version_skew_message(info["version"], local_version)
    if skew:
        print(col(f"[exptrack] {skew}", Y), file=sys.stderr)
    print(col(f"Tunnel to {args.name} is up.", G), file=sys.stderr)
    print(f"  {info['url']}", file=sys.stderr)
    print(dim(f"  Close it with: exptrack tunnel stop {args.name}"),
          file=sys.stderr)


def _process_name(pid: int) -> str | None:
    """Best-effort process name for *pid*, or None if it cannot be found.

    stdlib-only (no psutil): shells out to `ps`, which does not exist on
    Windows. The caller must treat None as "unknown", never as "not ssh".
    """
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                             capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    name = (out.stdout or "").strip()
    return name or None


def _tunnel_stop(args):
    """Close the forward by killing the ssh process holding the local port.

    Two honesty requirements this used to fail. First, `find_pids_on_port`
    is fuser/lsof only (POSIX) — on Windows it always returns [], which must
    not be read as "no tunnel is running": that is a detection gap, not
    evidence the port is free, and reporting it as a clean stop would leave
    an open tunnel while telling the user it was closed. Second, the port a
    remote was configured with can just as easily be held by something else
    entirely — a local `exptrack ui` on the same port — so a pid is only
    killed after naming what it is, and anything that doesn't look like ssh
    is left alone rather than silently taken down and reported as "closed".
    """
    from ..dashboard import daemon

    r = _remote_or_die(args.name)
    pids = daemon.find_pids_on_port(r["local_port"])
    if not pids:
        if platform.system() == "Windows":
            print(col(f"Could not check local port {r['local_port']}: pid "
                      f"lookup (fuser/lsof) isn't available on Windows, so "
                      f"a running tunnel cannot be told apart from a free "
                      f"port. If it's still open, close the ssh process by "
                      f"hand.", Y), file=sys.stderr)
        else:
            print(dim(f"No tunnel is holding local port {r['local_port']}."),
                  file=sys.stderr)
        return
    stopped_any = False
    for pid in pids:
        name = _process_name(pid)
        if name and "ssh" not in name.lower():
            print(col(f"Pid {pid} on local port {r['local_port']} is "
                      f"{name!r}, not ssh — leaving it running.", Y),
                  file=sys.stderr)
            continue
        label = f"{name} (pid {pid})" if name else f"pid {pid}"
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            print(col(f"Could not stop {label}: {e}", Y), file=sys.stderr)
            continue
        print(dim(f"Sent SIGTERM to {label}."), file=sys.stderr)
        stopped_any = True
    if stopped_any:
        print(col(f"Closed the tunnel on local port {r['local_port']}.", G),
              file=sys.stderr)
    else:
        print(dim("Nothing was stopped."), file=sys.stderr)
