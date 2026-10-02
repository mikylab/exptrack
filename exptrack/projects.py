"""
exptrack/projects.py — the set of projects this machine knows about.

`config.py` resolves *a* project root; this module is about the set of them:
discovering candidates, remembering them, and deciding whether one is safe to
open.

The schema probe is the load-bearing piece. `core.db.get_db()` runs
`_ensure_schema` whenever a database's `user_version` differs from the running
install's `_SCHEMA_VERSION` — in *either* direction — and then stamps the
database to its own version. One dashboard serving many projects therefore has
to be careful in a way a single-project process never was: opening a project
last touched by a different exptrack would migrate it behind the user's back,
and if that project has its own virtualenv, the two installs then stamp it
back and forth on every open. So discovery probes with a read-only connection
that structurally cannot migrate, and a mismatch refuses rather than opens.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

from . import config as cfg
from .core.db import _SCHEMA_VERSION
from .core.git import _git_env
from .core.utils import debug_log

SCHEMA_OK = "ok"
SCHEMA_OLD = "needs-upgrade"
SCHEMA_NEW = "too-new"
STALE = "stale"

_DB_RELATIVE = ".exptrack/experiments.db"


def database_path(root: Path) -> Path:
    """Where a project's database lives, without consulting its config.

    Deliberately not `config.load()`: that would need the project activated,
    and discovery runs over projects we have decided nothing about yet. A
    project with a relocated `db` config key is listed by its default path and
    reads as stale — rare, and better than activating an unvetted project.
    """
    return Path(root) / _DB_RELATIVE


def probe_status(root: Path) -> str:
    """Classify *root* without opening its database for writing."""
    db = database_path(root)
    if not db.is_file():
        return STALE
    try:
        # mode=ro cannot create, cannot migrate, and fails cleanly when the
        # file is missing — which is also the stale check.
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        debug_log(f"projects: cannot open {db} read-only: {e}")
        return STALE
    try:
        stamp = int(conn.execute("PRAGMA user_version").fetchone()[0])
    except (sqlite3.Error, TypeError, ValueError) as e:
        debug_log(f"projects: cannot read user_version from {db}: {e}")
        return STALE
    finally:
        conn.close()

    if stamp == _SCHEMA_VERSION:
        return SCHEMA_OK
    return SCHEMA_OLD if stamp < _SCHEMA_VERSION else SCHEMA_NEW


def status_message(status: str, root: Path) -> str:
    """The user-facing explanation for a non-ok status ("" when ok)."""
    if status == SCHEMA_OLD:
        return (f"This project's database was written by an older exptrack. "
                f"Upgrade it with:  exptrack upgrade   (run it in {root})")
    if status == SCHEMA_NEW:
        return ("This project's database was written by a newer exptrack "
                "than the one serving this dashboard. Upgrade this install "
                "to open it.")
    if status == STALE:
        return f"No exptrack database found at {root}."
    return ""


# Enough of the digest to make a collision implausible while staying short
# enough to read in a URL or a log line.
_ID_LEN = 16


def registry_path() -> Path:
    """``~/.exptrack/projects.json`` — user-global, not per-project.

    Deliberately outside any virtualenv: the point is that whichever install's
    `exptrack` you run finds the same set of projects. Written only by
    `exptrack init` and `exptrack ui start` (see config.init / daemon.start) —
    never from an arbitrary command, which would mean a global-file write from
    every CLI invocation, including ones running inside a training loop.
    """
    return cfg.user_dir() / "projects.json"


def project_id(root: Path) -> str:
    """A stable id for *root*, derived from its resolved path.

    Server-issued and path-derived rather than path-carrying: the client
    names a project by this id and never by a path, so no request can point
    the dashboard at an arbitrary directory the id happens to encode.
    """
    resolved = str(Path(root).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:_ID_LEN]


def _read_registry() -> dict:
    """The raw ``{path: {"name": ...}}`` mapping, or {} on any read failure.

    A hand-edited or half-written projects.json must degrade to "nothing
    registered" rather than crash every caller that touches the registry —
    the same invariant config.json already holds for per-project settings.
    """
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        debug_log(f"projects: unreadable registry: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _write_registry(data: dict) -> bool:
    """Atomically overwrite the registry file, 0600. True on success.

    This is the one file in the system that aggregates something the user
    cannot re-derive — every other project's registration. Writing in place
    with O_TRUNC (the first cut of this) truncates before it writes: a crash
    or kill mid-write leaves unparseable JSON, `_read_registry` degrades that
    to `{}`, and the *next* `register()` call would silently "lose" every
    other project by rewriting just its own one entry over an empty file. So
    the write lands on a temp path beside the target — created via
    `cfg.open_private` so the 0600 mode is set at creation, same as the final
    file — and `os.replace()` swaps it in; POSIX and Windows `replace` are
    both atomic within one filesystem, and a rename can't leave a half
    written target. The temp file is removed on any failure so a crash here
    doesn't litter `~/.exptrack/` with orphaned `.tmp` files.
    """
    target = registry_path()
    # The pid is in the temp name because one fixed name is not a private
    # scratch file: two processes registering at once (an `exptrack init` and
    # an `exptrack ui start`, say) interleave their writes into the same path
    # and `os.replace` installs whichever mixture is there — unparseable JSON,
    # which `_read_registry` degrades to `{}`, which is the total-loss failure
    # this whole function exists to prevent.
    tmp = target.with_suffix(f".json.{os.getpid()}.tmp")
    try:
        fd = cfg.open_private(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, target)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return True
    except OSError as e:
        # A project that cannot be registered is a smaller problem than a
        # command that fails because of it.
        debug_log(f"projects: could not write the registry: {e}")
        return False


def _entries_from(data: dict) -> list[dict]:
    """Turn a raw registry mapping into ``[{"path", "name"}, ...]``."""
    return [{"path": path, "name": (entry or {}).get("name") or Path(path).name}
            for path, entry in data.items()
            if isinstance(entry, dict)]


def registered() -> list[dict]:
    """The registry's entries as ``[{"path", "name"}, ...]``."""
    return _entries_from(_read_registry())


