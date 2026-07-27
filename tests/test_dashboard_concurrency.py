"""The dashboard must serve requests concurrently — over a real socket.

The regression these guard: the dashboard used to run on the stdlib
``HTTPServer``, which is single-threaded. It accepts one connection and then
blocks in ``readline()`` until that client sends a request line, so a
connection that is merely *open* stalls every other request for as long as it
stays quiet — forever, if it never sends.

That is invisible on localhost (the browser connects and writes in the same
instant) and the normal case through a remote tunnel: ssh -L, VS Code port
forwarding and cloudflared all pool and pre-open TCP connections to the
forwarded port and relay the bytes a round-trip later. The symptom was every
dashboard fetch dying as a bare "NetworkError" in the browser with no server
log, because nothing was ever written back.

These run a real server rather than driving do_GET directly: the failure is in
the accept loop, which a stubbed handler harness never exercises.
"""
from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from exptrack.dashboard.app import DashboardServer
from exptrack.dashboard.handler import DashboardHandler


@pytest.fixture
def live_server(tmp_project):
    """Run a real dashboard on an ephemeral port; yield its base URL."""
    server = DashboardServer(("127.0.0.1", 0), DashboardHandler)
    server.allowed_host = "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


# ── the tunnel case ─────────────────────────────────────────────────────────

def test_idle_connection_does_not_block_requests(live_server):
    """An open-but-silent socket must not stall the server.

    This is the exact shape of a tunnel's pooled connection, and the whole
    reason the dashboard is threaded. On the old single-threaded server this
    request never returned at all.
    """
    host, port = "127.0.0.1", int(live_server.rsplit(":", 1)[1])
    idle = socket.create_connection((host, port))
    try:
        time.sleep(0.2)  # let the server accept it
        status, _ = _get(live_server + "/api/experiments?limit=1000&offset=0",
                         timeout=5)
        assert status == 200
    finally:
        idle.close()


def test_many_idle_connections_do_not_block_requests(live_server):
    """A tunnel opens a *pool*, not a single spare socket."""
    host, port = "127.0.0.1", int(live_server.rsplit(":", 1)[1])
    idles = [socket.create_connection((host, port)) for _ in range(8)]
    try:
        time.sleep(0.2)
        status, _ = _get(live_server + "/api/stats", timeout=5)
        assert status == 200
    finally:
        for s in idles:
            s.close()


def test_slow_client_does_not_block_requests(live_server):
    """A client trickling its request line (tunnel round-trip) must not
    serialize everyone behind it."""
    host, port = "127.0.0.1", int(live_server.rsplit(":", 1)[1])
    slow = socket.create_connection((host, port))

    def trickle():
        for ch in b"GET /api/stats HTTP/1.0\r\n\r\n":
            try:
                slow.sendall(bytes([ch]))
            except OSError:
                return
            time.sleep(0.05)

    t = threading.Thread(target=trickle, daemon=True)
    t.start()
    try:
        time.sleep(0.15)  # slow client is mid-request
        started = time.time()
        status, _ = _get(live_server + "/api/stats", timeout=5)
        elapsed = time.time() - started
        assert status == 200
        # Served on its own thread, so it must not wait out the trickle
        # (~1.2s of sends). Generous bound — this is about not serializing.
        assert elapsed < 1.0, f"request waited {elapsed:.2f}s behind a slow client"
    finally:
        t.join(timeout=3)
        slow.close()


# ── the page's boot burst ───────────────────────────────────────────────────

_BOOT_PATHS = [
    "/api/config/timezone",
    "/api/config/metrics",
    "/api/config/capture",
    "/api/all-tags",
    "/api/all-studies",
    "/api/stats",
    "/api/experiments?limit=1000&offset=0",
    "/static/dashboard.js",
]


def test_boot_burst_all_succeed(live_server):
    """The page fires ~8 requests at once on load; none may be dropped.

    The stdlib listen backlog default is 5, below a single page load.
    """
    results: dict[str, object] = {}

    def go(path):
        try:
            results[path] = _get(live_server + path, timeout=15)[0]
        except (urllib.error.URLError, OSError) as e:
            results[path] = f"FAILED: {type(e).__name__}: {e}"

    threads = [threading.Thread(target=go, args=(p,)) for p in _BOOT_PATHS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert results == {p: 200 for p in _BOOT_PATHS}


# ── server configuration ────────────────────────────────────────────────────

def test_server_is_threaded_with_a_usable_backlog():
    """Guard the two settings the fix rests on, so a future edit back to a
    plain HTTPServer fails here rather than only through a tunnel."""
    from socketserver import ThreadingMixIn

    assert issubclass(DashboardServer, ThreadingMixIn)
    assert DashboardServer.daemon_threads is True
    assert DashboardServer.request_queue_size >= len(_BOOT_PATHS)


def test_handler_reaps_idle_connections():
    """A pre-opened socket that never sends must not park a thread forever."""
    assert DashboardHandler.timeout is not None
    assert 0 < DashboardHandler.timeout <= 120


def test_request_thread_closes_its_db_connection(live_server, monkeypatch):
    """get_db() caches per thread, so a thread-per-connection server leaks an
    sqlite connection per request unless the thread drops it on the way out."""
    closed = []
    from exptrack.core import db as _db

    real_close = _db.close_db
    monkeypatch.setattr(_db, "close_db",
                        lambda sweep=True: (closed.append(sweep), real_close(sweep))[1])

    _get(live_server + "/api/stats")
    time.sleep(0.3)  # the close happens after the response is written

    assert closed, "request thread did not close its thread-local DB connection"
    assert closed[0] is False, "per-request close must skip the orphan sweep"
