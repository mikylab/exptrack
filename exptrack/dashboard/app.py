"""
exptrack/dashboard/app.py — Web dashboard entry point (stdlib only, no Flask needed)

Usage: python -m exptrack.dashboard.app [port]
       exptrack ui [--port 7331]

The dashboard is a foreground process and dies on SSH disconnect (default
SIGHUP behaviour). Use `nohup exptrack ui &`, tmux, or screen for persistence.
"""
import errno
import secrets
import sys
from http.server import ThreadingHTTPServer

from .handler import DashboardHandler, _get_auth_token, set_session_token

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
                close_db(sweep=False)
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


def main(host: str = "127.0.0.1", port: int = 7331, no_auth: bool = False):
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

    token = _get_auth_token()
    if not token and not no_auth:
        token = secrets.token_urlsafe(32)
        set_session_token(token)

    url = f"http://{host}:{port}"
    if token:
        print(f"[exptrack] Dashboard: {url}/?token={token}", file=sys.stderr)
    else:
        print(f"[exptrack] Dashboard: {url}  (auth disabled)", file=sys.stderr)
        if host not in ("127.0.0.1", "localhost", "::1"):
            print(f"[exptrack] WARNING: Binding to {host} with --no-auth -- "
                  f"the dashboard is reachable from the network with no authentication.",
                  file=sys.stderr)

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
            print(f"[exptrack]   Kill it:  exptrack ui-stop --port {port}",
                  file=sys.stderr)
            sys.exit(1)
        raise

    print("[exptrack] Press Ctrl+C to stop", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[exptrack] Dashboard stopped.", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()