def register(root: Path, name: str | None = None) -> None:
    """Remember *root*. Idempotent; never raises.

    Called only from `exptrack init` and `exptrack ui start` — see the
    module docstring on `registry_path` for why nothing else may call this.
    """
    resolved = str(Path(root).resolve())
    entry = {"name": name or Path(resolved).name}
    data = _read_registry()
    if data.get(resolved) == entry:
        # Already recorded exactly this way. `exptrack tunnel` chains
        # `ui start && ui status` on every invocation and `ui start` now
        # registers on its already-running path too, so the common case is a
        # no-op — and a no-op should not rewrite a user-global file or drop
        # everyone's discovery cache.
        return
    data[resolved] = entry
    _write_registry(data)
    invalidate_discovery_cache()


def forget(key: str) -> bool:
    """Drop the entry matching *key* (a path, a name or a project id). True if
    removed. The id is what the dashboard's API and URLs (`?project=`) show,
    so it is the handle a user has copied — refusing it sent them off to
    `project list` to translate it back into a name."""
    data = _read_registry()
    # A key containing a path separator or a drive letter is meant as a path;
    # anything else is matched only against stored names, so "beta" doesn't
    # accidentally resolve against cwd and match nothing.
    target = str(Path(key).resolve()) if os.path.sep in key or ":" in key else None
    for path, entry in list(data.items()):
        name = (entry or {}).get("name") or Path(path).name
        if path in (target, key) or name == key or project_id(Path(path)) == key:
            del data[path]
            written = _write_registry(data)
            invalidate_discovery_cache()
            return written
    return False


def _absence_confirmed(root: Path) -> bool:
    """Whether *root* provably holds no exptrack project right now.

    True means the directory is readable (or its absence is) and there is no
    `.exptrack/` in it — a registry entry pointing here is dead and can be
    pruned. False means either the project is there, or we could not tell.

    The anchor check is the whole subtlety. An unplugged external disk or an
    unmounted network share makes every path under it look exactly like a
    deleted project, and pruning on that reading would drop a project the
    user still has, from a listing that runs on the dashboard's request path.
    So the path's anchor — the drive root on Windows, `/` on POSIX — must
    itself exist before an absence is believed. On POSIX that is always true,
    which is honest: there is no cheap way to tell an unmounted `/mnt/x` from
    a deleted one, and the cost of being wrong is one `exptrack init` in the
    project to register it again.
    """
    root = Path(root)
    if (root / ".exptrack").is_dir():
        return False
    anchor = root.anchor
    return not anchor or Path(anchor).is_dir()


