"""
exptrack/dashboard/app.py — Web dashboard entry point (stdlib only, no Flask needed)

Usage: python -m exptrack.dashboard.app [port]
       exptrack ui [--port 7331]

Running this module directly (or `exptrack ui` with no subcommand) is a
foreground process and dies on SSH disconnect (default SIGHUP behaviour).
For persistence, use `exptrack ui start` instead — it spawns the dashboard
detached and survives the terminal closing; `exptrack ui stop`/`ui status`
manage it from there. The foreground mode above remains for anyone who wants
to run it under their own supervisor (tmux, screen, systemd, nohup).
"""
import errno
import html
import os
import secrets
import socketserver
import sys
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

from .. import config as cfg
from .handler import (
    DashboardHandler,
    _get_auth_token,
    set_auth_disabled,
    set_session_token,
)

# Connections the kernel may hold before the server accepts them. The page's
# boot fires ~8 API calls at once on top of the shell + CSS/JS bundles + the
# vendored Chart.js, so the stdlib default of 5 is below a single page load.
_REQUEST_QUEUE_SIZE = 64


class DashboardServer(ThreadingHTTPServer):
    """Threaded HTTP server for the dashboard.

    Threading is not an optimization here, it is a correctness requirement.
    The stdlib ``HTTPServer`` accepts one connection, then blocks in
    ``readline()`` until that client sends a request line. A connection that
    is merely *open* — not yet sending — therefore stalls every other request
    for as long as it stays quiet, and one that never sends stalls them
    forever. Locally this is invisible: the browser connects and writes the
    request in the same instant. Through a remote tunnel (ssh -L, VS Code port
    forwarding, cloudflared) it is the normal case — those relays pool and
    pre-open TCP connections to the local port and forward the bytes a
    round-trip later, so an idle pooled socket deadlocked the whole dashboard
    and every fetch died as a bare "NetworkError" in the browser.

    ``daemon_threads`` keeps Ctrl+C immediate: an in-flight request never
    holds the process open.
    """

    daemon_threads = True
    request_queue_size = _REQUEST_QUEUE_SIZE

    def server_bind(self):
        """Bind the socket without the stdlib's reverse-DNS lookup.

        ``HTTPServer.server_bind`` sets ``server_name`` from
        ``socket.getfqdn(host)``, which is a *reverse* lookup: on a machine
        whose resolver is slow to answer for a loopback address — an mDNS
        query with no responder on a CI runner is the usual case — it blocks
        for tens of seconds. That the socket is already bound when it runs is
        what makes the symptom so confusing: the port is listening and the
        process is alive, but the startup banner is printed only after this
        constructor returns, and `ui start` learns an ephemeral port by
        parsing that banner. So a dashboard that is in fact serving reports
        "did not start within 10.0s" and gets SIGTERMed, with nothing in the
        log but the lines printed before the bind.

        Nothing here reads ``server_name`` — it exists for CGI's SERVER_NAME,
        and this server runs no CGI — so the host as given is a truthful value
        and the lookup buys nothing. Host-header checking is a separate,
        explicit allow-list (``allowed_host``), never this field.
        """
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port

    def process_request_thread(self, request, client_address):
        """Serve one connection, then drop this thread's SQLite connection.

        ``core.db.get_db()`` caches per *thread* (``threading.local``), so with
        a thread per connection every request would otherwise leave an open
        sqlite3 connection behind and the dashboard would leak file
        descriptors for as long as it runs.
        """
        try:
            super().process_request_thread(request, client_address)
        finally:
            try:
                from exptrack.core.db import close_db
                # sweep=False: the orphan scan is anti-join COUNTs over
                # params/metrics/timeline, far too expensive to repeat on
                # every closed connection. The CLI-exit close and
                # `exptrack clean` still sweep.
                # checkpoint=False: close_db's TRUNCATE checkpoint waits on
                # any open writer (up to busy_timeout, 5s) — a live training
                # run stalled every request here. The handler already does a
                # non-blocking PASSIVE checkpoint after each write.
                close_db(sweep=False, checkpoint=False)
            except Exception:
                pass  # never let cleanup break a served request


