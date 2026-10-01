"""Per-request project activation, over a real socket.

The dangerous failure here is silent: a pooled thread that keeps a project
bound serves the NEXT request from the wrong database, with no error anywhere.
These tests exist for that, and for the rule that an unknown id must never
fall back to the default project — serving data from a project other than the
one asked for looks like success, and a decision then gets made on the wrong
numbers.

Everything runs over a real socket rather than against do_GET with a stubbed
transport, because the property under test is about what a *served request*
leaves behind on the thread that served it. A harness that calls the handler
directly cannot see that, and the reset could be deleted without a failure.

These tests deliberately do NOT use the ``tmp_project`` fixture: it
monkeypatches ``config.project_root`` with a constant lambda, which pins every
request to one root and would make an activation test pass no matter what the
handler did. They build real project roots and leave resolution real.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer

import pytest

from exptrack import config as cfg
from exptrack import projects
from exptrack.core import db as _db
from exptrack.core.db import _SCHEMA_VERSION, close_db, get_db
from exptrack.dashboard.handler import DashboardHandler


def _build_project(root, runs: int):
    """A real exptrack project at *root* holding *runs* experiments.

    Built through ``get_db()`` under an activation scope so the database gets
    the full schema and the current stamp — a hand-stamped empty file probes
    as OK but has no tables, which would fail every read for the wrong reason.
    The run count is the tell the activation tests assert on: each project
    must answer with a number no other project could produce.
    """
    (root / ".exptrack").mkdir(parents=True, exist_ok=True)
    with cfg.project_scope(root):
        conn = get_db()
        for i in range(runs):
            conn.execute(
                "INSERT INTO experiments (id, name, status, created_at, updated_at) "
                "VALUES (?, ?, 'done', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                (f"{root.name}{i:04d}", f"{root.name}-run-{i}"))
        conn.commit()
        close_db()
    return root


def _stamp_project(root, stamp):
    """A project whose database carries *stamp* and nothing else."""
    (root / ".exptrack").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(root / ".exptrack" / "experiments.db"))
    conn.execute(f"PRAGMA user_version = {stamp}")
    conn.commit()
    conn.close()
    return root


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Two registered projects with different contents, plus a temp home.

    ``default`` is what cwd-based resolution finds when no header is sent;
    ``other`` is what a header can switch to. Their run counts differ so a
    leaked binding produces a wrong number rather than an equal one.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    default_root = _build_project(tmp_path / "default", runs=1)
    other_root = _build_project(tmp_path / "other", runs=3)
    projects.register(default_root, "default")
    projects.register(other_root, "other")

    # Real resolution, only pre-seeded: project_root() consults the thread
    # override first and this module global second, which is exactly the
    # order under test.
    monkeypatch.setattr(cfg, "_root_cache", default_root)
    monkeypatch.setattr(cfg, "_cache", None)
    monkeypatch.chdir(default_root)
    _db._local.conn = None
    _db._local.db_path = None
    # The discovery cache is process-wide, so it outlives a test. Clearing it
    # at both ends keeps one test's pinned TTL from reaching another.
    projects.invalidate_discovery_cache()

    yield {"default": default_root, "other": other_root}

    projects.invalidate_discovery_cache()
    try:
        close_db()
    except Exception:
        pass
    cfg.reset_project()


@pytest.fixture()
def live(env):
    """A real dashboard on an ephemeral port; yields (base_url, env)."""
    server = HTTPServer(("127.0.0.1", 0), DashboardHandler)
    server.allowed_host = "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", env
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(base, path, project=None):
    """(status, body bytes) for a GET, without raising on 4xx/5xx."""
    headers = {}
    if project is not None:
        headers["X-Exptrack-Project"] = project
    req = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _get_json(base, path, project=None):
    status, body = _request(base, path, project)
    assert status == 200, (status, body[:400])
    return json.loads(body)


def _post(base, path, payload, project=None):
    """(status, body bytes) for a JSON POST, without raising on 4xx/5xx."""
    headers = {"Content-Type": "application/json"}
    if project is not None:
        headers["X-Exptrack-Project"] = project
    req = urllib.request.Request(base + path, headers=headers,
                                 data=json.dumps(payload).encode("utf-8"),
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _tags_of(root, exp_id):
    """Read a run's tags straight out of *root*'s database.

    Deliberately its own connection rather than anything the request path
    touched: the question these tests ask is which file on disk the write
    landed in, and asking through the same resolution layer under test would
    answer with whatever that layer believes.
    """
    conn = sqlite3.connect(str(root / ".exptrack" / "experiments.db"))
    try:
        row = conn.execute("SELECT tags FROM experiments WHERE id = ?",
                           (exp_id,)).fetchone()
    finally:
        conn.close()
    return json.loads((row[0] if row else None) or "[]")


# ── /api/projects ───────────────────────────────────────────────────────────

def test_api_projects_lists_the_discovered_projects(live):
    base, env = live
    payload = _get_json(base, "/api/projects")
    assert "projects" in payload and "current" in payload
    by_id = {p["id"]: p for p in payload["projects"]}
    assert projects.project_id(env["default"]) in by_id
    assert projects.project_id(env["other"]) in by_id


def test_api_projects_names_the_active_one_as_current(live):
    base, env = live
    assert _get_json(base, "/api/projects")["current"] == \
        projects.project_id(env["default"])
    # ...and follows the header, or the switcher would highlight the wrong row.
    other_id = projects.project_id(env["other"])
    assert _get_json(base, "/api/projects", project=other_id)["current"] == other_id


def test_api_projects_answers_even_with_an_unknown_project_id(live):
    """/api/projects is the switcher's own recovery surface: a stored id that
    no longer names anything must not take this call down with every other
    one, or there is no way back to a working project short of clearing
    localStorage by hand. It must not silently claim the unknown id either —
    `current` falls back to the default project's id, not the header's."""
    base, env = live
    status, body = _request(base, "/api/projects", project="0" * 16)
    assert status == 200
    payload = json.loads(body)
    assert payload["current"] == projects.project_id(env["default"])
    by_id = {p["id"]: p for p in payload["projects"]}
    assert projects.project_id(env["other"]) in by_id


def test_api_projects_answers_even_with_a_skewed_project_id(live, tmp_path):
    """Same recovery guarantee as the unknown-id case, for a stored id that
    has gone stale/schema-skewed since it was picked — the other refusal
    reason every other route gives for a bad id (409, not 400)."""
    base, env = live
    old = _stamp_project(tmp_path / "old", _SCHEMA_VERSION - 1)
    projects.register(old, "old")
    old_id = projects.project_id(old)
    status, body = _request(base, "/api/projects", project=old_id)
    assert status == 200
    payload = json.loads(body)
    # The skewed id is listed with its reason, never silently adopted as current.
    assert payload["current"] == projects.project_id(env["default"])
    by_id = {p["id"]: p for p in payload["projects"]}
    assert by_id[old_id]["status"] != "ok"
    assert by_id[old_id]["message"]


# ── activation ──────────────────────────────────────────────────────────────

def test_a_request_without_a_project_header_uses_the_default(live):
    base, _ = live
    payload = _get_json(base, "/api/stats")
    assert "version" in payload
    assert payload["total"] == 1


def test_a_project_header_serves_that_project(live):
    base, env = live
    payload = _get_json(base, "/api/stats",
                        project=projects.project_id(env["other"]))
    assert payload["total"] == 3


def test_the_thread_is_reset_after_each_request(live):
    """A pooled thread that kept a project bound would serve the next request
    from the wrong database, with no error to notice.

    Asserted on the *data*: the second request carries no header, so it must
    come back with the default project's single run. Checking
    ``active_project()`` in the test's own thread would prove nothing — that
    thread never activated anything, so it passes with the reset deleted.
    """
    base, env = live
    assert _get_json(base, "/api/stats",
                     project=projects.project_id(env["other"]))["total"] == 3
    assert _get_json(base, "/api/stats")["total"] == 1


def test_a_refused_request_also_resets_the_thread(live):
    """The refusal path returns early, so the reset cannot live at the end of
    a handler — a 400 must leave the thread as clean as a 200 does.

    The binding has to come from the request *before* the refusal: a rejected
    id never activates anything, so a 400-then-default pair alone would pass
    with the reset deleted. So: bind to `other`, get refused, then ask with no
    header and require the default project's data.
    """
    base, env = live
    assert _get_json(base, "/api/stats",
                     project=projects.project_id(env["other"]))["total"] == 3
    assert _request(base, "/api/stats", project="0" * 16)[0] == 400
    assert _get_json(base, "/api/stats")["total"] == 1


# ── refusals ────────────────────────────────────────────────────────────────

def test_unknown_project_id_is_rejected(live):
    base, _ = live
    assert _request(base, "/api/stats", project="0" * 16)[0] == 400


def test_unknown_id_does_not_fall_back_to_the_default(live):
    """A silent fallback serves the wrong project's numbers, which is worse
    than an error because it looks like it worked."""
    status, body = _request(base=live[0], path="/api/stats",
                            project="0" * 16)
    assert status == 400
    # None of the default project's stats payload may appear in the response.
    assert b'"total"' not in body
    assert b'"version"' not in body


def test_a_filesystem_path_is_not_accepted_as_an_id(live, tmp_path):
    """An accepted path would let any request open a database anywhere."""
    base, env = live
    status, _ = _request(base, "/api/stats", project=str(env["other"]))
    assert status == 400
    assert _request(base, "/api/stats", project=str(tmp_path))[0] == 400


def test_a_skewed_project_is_refused_with_its_reason(live, tmp_path):
    """Opening it would migrate it behind the owner's back."""
    base, _ = live
    old = _stamp_project(tmp_path / "old", _SCHEMA_VERSION - 1)
    projects.register(old, "old")
    status, body = _request(base, "/api/stats",
                            project=projects.project_id(old))
    assert status == 409
    assert b"exptrack upgrade" in body


