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
    # Warm the server first. This is the only test here that asserts on
    # elapsed time, and the project's DB is created lazily by the first
    # request that touches it: ~100 DDL statements plus the WAL switch, all
    # fsync-bound (measured ~67ms locally against ~0.7ms for a warm
    # per-thread open). Timed cold, the measurement is dominated by one-time
    # setup rather than by the slow client, which is what it claims to
    # measure — and on a loaded CI runner that setup alone blew the bound.
    _get(live_server + "/api/stats")

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

    def _spy(sweep=True, checkpoint=True):
        closed.append((sweep, checkpoint))
        return real_close(sweep, checkpoint)

    monkeypatch.setattr(_db, "close_db", _spy)

    _get(live_server + "/api/stats")
    time.sleep(0.3)  # the close happens after the response is written

    assert closed, "request thread did not close its thread-local DB connection"
    assert closed[0][0] is False, "per-request close must skip the orphan sweep"
    # A TRUNCATE checkpoint waits on any open writer (up to busy_timeout), so
    # a live training run would stall every request here.
    assert closed[0][1] is False, "per-request close must skip the WAL checkpoint"


# ── WAL checkpointing must never wait on the user's training loop ────────────

def test_wal_checkpoint_is_passive():
    """TRUNCATE/RESTART invoke SQLite's busy handler; PASSIVE does not.

    A live run holds a write transaction open between metric commits
    (metric_commit_interval_ms), so a blocking checkpoint on the request path
    stalls the UI for up to busy_timeout — 5s — per request.
    """
    executed = []

    class _Conn:
        def execute(self, sql):
            executed.append(sql)

    DashboardHandler._wal_checkpoint(_Conn())

    assert executed == ["PRAGMA wal_checkpoint(PASSIVE)"]


def test_get_requests_do_not_checkpoint(live_server, monkeypatch):
    """A GET never appends to the WAL, so there is nothing to reclaim."""
    calls = []
    monkeypatch.setattr(DashboardHandler, "_wal_checkpoint",
                        staticmethod(lambda conn: calls.append(1)))

    _get(live_server + "/api/stats")
    _get(live_server + "/api/experiments?limit=10&offset=0")
    time.sleep(0.2)

    assert calls == []


def test_reads_are_not_blocked_by_an_open_writer(live_server, tmp_project):
    """The regression: a request stalled behind a training run's open write.

    With the old TRUNCATE checkpoints (one before GET dispatch, one in the
    per-request close_db) this waited on the writer up to busy_timeout.
    """
    import sqlite3

    from exptrack import config as cfg
    from exptrack.core.db import get_db

    get_db()  # materialize the schema before the writer opens its own handle
    db_path = str(cfg.project_root() / cfg.load().get("db", ".exptrack/experiments.db"))
    holding = threading.Event()
    release = threading.Event()

    def _writer():
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO metrics (exp_id,key,value,step,ts,source) "
                     "VALUES ('x','loss',1.0,1,1.0,'auto')")
        holding.set()
        release.wait(timeout=10)
        conn.rollback()
        conn.close()

    t = threading.Thread(target=_writer, daemon=True)
    t.start()
    try:
        assert holding.wait(timeout=5)
        start = time.monotonic()
        status, _ = _get(live_server + "/api/stats", timeout=10)
        elapsed = time.monotonic() - start
        assert status == 200
        assert elapsed < 2.0, f"read blocked behind the writer for {elapsed:.2f}s"
    finally:
        release.set()
        t.join(timeout=5)


# ── keep-alive ───────────────────────────────────────────────────────────────

def _raw_request(host, port, lines, sock=None, read_bytes=65536):
    """Send a raw request on (optionally) an existing socket; return the bytes."""
    s = sock or socket.create_connection((host, port), timeout=5)
    s.sendall("".join(lines).encode())
    time.sleep(0.3)
    return s.recv(read_bytes), s


def test_connection_is_reused_across_requests(live_server):
    """HTTP/1.0 meant a fresh TCP connection per request — a setup round trip
    each time, which is what shows through an ssh tunnel."""
    host, port = "127.0.0.1", int(live_server.rsplit(":", 1)[1])
    s = socket.create_connection((host, port), timeout=5)
    try:
        first, _ = _raw_request(host, port,
                                ["GET /api/ping HTTP/1.1\r\n",
                                 f"Host: 127.0.0.1:{port}\r\n\r\n"], sock=s)
        assert first.startswith(b"HTTP/1.1 200"), first[:80]
        assert b"Connection: close" not in first

        # The same socket must still answer.
        second, _ = _raw_request(host, port,
                                 ["GET /api/ping HTTP/1.1\r\n",
                                  f"Host: 127.0.0.1:{port}\r\n\r\n"], sock=s)
        assert second.startswith(b"HTTP/1.1 200"), second[:80]
    finally:
        s.close()


def test_oversized_post_closes_instead_of_poisoning_the_connection(live_server):
    """The 413 guard answers without draining the body.

    Under keep-alive a reused connection would then read that undrained body as
    the next request line, so this response has to end the connection.
    """
    host, port = "127.0.0.1", int(live_server.rsplit(":", 1)[1])
    resp, s = _raw_request(host, port, [
        "POST /api/clean-db HTTP/1.1\r\n",
        f"Host: 127.0.0.1:{port}\r\n",
        "Content-Type: application/json\r\n",
        f"Content-Length: {11 * 1024 * 1024}\r\n\r\n",
    ])
    try:
        assert resp.startswith(b"HTTP/1.1 413"), resp[:80]
        assert b"Connection: close" in resp
    finally:
        s.close()