def _allowed_host_for_bind(host: str) -> str:
    """Map a bind address to the handler's Host-check policy.

    A wildcard bind (0.0.0.0/::/blank) means clients arrive under the
    machine's real name or IP — unpredictable here — so "*" tells the
    handler to accept any Host: the user explicitly opted into network
    exposure. Specific binds stay strict (that host only, plus loopback).
    """
    bind = host.strip("[]").lower()
    return "*" if bind in ("0.0.0.0", "::", "") else bind


def _warn_if_token_in_config() -> None:
    """Flag a legacy ``dashboard_token`` sitting in the committable config.json.

    Older versions persisted the token there, and `exptrack init` both tells
    users config.json is safe to commit and leaves it out of .gitignore — so an
    existing setup may already have an auth secret staged for publication. The
    token is still honored (nothing breaks), but say so loudly once per start.
    """
    try:
        from exptrack import config as _cfg
        if _cfg.load().get("dashboard_token"):
            print("[exptrack] WARNING: dashboard_token is stored in "
                  ".exptrack/config.json, which is committable and not "
                  "gitignored. Move it with `exptrack ui --token <token>` "
                  "(writes .exptrack/dashboard_token, gitignored) or drop it "
                  "with `exptrack ui --clear-token`.", file=sys.stderr)
    except Exception:
        pass


def warn_if_exposed(host: str, no_auth: bool) -> None:
    """Warn when the dashboard is reachable beyond this machine.

    This used to fire only alongside --no-auth. Accidentally binding 0.0.0.0
    is a far more realistic way to become exposed than anyone attacking the
    token, so any non-loopback bind says so.
    """
    if host in ("127.0.0.1", "localhost", "::1"):
        return
    where = "every interface" if host in ("0.0.0.0", "::", "") else host
    print(f"[exptrack] WARNING: bound to {host} — the dashboard is reachable "
          f"from the network on {where}.", file=sys.stderr)
    if no_auth:
        print("[exptrack] WARNING: --no-auth is set, so it is reachable with "
              "no authentication at all.", file=sys.stderr)


def resolve_startup_token(no_auth: bool) -> str:
    """Return the token this server should use, persisting a generated one.

    Previously a generated token lived only in memory, so every restart minted
    a new one and invalidated the token the browser had stored — the open tab
    dropped to the login overlay and the user had to fetch the new token from
    the terminal. Persisting it to the (already gitignored, already
    first-in-precedence) .exptrack/dashboard_token file is the whole fix.

    A token that came from the environment is *not* persisted: it is the
    caller's to manage, and writing it to disk would be a surprise.

    This also decides whether the handler checks tokens at all: under
    --no-auth a token saved by an earlier start must not apply.
    """
    set_auth_disabled(no_auth)
    if no_auth:
        return ""
    token = _get_auth_token()
    if token:
        return token
    token = secrets.token_urlsafe(32)
    try:
        cfg.write_token(token)
    except OSError as e:
        # A read-only project directory must not stop the dashboard starting;
        # fall back to the old in-memory behaviour and say why.
        print(f"[exptrack] WARNING: could not persist the dashboard token "
              f"({e}); it will change on restart.", file=sys.stderr)
        set_session_token(token)
    return token


_WILDCARD_HOSTS = {"0.0.0.0", "::", ""}


def browser_url(host: str, port: int, token: str, project: str = "") -> str:
    """The URL a browser on *this* machine should open for a bound server.

    A wildcard bind is reachable on loopback, and ``http://0.0.0.0:7331`` is
    not a usable address on Windows.
    """
    h = "127.0.0.1" if host in _WILDCARD_HOSTS else host
    if ":" in h:
        h = f"[{h}]"
    query = [f"token={token}"] if token else []
    if project:
        # A tab opened without `?project=` shows the browser's remembered
        # project, not the one `exptrack ui` was run in.
        query.append(f"project={project}")
    return f"http://{h}:{port}/" + ("?" + "&".join(query) if query else "")