# ── POST goes through the same hook ─────────────────────────────────────────
# A *write* landing in the wrong project is the most destructive form of this
# task's failure mode, and every mutation plus the set-valued reads
# (/api/param-study, /api/multi-compare) goes through do_POST's activation.

def test_a_post_writes_to_the_project_it_names(live):
    base, env = live
    status, body = _post(base, "/api/experiment/other0000/tag", {"tag": "from-other"},
                         project=projects.project_id(env["other"]))
    assert status == 200 and json.loads(body).get("ok") is True
    assert _tags_of(env["other"], "other0000") == ["from-other"]
    # ...and nothing reached the project the server resolves by default.
    assert _tags_of(env["default"], "default0000") == []


def test_a_post_with_an_unknown_id_writes_nothing_anywhere(live):
    """The refusal has to happen before the body is even parsed — a write
    applied to the default project because its id was not recognised is the
    silent-corruption case, not an error case."""
    base, env = live
    status, _ = _post(base, "/api/experiment/other0000/tag", {"tag": "nope"},
                      project="0" * 16)
    assert status == 400
    assert _tags_of(env["other"], "other0000") == []
    assert _tags_of(env["default"], "default0000") == []


def test_ping_answers_even_with_an_unknown_project_id(live):
    """/api/ping is the liveness and readiness probe: daemon.py polls it to
    decide whether a dashboard is up, and the login overlay calls it before
    any project is known. A tab holding a since-forgotten id must not be able
    to make a running server look dead."""
    base, _ = live
    status, body = _request(base, "/api/ping", project="0" * 16)
    assert status == 200
    assert json.loads(body)["ok"] is True