def _prune_registry(data: dict, paths: list[str]) -> None:
    """Drop *paths* from *data* and rewrite the registry. Never raises.

    Takes the mapping `discover` already read rather than re-reading it: the
    two must agree about what is being removed, and a second read is a second
    chance for them not to.

    One write for the whole set rather than one per entry: a registry holding
    150 dead pytest directories (the case this exists for — see
    `tests/run_all.py`, which used to run the suite against the developer's
    real HOME) would otherwise rewrite the file 150 times.

    Deliberately does **not** call `invalidate_discovery_cache()`. The caller's
    own return value already excludes every path pruned here, so the answer
    about to be cached is the post-prune one and is not stale. Invalidating
    would bump `_discovery_gen`, and `_finish_discovery` refuses to store a
    result whose generation moved — so the refresh that did the pruning would
    not be cached at all. With `_write_registry` swallowing a failed write
    (a read-only `~/.exptrack`, say), that made the prune re-fire on every
    single discovery and the 2s memo store nothing, turning a `git worktree
    list` plus a probe per project into per-request work on the polled path.
    """
    if not paths:
        return
    dropped = False
    for path in paths:
        if data.pop(path, None) is not None:
            dropped = True
    if dropped:
        _write_registry(data)


def _run_git(root: Path, *args: str) -> str | None:
    """`git -C root <args>` stdout, or None on any failure.

    Never raises: not a repo, git missing, a slow or contended git are all
    "no answer", not an error a caller has to handle.

    Deliberately not `core.git._git`, which looks like the same thing and is
    not safe here. That runner memoizes through `core.git._memo`, a plain
    module global with no lock, written for the single-threaded notebook
    magics — sharing it with `ThreadingHTTPServer` workers would let one
    request answer from another request's git output. It also pins `cwd` to
    `cfg.project_root()`, which under the dashboard is whatever project the
    *thread* is bound to, while discovery asks about projects the thread is
    not in. `_git_env` is imported from `core.git` because that part is a
    pure value and is the right thing to share.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=5,
            stdin=subprocess.DEVNULL, env=_git_env())
    except (OSError, subprocess.SubprocessError) as e:
        debug_log(f"projects: git {' '.join(args)} failed: {e}")
        return None
    return result.stdout if result.returncode == 0 else None


def _git_worktree_rows(root: Path) -> list[dict]:
    """``[{"path", "branch"}, ...]`` for every worktree of *root*'s repo.

    The branch comes from the same porcelain output as the path — one
    subprocess for both. It is what makes a group of worktrees readable:
    they are checkouts of one repository and usually share a directory
    name, so the branch is the only thing that tells two of them apart.
    """
    out = _run_git(root, "worktree", "list", "--porcelain")
    if out is None:
        return []
    rows: list[dict] = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            rows.append({"path": line[len("worktree "):].strip(), "branch": ""})
        elif line.startswith("branch ") and rows:
            # refs/heads/feat/x -> feat/x. A detached worktree prints no
            # `branch` line at all and keeps the "" it was created with.
            ref = line[len("branch "):].strip()
            rows[-1]["branch"] = (ref[len("refs/heads/"):]
                                  if ref.startswith("refs/heads/") else ref)
    return rows


def _git_worktrees(root: Path) -> list[Path]:
    """Every worktree of *root*'s repository. [] when git is unavailable."""
    return [Path(r["path"]) for r in _git_worktree_rows(root)]


def _discovery_candidates(
    registry_entries: list[dict], current_root: Path | None
) -> dict[str, str | None]:
    """Merge registry entries and worktree paths into one ``{path: name}``.

    A registry entry's name (possibly None) always wins over a worktree
    guess, via ``setdefault`` ordering: registry entries are inserted first.
    Takes the already-read registry entries rather than re-reading, so a
    concurrent rewrite of projects.json can't make this set disagree with
    the guard set `discover` builds from the same read.
    """
    candidates: dict[str, str | None] = {}
    for entry in registry_entries:
        candidates[entry["path"]] = entry["name"]
    if current_root is not None:
        for wt in _git_worktrees(current_root):
            candidates.setdefault(str(Path(wt).resolve()), None)
    return candidates


