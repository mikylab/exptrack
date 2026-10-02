"""
exptrack/dashboard/daemon.py — running the dashboard as a background process.

The dashboard used to be foreground-only, which cost a terminal per project
and died on SSH disconnect (default SIGHUP). This module owns the other
option: spawn detached, record where it went, and be able to answer "is it
running?" and "stop it" without shelling out to fuser/lsof — which is what
makes those work on Windows, where neither binary exists.

The runtime state file deliberately holds no token. The token lives in
.exptrack/dashboard_token (config.token_file_path), which already existed and
is already first in handler._get_auth_token()'s resolution order. One secret,
one location.
"""
from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import config as cfg

# Seconds a liveness probe waits for a TCP connect before calling the port
# dead. Generous enough for a loaded machine, short enough that `ui status`
# stays instant.
_PROBE_TIMEOUT = 0.25


def state_file_path() -> Path:
    """Path of the runtime state file (``.exptrack/dashboard.json``)."""
    return cfg.exptrack_dir() / "dashboard.json"


def global_state_path() -> Path:
    """``~/.exptrack/dashboard.json`` — the *machine's* dashboard, not a
    project's.

    The per-project state file below records where a dashboard went for the
    project that started it, which is all a single-project dashboard ever
    needed. One dashboard now serves every project the switcher lists, so
    "is a dashboard running?" stopped being a per-checkout question: asked
    from a second worktree, the per-project file is empty, `ui start` spawns
    a second server, and the second server dies on EADDRINUSE — reported as
    "Port 7331 is already in use by something that is not an exptrack
    dashboard", which is both wrong and unactionable.

    User-global, beside `projects.json`, for the same reason that file is:
    whichever install's `exptrack` you run has to find the same answer.
    """
    return cfg.user_dir() / "dashboard.json"


def log_file_path() -> Path:
    """Path of the detached server's log (``.exptrack/dashboard.log``)."""
    return cfg.exptrack_dir() / "dashboard.log"


# Re-exported for backward compatibility: this used to be defined here, and
# is now the shared implementation in config.py (config is the lower layer —
# this module already imports it — and write_token needed the exact same
# create-time-0600 + O_NOFOLLOW guarantee, so there is now one implementation
# instead of two).
open_private = cfg.open_private


def _write_state_file(path: Path, payload: dict) -> None:
    """Write *payload* as private (0600) JSON to *path*. Raises on failure.

    O_TRUNC rather than unlink-then-create: the file is already ours and
    0600, and unlinking first would widen the race we are avoiding.
    """
    fd = open_private(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=2)


def _read_state_file(path: Path) -> dict | None:
    """The recording at *path*, or None if absent or unreadable.

    A corrupt state file is treated as "no dashboard recorded" rather than an
    error: it is a cache of where a process went, not a source of truth, and
    refusing to run `ui status` because of it would be worse than useless.
    """
    try:
        raw = path.read_text()
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _unlink_quietly(path: Path) -> None:
    """Remove *path* if present. Never raises."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def write_state(pid: int, host: str, port: int, version: str) -> Path:
    """Record where the detached dashboard went. Returns the file path."""
    cfg.ensure_gitignore_rules()
    payload = {
        "pid": int(pid),
        "host": host,
        "port": int(port),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
    }
    p = state_file_path()
    _write_state_file(p, payload)

    # The same recording, user-globally, plus *which* project this dashboard
    # was started from — a second checkout needs the root to read the serving
    # project's token, and the id to say whose dashboard it is reusing. A
    # failure here is not a failed start: the dashboard is already running and
    # this file is a convenience, so it degrades to "no shared dashboard
    # recorded" (one extra server, the pre-2.0 behaviour) rather than an error.
    from .. import projects
    root = cfg.project_root()
    try:
        _write_state_file(global_state_path(),
                          {**payload, "root": str(root),
                           "project": projects.project_id(root)})
    except OSError as e:
        from ..core.utils import debug_log
        debug_log(f"daemon: could not record the shared dashboard: {e}")
    return p


def read_global_state() -> dict | None:
    """The user-global recording, or None if absent or unreadable."""
    return _read_state_file(global_state_path())


def clear_global_state() -> None:
    """Remove the user-global state file if present. Never raises."""
    _unlink_quietly(global_state_path())


def read_state() -> dict | None:
    """This project's recording, or None if absent or unreadable."""
    return _read_state_file(state_file_path())