def test_ping_says_whether_the_tabs_project_resolves(live, tmp_path):
    """The page awaits /api/ping before it loads anything, so ping is where it
    learns a stored id is dead — before firing eight loads that all 400 and
    leave an empty table under an error banner until /api/projects recovers."""
    base, env = live
    def state(project):
        return json.loads(_request(base, "/api/ping", project=project)[1]).get("project")
    assert state("0" * 16) == "unknown"
    assert state(projects.project_id(env["other"])) == "ok"
    old = _stamp_project(tmp_path / "old", _SCHEMA_VERSION - 1)
    projects.register(old, "old")
    projects.invalidate_discovery_cache()
    assert state(projects.project_id(old)) == "unavailable"


def test_ping_without_a_project_runs_no_discovery(live, monkeypatch):
    """daemon.py polls ping for readiness; that must not cost a discovery."""
    base, _ = live
    monkeypatch.setattr(projects, "discover_cached",
                        lambda *a, **k: pytest.fail("ping ran discovery"))
    status, body = _request(base, "/api/ping")
    assert status == 200 and json.loads(body) == {"ok": True}


def test_a_refused_project_is_answered_in_json(live, tmp_path):
    """api() reads every error body as JSON; an HTML error page reached the
    banner as "server returned 400 with an unreadable body" instead of the
    reason."""
    base, _ = live
    status, body = _request(base, "/api/stats", project="0" * 16)
    assert status == 400
    assert "Unknown project" in json.loads(body)["error"]
    old = _stamp_project(tmp_path / "old", _SCHEMA_VERSION - 1)
    projects.register(old, "old")
    projects.invalidate_discovery_cache()
    status, body = _request(base, "/api/stats", project=projects.project_id(old))
    assert status == 409
    assert "exptrack upgrade" in json.loads(body)["error"]