def discover(current_root: Path | None = None, prune: bool = True) -> list[dict]:
    """Every project this machine knows about, each with its status.

    The union of the registry and — when *current_root* is given — the
    worktrees of its repository. Worktrees need no registration, which is the
    case that motivated this release: three worktrees of one repo are three
    projects, and nobody should have to declare them.

    A *worktree* candidate that was never an exptrack project (no
    `.exptrack/` at all) is skipped: git worktree list surfaces every
    worktree of the repo, including ones nobody ever ran `exptrack init` in,
    and those are noise, not stale projects.

    A *registered* candidate with no `.exptrack/` is dropped too, and pruned
    from the registry (see `_absence_confirmed` for when an absence counts).
    This used to be listed as `stale` and kept forever, on the theory that
    silently dropping an entry is indistinguishable from discovery being
    broken. That reasoning holds for a project that is merely *unreadable*
    and not for one that provably is not there — and in practice the registry
    filled with dead temp directories (every `tests/run_all.py` run appended
    a few, against the developer's real HOME) until the switcher was a list
    of greyed-out rows nobody could click with the real projects buried in
    it. A project whose `.exptrack/` exists but whose database does not is
    still listed as `stale`, with its reason, and still registered: that is
    the unreadable case, not the absent one.

    ``prune=False`` drops the entry from the *listing* without editing the
    registry. `projects.py` documents that only `exptrack init` and `exptrack
    ui start` write the registry, and `discover_cached` runs on the
    dashboard's request path — resolving a project id for a poll must not
    rewrite a user-global file. So the surfaces that *show* the list
    (`/api/projects`, `exptrack project list`) prune, and id resolution does
    not. Both hide the dead entry, which is what the reader sees.
    """
    # Read the registry exactly once: the candidate set and the "is this
    # registered" guard set below must agree, even if something else
    # rewrites projects.json between two reads.
    registry = _read_registry()
    registry_entries = _entries_from(registry)
    registry_paths = {e["path"] for e in registry_entries}
    candidates = _discovery_candidates(registry_entries, current_root)

    out = []
    dead: list[str] = []
    for path, name in candidates.items():
        root = Path(path)
        if not (root / ".exptrack").is_dir():
            # Not a project. A worktree candidate is simply noise. A
            # registered one is a dead entry when its absence can be
            # confirmed — and when it cannot (an unplugged disk), it falls
            # through and is listed as `stale`, because an absence we cannot
            # confirm is not an absence.
            if path not in registry_paths:
                continue
            if _absence_confirmed(root):
                dead.append(path)
                continue
        status = probe_status(root)
        out.append({
            "id": project_id(root),
            "name": name or root.name,
            "path": path,
            "status": status,
            "message": status_message(status, root),
        })
    if prune:
        _prune_registry(registry, dead)
    # Secondary key is the path: two same-named worktrees under different
    # parents would otherwise order by dict-insertion (registry-then-git),
    # which is an implementation detail, not a stated order.
    return sorted(out, key=lambda e: (e["name"].lower(), e["path"]))


# ── Cached discovery ────────────────────────────────────────────────────────
# `discover` costs a `git worktree list` subprocess, which is fine once per CLI
# invocation and not fine on the dashboard's request path: the UI polls
# /api/metrics every 5 seconds per live run per open tab, and every one of
# those requests names a project and therefore resolves an id through
# discovery. A process-wide cache with a short life collapses a poll burst into
# one spawn while still letting a project registered a moment ago appear
# without restarting the dashboard.
#
# Two seconds rather than a minute deliberately: the thing this cache can be
# wrong about is the *set* of projects, and being wrong about that is a
# switcher that does not list a project the user just created. Short enough
# that nobody notices, long enough that a burst of polls pays once.
_DISCOVERY_TTL_S = 2.0

# How long a thread waits for another thread's refresh before giving up and
# running its own. The refresher is bounded (git's own 5s timeout plus a
# read-only probe per candidate), so reaching this means something is wedged —
# and a wedged refresher must not become a wedged dashboard.
_DISCOVERY_WAIT_S = 10.0

