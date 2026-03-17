"""
exptrack/dashboard/app.py — Web dashboard entry point (stdlib only, no Flask needed)

Usage: python -m exptrack.dashboard.app [port]
       exptrack ui [--port 7331]
"""
import sys
from http.server import HTTPServer

from .handler import DashboardHandler


def main(host: str = "127.0.0.1", port: int = 7331):
    # Parse CLI args when run directly
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--host" and i + 1 < len(sys.argv):
                host = sys.argv[i + 1]
            elif arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
            elif arg.isdigit():
                port = int(arg)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[exptrack] WARNING: Binding to {host} — the dashboard will be accessible "
              f"from the network. There is no authentication.", file=sys.stderr)
    server = HTTPServer((host, port), DashboardHandler)
    print(f"[exptrack] Dashboard running at http://{host}:{port}", file=sys.stderr)
    print("[exptrack] Press Ctrl+C to stop", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[exptrack] Dashboard stopped.", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()