# ── discovery is cached on the request path ─────────────────────────────────

def test_resolving_an_id_does_not_spawn_git_per_request(live, monkeypatch):
    """The UI polls /api/metrics every 5s per live run per open tab, and every
    such request names a project — so id resolution must not cost a subprocess
    each time.

    The TTL is pinned well above any plausible run time: with the real 2s this
    would be an assertion about how fast the box is, and it would start failing
    (or passing) for reasons that have nothing to do with the cache.
    """
    base, env = live
    monkeypatch.setattr(projects, "_DISCOVERY_TTL_S", 3600.0)
    projects.invalidate_discovery_cache()
    calls = []
    real = projects._git_worktrees
    monkeypatch.setattr(projects, "_git_worktrees",
                        lambda root: calls.append(root) or real(root))

    other_id = projects.project_id(env["other"])
    for _ in range(3):
        assert _get_json(base, "/api/stats", project=other_id)["total"] == 3
    assert len(calls) == 1


def test_forgetting_a_project_takes_effect_immediately(live, monkeypatch):
    """The cache must never outlive a registry write made by this process:
    a dashboard that still serves a project the user just removed through it
    is a visible wrong answer, not merely a stale one.

    TTL pinned high, so a pass means `forget()` invalidated the cache and not
    that the entry happened to expire while the test ran.
    """
    base, env = live
    monkeypatch.setattr(projects, "_DISCOVERY_TTL_S", 3600.0)
    other_id = projects.project_id(env["other"])
    assert _get_json(base, "/api/stats", project=other_id)["total"] == 3
    projects.forget(str(env["other"]))
    assert _request(base, "/api/stats", project=other_id)[0] == 400


def test_the_project_list_itself_is_never_served_stale(live, monkeypatch):
    """A slightly slower switcher beats one that is wrong about which projects
    exist, so /api/projects reads through the cache.

    The new project is written straight into the registry rather than through
    `register()`, which would invalidate the cache and so prove nothing — this
    is the case of *another* process (an `exptrack init` in a second terminal)
    adding a project while this dashboard runs. The TTL is pinned high so the
    entry cannot expire on its own and let the test pass for that reason.
    """
    base, env = live
    monkeypatch.setattr(projects, "_DISCOVERY_TTL_S", 3600.0)
    _get_json(base, "/api/stats",
              project=projects.project_id(env["other"]))   # warms the cache
    newly = _build_project(env["default"].parent / "newly", runs=2)
    data = projects._read_registry()
    data[str(newly.resolve())] = {"name": "newly"}
    projects._write_registry(data)

    ids = {p["id"] for p in _get_json(base, "/api/projects")["projects"]}
    assert projects.project_id(newly) in ids


# ── /api/project/forget — the switcher's dismiss control ─────────────────────
# The dashboard's half of `exptrack project forget`: it must call the same
# `projects.forget`, take only a server-issued id (never a path), and leave
# both the database and any file under the project's root untouched — this
# only edits the registry.

def test_forget_removes_a_registered_project_from_the_list(live):
    base, env = live
    other_id = projects.project_id(env["other"])
    assert other_id in {p["id"] for p in _get_json(base, "/api/projects")["projects"]}

    status, body = _post(base, "/api/project/forget", {"id": other_id})
    assert status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["id"] == other_id

    remaining = {p["id"] for p in _get_json(base, "/api/projects")["projects"]}
    assert other_id not in remaining


def test_forget_refuses_an_unknown_id_and_removes_nothing(live):
    base, env = live
    before = {p["id"] for p in _get_json(base, "/api/projects")["projects"]}

    status, body = _post(base, "/api/project/forget", {"id": "0" * 16})
    assert status == 200            # write routes answer 200 with an error body
    assert "error" in json.loads(body)

    after = {p["id"] for p in _get_json(base, "/api/projects")["projects"]}
    assert after == before