# The lock guards the two maps and nothing else. It is deliberately NOT held
# across `discover()`: that call spawns git (5s timeout) and opens a sqlite
# connection per candidate, and holding a global lock over it would serialize
# every project-named request in the process behind one slow subprocess —
# the blocking-operation-on-a-request-path hazard that ThreadingHTTPServer
# exists to avoid (docs/design/patterns/server.md). Single-flight is still
# enforced, but through an in-progress event per key rather than a lock: one
# thread refreshes, everyone else is served the previous answer (or waits only
# if there is no previous answer at all).
_discovery_lock = threading.Lock()
_discovery_cache: dict = {}          # key -> (expires_at, entries)
_discovery_inflight: dict = {}       # key -> Event, set when that refresh ends

# Bumped by every invalidation. A refresh that started before the invalidation
# may finish after it, carrying data read from the registry as it was *before*
# the write — storing that would resurrect a project the user just forgot. The
# generation is checked at store time, so a result that raced an invalidation
# is returned to its own caller and simply not cached.
_discovery_gen = 0


def invalidate_discovery_cache() -> None:
    """Drop the cached discovery. Called by every writer in this process.

    A cache that outlives a `register`/`forget` made by the same process is a
    dashboard that denies a project the user just added through it — a visible
    wrong answer, not merely a stale one. Registry writes from *another*
    process are covered by the TTL instead; there is no cross-process
    invalidation and this cache is deliberately not worth one.
    """
    global _discovery_gen
    with _discovery_lock:
        _discovery_cache.clear()
        _discovery_gen += 1


def _claim_discovery(key: str):
    """``(fresh, stale, event, leader, gen)`` for *key*, under the map lock.

    Holds the lock only to read and stamp the maps. *fresh* is an unexpired
    answer (nothing else to do); *stale* is an expired one, which a follower
    serves rather than blocking; *leader* says this thread owns the refresh.
    """
    with _discovery_lock:
        hit = _discovery_cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            # A copy on the way out: the cached list outlives the call, and a
            # caller that sorted or filtered it in place would corrupt every
            # later hit.
            return list(hit[1]), None, None, False, _discovery_gen
        stale = list(hit[1]) if hit is not None else None
        event = _discovery_inflight.get(key)
        if event is None:
            event = threading.Event()
            _discovery_inflight[key] = event
            return None, stale, event, True, _discovery_gen
        return None, stale, event, False, _discovery_gen


def _finish_discovery(key: str, event, entries, gen: int) -> None:
    """Publish a refresh's result and release the followers waiting on it."""
    with _discovery_lock:
        if entries is not None and gen == _discovery_gen:
            # Measured from *after* the discovery: timing it from before would
            # let a slow git write an entry that is already expired, so the
            # cache would do nothing in exactly the case it is here for.
            _discovery_cache[key] = (time.monotonic() + _DISCOVERY_TTL_S, entries)
        if _discovery_inflight.get(key) is event:
            del _discovery_inflight[key]
    event.set()


def discover_cached(current_root: Path | None = None) -> list[dict]:
    """`discover`, memoized for `_DISCOVERY_TTL_S`.

    For callers that resolve an id on a request path and would otherwise pay a
    subprocess per request. Anything *showing the user the list* should call
    `discover` directly: a slightly slower switcher beats one that is wrong
    about which projects exist.

    Keyed by *current_root*, because it decides which worktrees are candidates
    — one key's answer is not another's.
    """
    key = str(current_root) if current_root is not None else ""
    deadline = time.monotonic() + _DISCOVERY_WAIT_S
    while True:
        fresh, stale, event, leader, gen = _claim_discovery(key)
        if fresh is not None:
            return fresh
        if leader:
            entries = None
            try:
                # prune=False: this is the request path. See discover().
                entries = discover(current_root=current_root, prune=False)
            finally:
                _finish_discovery(key, event, entries, gen)
            return list(entries)
        if stale is not None:
            # A slightly old set of projects beats waiting on a subprocess.
            return stale
        if not event.wait(max(0.0, deadline - time.monotonic())):
            return discover(current_root=current_root, prune=False)


