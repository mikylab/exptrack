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
from http.server import HTTPServer

from .handler import DashboardHandler, _get_auth_token, set_session_token


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
        server = HTTPServer((host, port), DashboardHandler)
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