def test_forget_rejects_a_filesystem_path_supplied_as_the_id(live, tmp_path):
    """A path is never a valid id: discover() only ever emits path-derived
    hashes, so a path posted as `id` can't match anything and must be refused
    exactly like an unknown id — never resolved as a path in its own right."""
    base, env = live
    status, body = _post(base, "/api/project/forget", {"id": str(env["other"])})
    assert status == 200
    assert "error" in json.loads(body)
    # Nothing was removed — the path did not silently resolve to any project.
    ids = {p["id"] for p in _get_json(base, "/api/projects")["projects"]}
    assert projects.project_id(env["other"]) in ids


def test_forget_touches_only_the_registry(live):
    """Forgetting is "stop listing this", not "delete this" — the project's
    database and every file under its root survive, byte for byte."""
    base, env = live
    other_root = env["other"]
    db_path = other_root / ".exptrack" / "experiments.db"
    before_bytes = db_path.read_bytes()
    marker = other_root / "marker.txt"
    marker.write_text("still here", encoding="utf-8")

    status, body = _post(base, "/api/project/forget",
                         {"id": projects.project_id(other_root)})
    assert status == 200
    assert json.loads(body)["ok"] is True

    assert other_root.is_dir()
    assert db_path.read_bytes() == before_bytes
    assert marker.read_text(encoding="utf-8") == "still here"
    # A forgotten-but-still-real project is discoverable again the moment it
    # is re-registered — forgetting only removed the pointer, not the project.
    projects.register(other_root, "other")
    ids = {p["id"] for p in _get_json(base, "/api/projects")["projects"]}
    assert projects.project_id(other_root) in ids


def test_forget_rejects_a_missing_id(live):
    base, _ = live
    status, body = _post(base, "/api/project/forget", {})
    assert status == 200
    assert "error" in json.loads(body)


# ── the /api/file/ sandbox follows the active project ────────────────────────

def test_the_file_sandbox_follows_the_active_project(live):
    """readable_project_path resolves through project_root(), so activation
    must move the sandbox with it — otherwise the active project's own files
    read as out-of-bounds."""
    base, env = live
    (env["other"] / "data.txt").write_text("OTHER", encoding="utf-8")
    status, body = _request(base, "/api/file/data.txt",
                            project=projects.project_id(env["other"]))
    assert status == 200
    assert body == b"OTHER"


def test_the_file_sandbox_refuses_another_projects_files(live):
    """A regression here is a file-read escape, not a cosmetic bug: with one
    project active, a path climbing into a *different* discovered project must
    be refused rather than served."""
    base, env = live
    (env["default"] / "secret.txt").write_text("DEFAULT", encoding="utf-8")
    escape = urllib.parse.quote(f"../{env['default'].name}/secret.txt", safe="")
    status, body = _request(base, "/api/file/" + escape,
                            project=projects.project_id(env["other"]))
    assert status == 403
    assert b"DEFAULT" not in body


# ── cross-project Compare ───────────────────────────────────────────────────
# Compare is the only surface that may span projects: every other view reads a
# *set* whose members have to share a parameter space, while Compare reads an
# explicitly chosen handful of runs. These tests are written against the real
# route, not against `split_qualified_id` alone — the grammar is the easy half,
# and the half that broke is what the route leaves behind on the thread.

def _compare(base, ids, project=None):
    """(status, decoded payload) for a multi-compare POST."""
    status, body = _post(base, "/api/multi-compare", {"ids": ids}, project)
    return status, json.loads(body)


def test_split_qualified_id_handles_both_forms():
    from exptrack.projects import split_qualified_id
    assert split_qualified_id("abc123") == (None, "abc123")
    assert split_qualified_id("deadbeefdeadbeef:run42") == (
        "deadbeefdeadbeef", "run42")
    # An empty project half is not a project — it degrades to "the current
    # one" rather than resolving an id nothing can name.
    assert split_qualified_id(":run42") == (None, "run42")


def test_compare_pulls_runs_from_two_projects(live):
    """The point of the whole feature: two runs that live in two databases
    come back from one request, each saying which project it came from."""
    base, env = live
    other_id = projects.project_id(env["other"])
    status, payload = _compare(
        base, ["default0000", f"{other_id}:other0000"],
        project=projects.project_id(env["default"]))
    assert status == 200, payload
    assert not payload.get("error"), payload
    got = {e["id"] for e in payload["experiments"]}
    assert got == {"default0000", "other0000"}, payload
    # Two projects can hold runs with the same name, so the answer has to name
    # the project per run or the columns identify nothing.
    by_id = {e["id"]: e for e in payload["experiments"]}
    assert by_id["other0000"]["project_id"] == other_id
    assert by_id["other0000"]["project_name"] == "other"
    assert by_id["default0000"]["project_id"] == projects.project_id(env["default"])
    assert by_id["other0000"]["qualified_id"] == f"{other_id}:other0000"