def _recording_is_ours(state: dict) -> bool:
    """Whether *state* names this project as the one that started it.

    A recording with no `root` at all was written by a pre-2.0 install and
    counts as ours — there was only one project then. A `root` the
    filesystem will not resolve counts as *not* ours, which is the safe
    answer for both callers: neither erasing nor reusing a recording we
    cannot identify.
    """
    recorded = state.get("root") or ""
    if not recorded:
        return True
    try:
        return Path(recorded).resolve() == cfg.project_root().resolve()
    except OSError:
        return False


def _clear_global_state_for(pids: list[int]) -> None:
    """Drop the shared recording when it names a pid we just stopped.

    `clear_state` refuses to touch a shared recording that belongs to another
    project, which is right for cleanup but wrong here: `ui stop` run from a
    worktree that did not start the dashboard *did* stop that dashboard, and
    leaving its record behind means the next `ui start` has to probe a dead
    pid to discover what this call already knows. Scoped to the pids actually
    stopped, so it can never erase a record of some other live dashboard.
    """
    shared = read_global_state()
    if shared and shared.get("pid") in pids:
        clear_global_state()


def clear_state() -> None:
    """Remove the state file if present, and the user-global one it owns.

    The shared recording is dropped only when `_recording_is_ours` says this
    project started it. Clearing it unconditionally would let one project's
    cleanup erase another project's live dashboard's only record — the same
    orphaning `start`'s refusal exists to prevent.
    """
    _unlink_quietly(state_file_path())
    shared = read_global_state()
    if shared and _recording_is_ours(shared):
        clear_global_state()


def _pid_alive_windows(pid: int) -> bool:
    """Windows liveness probe via OpenProcess — never via os.kill(pid, 0).

    ``signal.CTRL_C_EVENT == 0``, so ``os.kill(pid, 0)`` on Windows does not
    probe liveness at all: CPython routes it to
    ``GenerateConsoleCtrlEvent``, which only works within the caller's own
    console process group. Every dashboard is spawned with
    ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`` (see ``spawn_detached``),
    so it is *always* outside that group — ``os.kill(pid, 0)`` on a live,
    detached dashboard fails with ERROR_INVALID_PARAMETER (87), the exact
    error a genuinely dead pid produces, so the two cases were
    indistinguishable and every live detached dashboard read as dead. For a
    pid that *does* share the caller's console, ``os.kill(pid, 0)`` would
    actually deliver a Ctrl-C — a liveness check must never risk killing the
    thing it's asking about.

    OpenProcess + WaitForSingleObject(handle, 0) is a real query with no such
    side effect. WaitForSingleObject, not GetExitCodeProcess: the latter
    reports STILL_ACTIVE (259) for a running process, which is ambiguous
    with a process that has already exited with status code 259.
    """
    import ctypes

    # use_last_error=True: ctypes.get_last_error() below only reflects
    # GetLastError() for calls made through a DLL object opened this way —
    # plain ctypes.windll.kernel32 does not track it, and would make the
    # OpenProcess-failure branch below read a stale/wrong error code.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    ERROR_ACCESS_DENIED = 5
    WAIT_TIMEOUT = 258

    # Without explicit argtypes/restype, ctypes defaults every return value to
    # c_int (32-bit signed). On 64-bit Windows a HANDLE is 64 bits, so the
    # default silently truncates it — and the truncated value is what
    # CloseHandle then receives. This only worked by accident, because handle
    # values are typically small; it is exactly the class of bug this release
    # exists to eliminate everywhere else.
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid))
    if not handle:
        # NULL handle: inspect why. ERROR_INVALID_PARAMETER (87) means no
        # such pid exists. ERROR_ACCESS_DENIED (5) means it exists but this
        # user can't query it — treated as alive, matching the POSIX
        # PermissionError branch below.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        # A handle can outlive the process it named; a signalled (non-timeout)
        # wait means the process has already exited.
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)  # a 5s-poll caller must never leak these