def _no_display() -> str:
    """Why no browser should be opened here, or '' when one can be."""
    if any(os.environ.get(v) for v in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")):
        return "this is an SSH session"
    if sys.platform.startswith("linux") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "there is no display"
    return ""


def _redirect_page(url: str) -> Path:
    """A 0600 page in ``~/.exptrack/`` that forwards the browser to *url*.

    ``webbrowser.open(url)`` starts the browser with the URL as an argument,
    and a process's arguments are readable by every user on the machine — so
    handing it a tokened URL publishes the token for as long as the browser
    runs. The browser is handed this file's path instead (Jupyter's approach).
    Rewritten on every open, so it holds only the current token.
    """
    page = cfg.user_dir() / "dashboard_open.html"
    target = html.escape(url, quote=True)
    body = ('<!doctype html><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0;url={target}">'
            '<title>exptrack</title>'
            f'<p>Opening the exptrack dashboard: <a href="{target}">{target}</a></p>')
    try:
        page.unlink()          # O_NOFOLLOW refuses a planted symlink; an old
    except FileNotFoundError:  # page of ours is simply replaced
        pass
    fd = cfg.open_private(page, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    return page


def open_in_browser(url: str) -> bool:
    """Open the dashboard in the default browser, as `jupyter lab` does.

    Returns whether a browser was asked to open it. Never raises: the URL is
    printed either way, and failing to open a tab is not failing to serve.
    Over SSH or on a display-less Linux box nothing is opened — `webbrowser`
    would pick a text-mode browser there and take over the terminal.
    """
    reason = _no_display()
    if reason:
        print(f"[exptrack] Not opening a browser: {reason}. Open the URL above.",
              file=sys.stderr)
        return False
    try:
        target = url
        if "token=" in url:
            target = _redirect_page(url).as_uri()
        return bool(webbrowser.open(target, new=2))
    except Exception as e:  # webbrowser raises a zoo of errors across platforms
        print(f"[exptrack] Could not open a browser ({e}). Open the URL above.",
              file=sys.stderr)
        return False


def main(host: str = "127.0.0.1", port: int = 7331, no_auth: bool = False,
         open_browser: bool = False):
    # Parse CLI args when run directly
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--host" and i + 1 < len(sys.argv):
                host = sys.argv[i + 1]
            elif arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
            elif arg == "--no-auth":
                no_auth = True
            elif arg.isdigit():
                port = int(arg)

    _warn_if_token_in_config()

    perm_warning = cfg.warn_if_world_readable()
    if perm_warning:
        print(f"[exptrack] WARNING: {perm_warning}", file=sys.stderr)

    token = resolve_startup_token(no_auth)

    try:
        server = DashboardServer((host, port), DashboardHandler)
        # Allow the bound host through the DNS-rebinding Host-header check
        # (localhost/127.0.0.1/::1 are always allowed) so non-local binds work;
        # wildcard binds accept any Host (see _allowed_host_for_bind).
        server.allowed_host = _allowed_host_for_bind(host)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(f"[exptrack] Port {port} is already in use. A previous "
                  f"dashboard may still be running.", file=sys.stderr)
            print(f"[exptrack]   List it:  lsof -i :{port}", file=sys.stderr)
            print(f"[exptrack]   Kill it:  exptrack ui stop --port {port}",
                  file=sys.stderr)
            sys.exit(1)
        raise

    # Print the *bound* port, not the requested one: --port 0 asks the OS for
    # an ephemeral port, and daemon.spawn_detached's readiness poll parses
    # this exact banner line out of the log to learn which port a detached
    # child actually landed on.
    bound_port = server.server_address[1]
    url = f"http://{host}:{bound_port}"
    if token:
        print(f"[exptrack] Dashboard: {url}/?token={token}", file=sys.stderr)
    else:
        print(f"[exptrack] Dashboard: {url}  (auth disabled)", file=sys.stderr)

    warn_if_exposed(host, no_auth)

    # After the bind, so the page never races a server that is not listening.
    # Off by default here: the detached child `ui start` spawns runs this same
    # main(), and the parent opens the tab once the child reports ready.
    if open_browser:
        from .. import projects
        from ..core.utils import safe_call
        pid = safe_call(lambda: projects.project_id(cfg.project_root()),
                        default="", context="ui project id") or ""
        open_in_browser(browser_url(host, bound_port, token, pid))

    print("[exptrack] Press Ctrl+C to stop", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[exptrack] Dashboard stopped.", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()