def test_compare_keeps_the_posted_order_across_projects(live):
    """The client laid the columns out in the order the user picked them; an
    answer reordered by project silently relabels every column."""
    base, env = live
    other_id = projects.project_id(env["other"])
    _, payload = _compare(base, [f"{other_id}:other0000", "default0000"],
                          project=projects.project_id(env["default"]))
    assert [e["id"] for e in payload["experiments"]] == \
        ["other0000", "default0000"]


def test_a_bare_id_means_the_current_project(live):
    """Every existing caller, bookmark and saved URL posts bare ids, and they
    must resolve against the project the request is already about — not
    against whichever project happens to be the process default."""
    base, env = live
    status, payload = _compare(base, ["other0000", "other0001"],
                               project=projects.project_id(env["other"]))
    assert status == 200, payload
    assert not payload.get("error"), payload
    assert {e["id"] for e in payload["experiments"]} == {"other0000", "other0001"}
    # Nothing was qualified, so the answer is exactly what it always was: no
    # project stamp at all on a single-project comparison.
    assert "project_id" not in payload["experiments"][0]


def test_a_cross_project_compare_leaves_the_thread_on_its_own_project(live):
    """The regression test for the dead-handle hazard.

    `get_db()` closes the previous connection when the resolved path changes,
    so after the first switch the handle the route was handed is closed. If
    the route does not reopen the request's own project before returning, the
    *next* request served by this thread — this server is single-threaded, so
    that is literally the next line — reads through a closed connection or
    through the foreign project's database.
    """
    base, env = live
    other_id = projects.project_id(env["other"])
    status, payload = _compare(base, ["default0000", f"{other_id}:other0000"],
                               project=projects.project_id(env["default"]))
    assert status == 200 and not payload.get("error"), payload
    # Back on the default project: its single run, not `other`'s three.
    assert _get_json(base, "/api/stats")["total"] == 1
    # ...and the connection in hand is usable for a write-path POST too, which
    # is where a closed handle would surface as a 500 rather than a wrong number.
    status, payload = _compare(base, ["other0000", "other0001"], project=other_id)
    assert status == 200 and not payload.get("error"), payload


def test_the_route_hands_back_a_live_connection_on_the_request_project(env):
    """The same guarantee, asserted on the objects rather than on a response.

    Called in-process so the connection and the thread binding can be
    inspected directly: `project_root()` must be the request's project again,
    and `get_db()` must hand back a handle that actually works.
    """
    from exptrack.dashboard.routes import write_routes

    other_id = projects.project_id(env["other"])
    conn = get_db()
    payload = write_routes.api_multi_compare(
        conn, {"ids": ["default0000", f"{other_id}:other0000"]})
    assert not payload.get("error"), payload
    assert len(payload["experiments"]) == 2
    assert cfg.project_root() == env["default"]

    # Asserted on the *thread's cached binding*, before anything calls get_db()
    # again. This is the whole point: get_db() re-resolves the root on every
    # call and self-corrects, so a test that reaches for get_db() first would
    # pass with the route's restoring `finally` deleted — it would simply be
    # the test doing the restoring. What must be true the instant the route
    # returns is that the thread is already holding the request project's
    # database, with the foreign one closed behind it.
    assert _db._local.db_path == str(
        env["default"] / ".exptrack" / "experiments.db")
    assert _db._local.conn is not None
    # ...and that cached connection is live, not a closed handle left in place.
    assert _db._local.conn.execute(
        "SELECT COUNT(*) FROM experiments").fetchone()[0] == 1
    # And the test is not vacuous: a switch really happened, so the handle the
    # route was given is a *different*, now-closed object. If these ever start
    # being the same connection, the route stopped crossing projects and the
    # assertions above are proving nothing.
    assert _db._local.conn is not conn
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_compare_refuses_an_unknown_foreign_project(live):
    """An id the server cannot resolve is an error, never a silent fall-back
    to the current project: a comparison quietly narrowed to the runs that
    happened to resolve looks like success and answers a different question."""
    base, env = live
    status, payload = _compare(base, ["default0000", "0" * 16 + ":other0000"],
                               project=projects.project_id(env["default"]))
    assert status == 200
    assert payload.get("error"), payload
    assert not payload.get("experiments")
    # Named as a *project* refusal. Reporting it as one more unresolvable run
    # id reads as "that run is gone", and the user re-picks the same run from
    # a project the dashboard will still refuse.
    assert "project" in payload["error"].lower()