def pid_alive(pid: int) -> bool:
    """Whether *pid* names a live process this user can signal.

    On POSIX, ``os.kill(pid, 0)`` raises ``ProcessLookupError``/``ESRCH`` for a
    missing pid, so any *other* OSError implies the process exists (e.g. some
    other transient failure) and is treated as alive.

    Windows never reaches ``os.kill`` at all — see ``_pid_alive_windows``.
    """
    if not pid or pid < 1:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OverflowError:
        return False  # pid outside the platform's valid range: can't exist
    except OSError as e:
        return e.errno != errno.ESRCH
    return True


def port_listening(host: str, port: int, timeout: float = _PROBE_TIMEOUT) -> bool:
    """Whether something accepts TCP connections on *host*:*port*."""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        with socket.create_connection((probe_host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


class DaemonError(Exception):
    """A lifecycle operation failed, with a message meant for the user."""


# How long the parent waits for the child to accept connections. A cold
# import of the dashboard on a loaded shared workstation is the slow case.
_READY_TIMEOUT = 10.0
_POLL_INTERVAL = 0.1


def tail_log(lines: int = 20) -> str:
    """Last *lines* lines of the dashboard log, or "" if there is none."""
    try:
        content = log_file_path().read_text(errors="replace")
    except OSError:
        return ""
    return "\n".join(content.splitlines()[-lines:])


def _log_size() -> int:
    """Byte offset marking "before this spawn" in the log.

    Captured immediately before the child is spawned so `_bound_port`'s
    --port-0 scan only ever looks at bytes the *new* child wrote. Without
    this, a quick restart after a crash (or a crash loop) can leave a
    previous invocation's banner inside the last N lines `tail_log` returns;
    if anything happens to still be listening on that stale port,
    `_bound_port` would report it as the new child's port and `write_state`
    would record the wrong port as authoritative.
    """
    try:
        return log_file_path().stat().st_size
    except OSError:
        return 0


def _read_log_since(offset: int) -> str:
    """Log bytes written after *offset*, or "" if the file is unreadable.

    Byte-offset seek, not `tail_log`'s line-count window: a stale banner
    from a previous invocation must never enter this scan, however short the
    new child's output is so far.
    """
    try:
        with open(log_file_path(), "rb") as f:
            f.seek(offset)
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def spawn_detached(host: str, port: int) -> int:
    """Start the dashboard in a background process. Returns its pid.

    POSIX: start_new_session puts the child in its own session with no
    controlling terminal, which is also what stops SIGHUP killing it when an
    SSH connection drops — the failure app.py used to document as the user's
    problem to solve with nohup.
    """
    cfg.ensure_gitignore_rules()
    log_path = log_file_path()
    fd = open_private(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    log = os.fdopen(fd, "ab")
    argv = [sys.executable, "-m", "exptrack.dashboard.app",
            "--host", str(host), "--port", str(port)]
    kwargs = {"stdout": log, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL, "cwd": str(cfg.project_root())}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except OSError as e:
        # A bad interpreter or a permission error on the spawn itself (not on
        # the dashboard code) used to escape as a raw OSError all the way up
        # through cmd_ui_start, which catches only DaemonError — a traceback
        # from a command whose entire design premise is that a detached
        # failure must be as legible as a foreground one.
        raise DaemonError(
            f"Could not launch the dashboard with {sys.executable!r}: {e}"
        ) from e
    finally:
        log.close()
    return proc.pid


def _alive_state(state: dict | None, host: str, port: int, forget) -> dict | None:
    """*state* if it names a live, listening dashboard on *port*; else None.

    ``forget`` is called for a recording that is provably dead, so the two
    slots (per-project and user-global) each clean up their own file. A
    port mismatch is not death — another dashboard may legitimately be on
    another port — so it returns None without forgetting anything.
    """
    if not state:
        return None
    if not pid_alive(state.get("pid", 0)):
        forget()
        return None
    recorded_port = state.get("port")
    if port and recorded_port != port:
        return None
    if not port_listening(state.get("host", host), recorded_port):
        forget()
        return None
    return state


def running_state(host: str, port: int) -> dict | None:
    """The recorded dashboard, if it is alive and serving *port*.

    Falls back to the user-global recording so `ui status` and `ui stop`
    answer about the shared dashboard from a checkout that did not start it —
    without it, a second worktree reports "Dashboard is not running" while
    the tab in the browser is being served fine.
    """
    local = _alive_state(read_state(), host, port, clear_state)
    if local:
        return local
    return _alive_state(read_global_state(), host, port, clear_global_state)


def local_running_state(host: str, port: int) -> dict | None:
    """`running_state` without the user-global fallback.

    `start` needs the distinction the reporting commands do not: a dashboard
    recorded *for this project* is simply already running, while one recorded
    only user-globally belongs to another project and has to be reported as
    such, with a URL naming this project. Reading `running_state` here made
    the second case look like the first and dropped both.
    """
    return _alive_state(read_state(), host, port, clear_state)


def foreign_shared_state(host: str) -> dict | None:
    """A live dashboard, recorded user-globally, started by another project.

    Port 0 — any port — because the question is "is there already a
    dashboard I can send this project to", and the answer does not depend on
    the port the caller would have picked.

    A recording whose root is this project is the local case and is handled
    by `local_running_state`; returning it here too would make `start`
    report a dashboard as "served by" the project it is already in.
    """
    state = _alive_state(read_global_state(), host, 0, clear_global_state)
    if not state or _recording_is_ours(state):
        return None
    return state


def start(host: str = "127.0.0.1", port: int = 7331,
          timeout: float = _READY_TIMEOUT) -> dict:
    """Ensure a detached dashboard is running; return how to reach it.

    Already running is *success*, not failure: `exptrack tunnel` chains
    `ui start && ui status --json` on every invocation, and re-running a
    tunnel against a live dashboard is the normal case.
    """
    # Function-local: projects imports config, so a module-level import here
    # would cycle back through daemon -> config -> projects -> config. This is
    # the other of the two places (with `exptrack init`) allowed to write the
    # user-global registry — every other command must leave it alone.
    from .. import __version__, projects
    from .app import resolve_startup_token

    existing = local_running_state(host, port)
    if existing:
        # Register even on the already-running path: `ui start` is one of the
        # two commands that may register, and the project the user just ran it
        # in has to reach the switcher whether or not a server had to be
        # spawned for it.
        projects.register(cfg.project_root())
        # `?project=` even for the project that started it: a tab opened
        # without one falls back to the browser's remembered project, so
        # `ui start` in `demo` showed whatever that browser last had open.
        return describe_state(existing, status="already-running",
                              project=_this_project_id())

    # A dashboard started from *another* project already serves this one: the
    # server is multi-project, so a second checkout needs a URL, not a second
    # server. Before 2.0 this path spawned one, and the child died on
    # EADDRINUSE — reported as "port held by something that is not an exptrack
    # dashboard", which named neither the cause nor the fix.
    #
    # Only when the caller would have used the shared dashboard's own port.
    # `ui start --port 8000` against a dashboard on 7331 is a request for a
    # second server on a stated port, and is answered by the orphan refusal
    # below, which names the running one.
    shared = foreign_shared_state(host)
    if shared and (not port or int(shared.get("port", 0)) == int(port)):
        root = cfg.project_root()
        projects.register(root)
        served_root = Path(shared["root"])
        # The token is the *serving* project's: one dashboard, one token, and
        # it is stored under the root that started it. Read through
        # project_scope so `_get_auth_token` resolves that project's token
        # file rather than this one's.
        with cfg.project_scope(served_root):
            token = resolve_startup_token(no_auth=False)
        return describe_state(shared, status="already-running", token=token,
                              project=projects.project_id(root),
                              served_by=served_root.name)

    # A live, listening dashboard recorded on a *different* port must not be
    # silently orphaned. write_state below is a single-slot file — it would
    # overwrite this recording with the new child's, and the first dashboard
    # would become untracked: unreachable through `ui stop`/`ui status` and,
    # on Windows (find_pids_on_port always returns [] — no fuser/lsof),
    # unreachable through the CLI at all. That is exactly the orphaned-process
    # class this subsystem exists to eliminate, reintroduced one layer up.
    # Refusing is the correct scope here — the state file stays single-slot;
    # the second dashboard is simply told to stop the first one first.
    other = read_state()
    if other and port and other.get("port") and int(other["port"]) != port:
        other_port = int(other["port"])
        if pid_alive(other.get("pid", 0)) and port_listening(
                other.get("host", host), other_port):
            raise DaemonError(
                f"A dashboard is already running on port {other_port} "
                f"(pid {other['pid']}). Starting another one on port {port} "
                f"would leave it untracked.\n"
                f"  It already serves this project — open it with:  "
                f"exptrack ui status\n"
                f"  Or stop it first:  exptrack ui stop --port {other_port}")

    if port and port_listening(host, port):
        raise DaemonError(
            f"Port {port} is already in use by something that is not an "
            f"exptrack dashboard.\n"
            f"  Find it:  lsof -i :{port}\n"
            f"  Or pick another port:  exptrack ui start --port {port + 1}")

    # Captured before spawning, not after: it is the boundary `_bound_port`
    # uses to tell this child's own banner apart from a stale one left over
    # by whatever last wrote to this log (see `_log_size`).
    log_offset = _log_size()
    pid = spawn_detached(host, port)
    bound_port = _await_ready(pid, host, port, timeout, log_offset)
    write_state(pid=pid, host=host, port=bound_port, version=__version__)
    projects.register(cfg.project_root())
    token = resolve_startup_token(no_auth=False)
    # Pass the state just written, not a fresh read_state() call: read_state()
    # returns None on any read failure (transient FS hiccup, a concurrent
    # writer), and describe_state(None, ...) would AttributeError right after
    # a start that otherwise succeeded.
    written_state = {"pid": pid, "host": host, "port": bound_port,
                     "version": __version__}
    return describe_state(written_state, status="started", token=token,
                          project=_this_project_id())


def _await_ready(pid: int, host: str, port: int, timeout: float,
                 log_offset: int = 0) -> int:
    """Block until the child serves, or raise DaemonError naming the log.

    A start that fails must be as loud as a foreground one: without this the
    command would print a cheerful "started" for a process that died on
    EADDRINUSE seconds ago.

    Two distinct failure shapes both end here, and they are not the same
    bug: the child can exit on its own (EADDRINUSE, an import error) with
    nothing left to clean up, or it can still be alive at the deadline,
    having never bound anything — a process that would otherwise run on
    forever with no state file pointing at it, exactly the orphan this
    subsystem exists to prevent.

    Neither failure path touches the state file, and that is deliberate.
    This runs *before* ``start`` calls ``write_state``, so any record on
    disk right now belongs to some *other* dashboard — this child has not
    been recorded yet and never will be. Both paths used to
    ``clear_state()`` unconditionally, which meant a start that failed
    could delete a different, live dashboard's record and orphan it: a
    transient ``port_listening`` miss (the probe is 250ms) is enough to
    slip past ``running_state`` and the different-port refusal in
    ``start``, and then the failing child takes the other dashboard's
    registration down with it. A ``clear_state()`` is a claim that the
    record belongs to the thing you just acted on, and this function has
    no such claim. Stale records are cleaned by ``running_state``, which
    owns that job and checks liveness first.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        bound = _bound_port(pid, host, port, log_offset)
        if bound:
            return bound
        if not pid_alive(pid):
            raise DaemonError(_startup_failure_message(
                f"The dashboard process (pid {pid}) exited before it started "
                f"serving."))
        time.sleep(_POLL_INTERVAL)

    # Deadline reached with the child still alive: signal it before giving
    # up so a failed `start` never leaves an untracked process running.
    # Best-effort — if the signal doesn't land, the pid is named so the user
    # can finish the job by hand.
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    raise DaemonError(_startup_failure_message(
        f"The dashboard did not start within {timeout}s and was sent "
        f"SIGTERM (pid {pid})."))


def _startup_failure_message(headline: str) -> str:
    """Compose a start-failure message: what happened, plus the log tail."""
    detail = tail_log()
    return (f"{headline}\n"
            + (f"Last lines of {log_file_path()}:\n{detail}" if detail
               else f"No output in {log_file_path()}."))


def _bound_port(pid: int, host: str, port: int, log_offset: int = 0) -> int | None:
    """The port the child is serving, or None if it is not serving yet.

    With --port 0 the child picks an ephemeral port and prints it in its
    startup banner, so the banner is the only way to learn it. `log_offset`
    restricts that search to bytes written after this child was spawned —
    see `_log_size`.
    """
    if port:
        return port if port_listening(host, port) else None
    m = re.search(r"http://[^:]+:(\d+)", _read_log_since(log_offset))
    if not m:
        return None
    candidate = int(m.group(1))
    return candidate if port_listening(host, candidate) else None


def _this_project_id() -> str:
    """This checkout's project id for a URL, or "" when it cannot be read."""
    from .. import projects
    from ..core.utils import safe_call
    return safe_call(lambda: projects.project_id(cfg.project_root()),
                     default="", context="ui project id") or ""


def describe_state(state: dict, status: str, token: str | None = None,
                   project: str = "", served_by: str = "") -> dict:
    """Build the dict `ui start` / `ui status` report, including the URL.

    *project* is a project id to put in the URL's query. The dashboard reads
    `?project=` per tab, so this is what makes `exptrack ui start` in a second
    worktree open *that* worktree rather than whichever project the running
    dashboard happens to have been started from. *served_by* names that
    project, for a command that has to explain why it did not start anything.
    """
    from .handler import _get_auth_token

    if token is None:
        # A dashboard recorded user-globally carries the root it was started
        # from, and the token lives under *that* root (one dashboard, one
        # token). Reading this project's token file instead would print a URL
        # with a token the server has never heard of — a login overlay on a
        # link the command just promised would work. A recording with no root
        # (pre-2.0) is already about this project, hence nullcontext.
        recorded = state.get("root") or ""
        scope = (cfg.project_scope(Path(recorded)) if recorded
                 else contextlib.nullcontext())
        with scope:
            token = _get_auth_token()
    host, port = state.get("host", "127.0.0.1"), state.get("port")
    query = []
    if token:
        query.append(f"token={token}")
    if project:
        query.append(f"project={project}")
    url = f"http://{host}:{port}/" + ("?" + "&".join(query) if query else "")
    out = {"status": status, "pid": state.get("pid"), "host": host,
           "port": port, "url": url, "token": token,
           "version": state.get("version", "")}
    if served_by:
        out["served_by"] = served_by
    return out


# Port-to-pid lookups, tried in order. Both print pids to stdout,
# whitespace-separated. This is the *fallback* path — the state file is
# preferred — and exists for dashboards started before the state file did.
_PID_LOOKUPS = (
    ("fuser", lambda port: ["fuser", f"{port}/tcp"]),
    ("lsof", lambda port: ["lsof", "-ti", f"tcp:{port}"]),
)


def find_pids_on_port(port: int) -> list[int]:
    """Pids listening on *port*, using every available lookup tool.

    Every method is tried and the results unioned — never short-circuited on
    the first tool that returns something (even an empty something). The
    previous implementation (the old `cmd_ui_stop`) looped fuser then lsof but
    only `continue`d past a tool that was *missing*; if fuser existed and
    simply couldn't see the socket (a container with a restricted /proc,
    another user's process, a hardened kernel that hides other users'
    sockets), it printed a confident "nothing is listening" and lsof was
    never consulted — while the dashboard kept running. An empty answer from
    one tool means nothing; only the union of every tool's answer, still
    empty, means "not found this way".
    """
    found: set[int] = set()
    for _name, build in _PID_LOOKUPS:
        try:
            result = subprocess.run(build(port), capture_output=True,
                                     text=True, timeout=5)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        for tok in (result.stdout or "").split():
            if tok.isdigit():
                found.add(int(tok))
    return sorted(found)


def stop(force: bool = False, port: int | None = None,
         grace: float = 5.0) -> dict:
    """Stop the dashboard and verify the port was released.

    Returns {"stopped", "pids", "reason"}. Raises DaemonError if the port is
    still held afterwards — the command's success means *stopped*, not
    *signal delivered*. The old implementation printed "Sent SIGTERM" and
    exited without ever checking whether the process actually went away, so
    a slow or wedged process reported as a clean stop.

    Pid discovery prefers the state file (fast, exact) and falls back to
    find_pids_on_port's port scan (for dashboards started before the state
    file existed, or a state file that has gone stale) — every method is
    unioned, never treated as authoritative on its own.
    """
    # The user-global recording is the fallback, not an alternative: `ui stop`
    # run in a worktree that did not start the dashboard has no per-project
    # state, and on Windows find_pids_on_port returns [] (no fuser, no lsof),
    # so without this the shared dashboard could not be stopped from anywhere
    # but the checkout it was started in.
    state = read_state() or read_global_state() or {}
    host = state.get("host", "127.0.0.1")
    target_port = port or state.get("port") or 7331

    # Only seed from the state file when it actually names *this* port — a
    # dashboard recorded on 7331 must never be signalled by `ui stop --port
    # 8000` just because a state file happens to exist. `port is None` means
    # the caller didn't ask for a specific port, so the recorded one is fair
    # game (this is the "no --port" default-to-recorded case).
    state_matches_port = port is None or int(state.get("port", 0)) == target_port
    pids = ([int(state["pid"])]
            if state_matches_port and state.get("pid") and pid_alive(state["pid"])
            else [])
    pids += [p for p in find_pids_on_port(target_port) if p not in pids]

    if not pids:
        if not port_listening(host, target_port):
            # state_matches_port, not an unconditional clear: a state file
            # describing a *different* (still-live) dashboard is another
            # dashboard's only record — `ui stop --port 9999` finding
            # nothing on 9999 must not delete the state of the dashboard
            # actually running on, say, 7402. That was exactly the orphan
            # bug item #3 was supposed to close: #3 scoped which *pid* gets
            # signalled but left every success path below clearing the
            # state file unconditionally.
            if state_matches_port:
                clear_state()
            return {"stopped": False, "pids": [],
                    "reason": f"No dashboard is running on port {target_port}."}
        raise DaemonError(
            f"Port {target_port} is held by a process this user cannot see "
            f"(it may belong to another user). Nothing was stopped.")

    refused = _signal_all(pids, signal.SIGTERM)
    # A permission refusal on *every* candidate pid is unactionable: SIGKILL
    # would fail the same way (permission denied is not about signal type).
    # But a refusal alone doesn't mean the port is still held — a stale
    # state-file pid can be reused by an unrelated process owned by someone
    # else while the real dashboard already exited, in which case the port is
    # genuinely free and there's nothing left to stop. So this branch takes
    # exactly one port_listening check (not the full `grace` poll — waiting
    # buys nothing when force can't help either) before deciding: free means
    # the goal state already holds, held means we truly could not act.
    if refused and len(refused) == len(pids):
        if not port_listening(host, target_port):
            # See the comment on the first clear_state() above: only clear
            # the record this call actually targeted.
            if state_matches_port:
                clear_state()
            return {"stopped": True, "pids": pids,
                    "reason": "already stopped (port was already free)"}
        raise DaemonError(
            f"Could not signal {', '.join(str(p) for p in refused)} "
            f"(owned by another user). Nothing was stopped.")

    partial = (f"stopped, but could not signal "
               f"{', '.join(str(p) for p in refused)}" if refused else "")

    if _released(host, target_port, grace):
        # Same scoping as above: the pids just stopped may have come solely
        # from find_pids_on_port's port scan (state_matches_port False), in
        # which case the on-disk state describes an unrelated, still-live
        # dashboard and must be left alone.
        if state_matches_port:
            clear_state()
        _clear_global_state_for(pids)
        return {"stopped": True, "pids": pids, "reason": partial}

    if force:
        _signal_all(pids, getattr(signal, "SIGKILL", signal.SIGTERM))
        if _released(host, target_port, grace):
            if state_matches_port:
                clear_state()
            _clear_global_state_for(pids)
            return {"stopped": True, "pids": pids,
                    "reason": "killed" + (f"; {partial}" if partial else "")}

    hint = "" if force else "\nRetry with: exptrack ui stop --force"
    owner = (f"\nCould not signal {', '.join(str(p) for p in refused)} "
             f"(owned by another user)." if refused else "")
    raise DaemonError(
        f"Port {target_port} is still held after stopping "
        f"{', '.join(str(p) for p in pids)}.{owner}{hint}")


def _signal_all(pids: list[int], sig) -> list[int]:
    """Signal each pid. Returns the pids that could not be signalled."""
    refused = []
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass  # already gone, which is the outcome we wanted
        except (PermissionError, OSError):
            refused.append(pid)
    return refused


def _released(host: str, port: int, grace: float) -> bool:
    """Poll until nothing is listening on *port*, up to *grace* seconds."""
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not port_listening(host, port):
            return True
        time.sleep(_POLL_INTERVAL)
    return not port_listening(host, port)