# ── Worktree grouping ───────────────────────────────────────────────────────
# Three worktrees of one repository are three projects with three databases,
# and they are also the case the multi-project dashboard exists for: they
# usually share a directory name and differ only by branch, so a flat
# switcher lists "exptrack, exptrack, exptrack" and the reader has to hover
# each one to find out which is which.
#
# This is display metadata and nothing else — it never changes which database
# a request reads, and it is deliberately NOT computed by `discover`, which
# runs on the dashboard's request path to resolve an id. Only the surface
# that renders the list pays for it.

# Above this many projects the grouping is skipped entirely. A switcher with
# 30 projects in it is a different problem than this solves, and it is not
# worth the subprocesses on the way to that conclusion.
_GROUP_PROBE_MAX = 24


def _resolved(path: str) -> str:
    """`path` resolved, or `path` itself when the filesystem won't say."""
    try:
        return str(Path(path).resolve())
    except OSError:
        return path


def annotate_worktree_groups(entries: list[dict]) -> list[dict]:
    """Add ``group``, ``group_name`` and ``branch`` to *entries*, in place.

    (It returns *entries* as well, for callers that want to chain; the list
    is the same object, never a copy.)

    One `git worktree list --porcelain` per *repository*, not per project.
    That output already names every worktree of the repo and the branch each
    one is on, so a single spawn assigns the whole group — the first cut ran
    `rev-parse --git-common-dir` per project *and* a worktree list per group,
    which for the release's headline case (three checkouts) meant five
    sequential spawns on the request that renders the switcher, each ~30-80 ms
    on Windows, holding a `ThreadingHTTPServer` worker for all of it.

    The group id is derived from the repository's **main** worktree, which
    `git worktree list` always prints first and every member agrees on — the
    same stable key `--git-common-dir` gave, without the extra process.

    Only entries that share a repository with at least one other entry are
    annotated: a lone project is not a "group of one", and labelling it as
    one would add a heading to every row in the common single-project case.

    Everything degrades to "no grouping": no git, a project that is not a
    repository, a repository whose worktree list cannot be read. The switcher
    then renders exactly the flat list it always did.
    """
    if len(entries) < 2 or len(entries) > _GROUP_PROBE_MAX:
        return entries

    by_path = {_resolved(e["path"]): e for e in entries}
    seen: set[str] = set()
    for key, entry in by_path.items():
        if key in seen:
            continue                      # a sibling's listing already covered it
        rows = _git_worktree_rows(Path(entry["path"]))
        if not rows:
            seen.add(key)                 # not a repository, or git said nothing
            continue
        branches = {_resolved(r["path"]): r["branch"] for r in rows}
        seen.update(branches)
        members = [by_path[k] for k in branches if k in by_path]
        if len(members) < 2:
            continue
        # The main worktree is the first line of the porcelain output, and
        # every member of the repo reports the same one.
        main = _resolved(rows[0]["path"])
        group_id = hashlib.sha256(main.encode("utf-8")).hexdigest()[:_ID_LEN]
        group_name = Path(main).name
        for member in members:
            member["group"] = group_id
            member["group_name"] = group_name
            member["branch"] = branches.get(_resolved(member["path"]), "")
    return entries


def split_qualified_id(value: str) -> tuple[str | None, str]:
    r"""Split ``<project-id>:<run-id>``; a bare id means the current project.

    The grammar has exactly two shapes, and both are *ids*:

    * ``"abc123"`` -> ``(None, "abc123")`` — the project the request is
      already about. Every existing caller, bookmark and saved URL passes
      this shape, and keeping it meaningful is what lets them all keep
      working unchanged.
    * ``"<16 hex>:abc123"`` -> ``("<16 hex>", "abc123")`` — the project id
      `project_id` issues. Run ids are hex and never contain a colon, so the
      separator is unambiguous inside that grammar.

    A **path is not accepted** and must never be passed here: on Windows
    ``C:\work\p`` would split at the drive colon and read as project ``C``.
    That is not a vulnerability — a client only ever names a project by id,
    and every caller resolves the returned id against the server's own
    discovered id->path map, so a bogus ``C`` resolves to nothing and is
    refused rather than opening a directory. It is spelled out because the
    contract is the whole defence: ids in, never paths.
    """
    project, sep, run = value.partition(":")
    if not sep:
        return None, value
    return project or None, run