def test_compare_refuses_a_schema_skewed_foreign_project(live, tmp_path):
    """Opening a schema-skewed project migrates and re-stamps it behind its
    owner's back, so it is refused with its reason — the same answer the
    ``X-Exptrack-Project`` header gets."""
    base, env = live
    old = _stamp_project(tmp_path / "old", _SCHEMA_VERSION - 1)
    projects.register(old, "old")
    status, payload = _compare(
        base, ["default0000", f"{projects.project_id(old)}:whatever"],
        project=projects.project_id(env["default"]))
    assert status == 200
    assert payload.get("error"), payload
    assert not payload.get("experiments")
    # The reason, not a bare refusal.
    assert "older exptrack" in payload["error"]


def test_compare_reports_an_id_with_no_run_half(live):
    """`"<pid>:"` names no run. Dropping it on the way in is the one failure
    this endpoint family refuses to make — an id quietly discarded is how a
    comparison ends up rendering three of the four runs that were picked."""
    base, env = live
    other_id = projects.project_id(env["other"])
    status, payload = _compare(base, ["other0000", "other0001", f"{other_id}:"],
                               project=projects.project_id(env["other"]))
    assert status == 200
    assert not payload.get("error"), payload
    assert len(payload["experiments"]) == 2
    assert f"{other_id}:" in payload["unknown_ids"], payload


# ── a file belonging to a run in another project ────────────────────────────
# An <img src> carries no headers, which is already why the auth token rides in
# the query string for /api/file/. A cross-project Compare renders images from
# runs in another project, and the query is the only channel they have.

def test_the_file_sandbox_accepts_the_project_in_the_query(live):
    base, env = live
    (env["other"] / "plot.png").write_text("OTHER-IMAGE", encoding="utf-8")
    other_id = projects.project_id(env["other"])
    status, body = _request(base, "/api/file/plot.png?project=" + other_id)
    assert status == 200, (status, body[:200])
    assert body == b"OTHER-IMAGE"


def test_a_query_named_project_is_resolved_exactly_like_the_header(live):
    """The query widens *how* a project is named, never what may be named: the
    id is still matched against discovery, so an unknown one is refused rather
    than falling back to the current project's file of the same name."""
    base, env = live
    (env["default"] / "plot.png").write_text("DEFAULT-IMAGE", encoding="utf-8")
    status, body = _request(base, "/api/file/plot.png?project=" + "0" * 16)
    assert status == 400, (status, body[:200])
    assert b"DEFAULT-IMAGE" not in body


def test_a_path_in_the_project_query_is_not_accepted(live, tmp_path):
    """The same rule the header has: a client names a project by a server-issued
    id and never by a path, or any authenticated request becomes "open a
    database anywhere on this machine"."""
    base, env = live
    status, _ = _request(base, "/api/file/plot.png?project=" +
                         urllib.parse.quote(str(env["other"]), safe=""))
    assert status == 400


def test_a_foreign_runs_metrics_are_served_from_its_own_project(live):
    """The per-run fetches Compare makes for a foreign run name that run's
    project on the request. The page's project would answer with nothing, and
    an empty series draws as a run that logged no metrics."""
    base, env = live
    conn = sqlite3.connect(str(env["other"] / ".exptrack" / "experiments.db"))
    try:
        conn.execute(
            "INSERT INTO metrics (exp_id, key, value, step, ts) "
            "VALUES ('other0000', 'loss', 0.25, 1, '2026-01-01T00:00:00')")
        conn.commit()
    finally:
        conn.close()
    other_id = projects.project_id(env["other"])
    # Asked with the page on `default`, but naming the run's own project.
    payload = _get_json(base, "/api/metrics/other0000", project=other_id)
    assert payload.get("loss"), payload
    # ...and the same request without it finds nothing, which is exactly the
    # blank panel this exists to prevent.
    status, body = _request(base, "/api/metrics/other0000")
    assert status != 200 or not json.loads(body).get("loss")
