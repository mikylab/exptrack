"""
exptrack/core/experiment.py — Experiment class

One Experiment = one run of a script or a notebook session.
Captures: params, metrics, git state (branch + uncommitted diff),
output file paths, and fires plugin hooks on lifecycle events.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import math
import platform
import re as _re
import socket
import sys
import threading
import time
import traceback as _tb
import uuid
import weakref
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config as cfg
from .._console import harden_stdio
from ..plugins import registry as plugins
from .db import flush_pending, get_db, rename_output_folder, store_git_diff
from .git import git_info
from .gpu import gpu_info
from .naming import make_run_name, output_path
from .script_snapshot import capture_script_snapshot
from .utils import debug_log, join_notes, resolve_script_identity, safe_call

_VALID_STATUSES = {"running", "done", "failed"}

# Cap on the stored failure traceback so a pathological error can't bloat the DB.
_MAX_TRACEBACK_CHARS = 20000

# The run created by `exptrack run` / `python -m exptrack`, published here so a
# wrapped script that creates its OWN Experiment() — e.g. one written for plain
# `python script.py` with `with Experiment() as exp:` — adopts this wrapper
# instead of spawning a redundant second run for the same script (the "phantom
# run": the wrapper gets the code snapshot but no metrics, and the script's own
# run gets the metrics, so a same-script comparison then floods with None→value
# changes). Only a bare, first `Experiment()` adopts it; a script that passes its
# own identity (name/params/…) or creates additional runs gets independent rows.
_run_wrapper: Experiment | None = None


def publish_run_wrapper(exp: Experiment | None) -> None:
    """Register the `exptrack run` wrapper as adoptable (see ``_run_wrapper``)."""
    global _run_wrapper
    _run_wrapper = exp


def _claim_run_wrapper() -> Experiment | None:
    """Hand out the adoptable wrapper exactly once, marking it adopted so its
    ``__init__`` is skipped when the script's ``Experiment()`` re-enters it."""
    global _run_wrapper
    w = _run_wrapper
    if w is not None:
        _run_wrapper = None
        w._adopted = True
    return w


# Live, unfinished runs, so interpreter shutdown can flush metrics still held
# inside the commit-coalescing window (see Experiment._commit_metrics). Weak
# refs: this must never be the reason a run object stays alive. A script that
# just falls off the end without calling finish() still keeps its last points;
# only a hard kill (SIGKILL) can lose them, bounded by the interval.
_live_runs: weakref.WeakSet[Experiment] = weakref.WeakSet()


def _flush_live_runs() -> None:
    for exp in list(_live_runs):
        try:
            exp.flush_metrics()
        except Exception:
            pass        # shutdown: never raise out of an atexit hook
    # _live_runs holds weak references, so a run dropped without finish() is
    # already gone from it with its coalescing window still open. flush_pending
    # asks the *connection* whether rows are outstanding, so those land too —
    # without it the next Experiment()'s BEGIN IMMEDIATE failed with "cannot
    # start a transaction within a transaction" and its rollback destroyed the
    # collected run's points.
    flush_pending()


atexit.register(_flush_live_runs)


# Serialises the metric write path against the trailing flusher, which commits a
# run's connection from its own thread. One lock for every run rather than one
# each: uncontended it costs the same, and it needs no per-instance setup on the
# resume path, which skips __init__. The flusher's condition shares it, so a
# wait releases exactly the lock the write path takes.
_metric_commit_lock = threading.RLock()
_flush_cv = threading.Condition(_metric_commit_lock)
# Runs with an open coalescing window -> the moment it closes. Weak keys: this
# must never be what keeps a run alive.
_flush_due: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_flusher: threading.Thread | None = None


def _ensure_flusher() -> None:
    """Start the one trailing-flush thread, once per process. Caller holds the lock."""
    global _flusher
    if _flusher is not None and _flusher.is_alive():
        return      # (a forked child inherits the variable, not the thread)
    t = threading.Thread(target=_flusher_loop, name="exptrack-metric-flush",
                         daemon=True)
    try:
        t.start()
    except RuntimeError as e:       # interpreter shutting down: atexit flushes
        debug_log(f"metrics: could not start trailing flush: {e}")
        return
    _flusher = t


def _flusher_loop() -> None:
    """Close every coalescing window that no later write closed.

    One long-lived daemon thread rather than a timer per window: a tight loop
    opens about four windows a second, and a thread spawned for each was ~14k
    threads an hour. A window an inline commit already closed is removed from
    `_flush_due` there, so this never commits a second time behind it.
    """
    with _flush_cv:
        while True:
            if not _flush_due:
                _flush_cv.wait()
                continue
            exp, due = min(_flush_due.items(), key=lambda kv: kv[1])
            wait = due - time.perf_counter()
            if wait > 0:
                del exp     # not held across the wait: the run may be collected
                _flush_cv.wait(wait)
                continue
            del _flush_due[exp]
            exp._commit_pending_window()
            del exp


def mark_wrapper_foreign_child(exp: Experiment) -> None:
    """Flag the published wrapper that a *different* Experiment was built under it.

    A script running under ``exptrack run`` that constructs its own
    ``Experiment(...)`` with explicit identity (a sweep) — instead of adopting the
    wrapper — leaves the wrapper metrics-less, a phantom row ``__main__`` Trashes at
    finish. No-op outside ``exptrack run`` (no wrapper published) and for the
    wrapper's own construction (it runs before ``publish_run_wrapper``, so
    ``_run_wrapper`` is still ``None`` — it never flags itself)."""
    if _run_wrapper is not None and _run_wrapper is not exp:
        _run_wrapper._had_foreign_child = True


def _active_session_node(exp: Experiment | None = None) -> str | None:
    """Id of the Session Trees node currently being explored, or None.

    Stamped onto each metric as it's written so a metric belongs to the branch
    that produced it. A notebook session funnels every ``metric()`` call into
    one auto-created run, so without this the only way to attribute a metric to
    a branch is to guess from timestamps — and that guess is wrong whenever the
    user revisits an earlier branch, since switching back changes the active
    node without creating one.

    Import is local and failure is swallowed: metric logging must not depend on
    the (optional) session subsystem being importable.
    """
    try:
        from ..sessions import get_current_session
        sm = get_current_session()
        if sm is None or not sm.session_id:
            return None
        # Only tag metrics belonging to *this session's* run. The tag used to
        # be applied to any metric logged while a session was active in the
        # kernel, whoever owned the run — and `materialize` then copied those
        # foreign numbers onto the graduated branch run, re-introducing the
        # cross-attribution the tag exists to prevent.
        if exp is not None and not sm.owns_experiment(exp.id):
            return None
        return sm._current_node_id
    except Exception as e:
        from .utils import debug_log
        debug_log(f"could not resolve active session node for metric: {e}")
    return None


def _redact_params(params: dict) -> dict:
    """Redact parameter values matching configured sensitive patterns."""
    try:
        conf = cfg.load()
        patterns = conf.get("param_redact_patterns", [])
        if not patterns:
            return params
        result = {}
        for k, v in params.items():
            redacted = False
            for pat in patterns:
                if _re.search(pat, k, _re.IGNORECASE):
                    result[k] = "***REDACTED***"
                    redacted = True
                    break
            if not redacted:
                result[k] = v
        return result
    except (KeyError, TypeError, _re.error) as e:
        print(f"[exptrack] warning: param redaction failed: {e}", file=sys.stderr)
        return params


class Experiment:
    """
    One experiment = one tracked run.

    Minimal usage (script):
        exp = Experiment()          # auto-detects script name
        exp.log_metric("loss", 0.3, step=1)
        exp.finish()

    As context manager:
        with Experiment() as exp:
            ...

    Notebook — use exptrack.notebook helpers instead (they wrap this).
    """

    # Class-level safety net for instances built via object.__new__ (see
    # resume()), which bypass __init__ where this is normally set. Without it,
    # _maybe_commit()'s `if not self._defer_commit` raises AttributeError.
    _defer_commit = False
    # Default so the resume path (object.__new__, skips __init__) and any early
    # reader never AttributeError on the explicit-command override.
    _command = ""
    # True only on a wrapper adopted by a script's bare Experiment() (see
    # __new__); its __init__ then short-circuits so it isn't re-created.
    _adopted = False
    # Set on the published `exptrack run` wrapper when a script constructs its
    # OWN Experiment(s) with explicit identity (a param sweep) instead of
    # adopting the wrapper — the tell-tale of a metrics-less phantom wrapper
    # row that `__main__` then Trashes at finish. Class default for the resume
    # path (object.__new__, skips __init__) and early readers.
    _had_foreign_child = False
    # Metric-commit coalescing (see _commit_metrics). Class-level defaults so
    # the resume path (object.__new__, skips __init__) and any early caller are
    # safe; __init__ replaces the interval with the configured value.
    _metric_commit_interval_s = 0.25
    _last_metric_commit = float("-inf")
    _metrics_uncommitted = False
    # (connection, total_changes) the last deferred metric write left behind,
    # while a window is open — what the trailing flush checks before it
    # commits (see _commit_pending_window). None once the window is closed.
    _pending = None
    # Path of the script whose source this run has already captured, so a
    # repeat capture is a no-op. Class default for the resume path
    # (object.__new__, skips __init__) and any early reader.
    _script_snapshotted = None
    # Write-time metric thinning state (see _keep_metric_point): points logged
    # per key so far, and whether the "thinning is on" notice has been printed.
    # `None` here rather than a shared dict — a mutable class attribute would be
    # shared by every run in the process. Set per instance in __init__/resume().
    _metric_logged = None
    _thin_notice_shown = False
    # Points thinning discarded, so finish() can state stored-vs-logged. The
    # opening notice can only name the factor; `metric_keep_every` reads like a
    # budget ("keep 1000 points") and is a divisor, and the two differ by orders
    # of magnitude for anyone whose loop already logs every Nth step.
    _metric_dropped = 0
    # None = use the config default. Class-level so _keep_metric_point's
    # build-us-bare guard below is reachable instead of dying on the attribute
    # lookup that precedes it.
    _thin_every = None

    def __new__(cls, *args, **kwargs):
        # A bare ``Experiment()`` created by a script running under
        # ``exptrack run`` adopts the run ``exptrack run`` already started,
        # rather than creating a redundant second run for the same script. Only
        # a no-argument construction adopts — a script passing its own
        # name/params/… clearly wants its own run and is never silently merged —
        # and only the first one (a later ``Experiment(...)``, e.g. a sweep
        # iteration, gets its own row because the wrapper is claimed once).
        if not args and not kwargs:
            wrapper = _claim_run_wrapper()
            if wrapper is not None:
                return wrapper
        return super().__new__(cls)

    def __init__(
        self,
        name: str = "",
        params: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        notes: str = "",
        script: str = "",
        thin_every: int | None = None,
        command: str = "",
        naming_hint: str = "",
        auto_capture: bool = True,
        _caller_depth: int = 1,
    ):
        # A plain `python train.py` never passes through the CLI's main(), and
        # the run prints `→`/`—` in its own messages; a cp1252 console must
        # degrade them rather than kill the user's training run.
        harden_stdio()
        if self._adopted:
            # This instance is the `exptrack run` wrapper, adopted by a script's
            # bare Experiment() (see __new__). It's already fully initialized —
            # re-running __init__ would insert a second run for the same script.
            return
        # A script running under `exptrack run` that builds its own Experiment(s)
        # with explicit identity (a sweep) — rather than adopting the wrapper —
        # leaves the wrapper metrics-less: a phantom row. Flag the still-published
        # wrapper so `__main__` can Trash it at finish (no-op off the wrapper path).
        mark_wrapper_foreign_child(self)
        conf          = cfg.load()
        self._start   = time.time()
        # Explicit reproduce command (e.g. from `exptrack run`); when empty we
        # fall back to _build_command() which reconstructs it from sys.argv.
        self._command = command
        self._params: dict[str, Any] = dict(params or {})
        self.tags     = list(tags or [])
        self.notes    = notes
        self.status   = "running"
        self._thin_every = thin_every  # None = use config default
        self._metric_logged: dict[str, int] = {}
        self.duration_s: float | None = None
        # How long metric writes may sit uncommitted (see _commit_metrics).
        self._metric_commit_interval_s = max(
            0.0, cfg.load().get("metric_commit_interval_ms", 250) / 1000.0)
        # -inf, not "now": the first metric of a run must commit immediately.
        # Starting the window at creation defers it until the *second* write,
        # which for a run logging once per epoch means the chart sits one epoch
        # behind for the whole run.
        self._last_metric_commit = float("-inf")
        self._metrics_uncommitted = False
        _live_runs.add(self)

        # Detect caller script if not given
        if not script:
            try:
                frame = sys._getframe(_caller_depth)
                script = frame.f_globals.get("__file__", "") or sys.argv[0]
            except Exception:
                script = sys.argv[0]  # frame detection failed, fall back to argv
        # Resolve to absolute path if it looks like a real file path;
        # keep labels (e.g. "pipeline", "train") as-is from run-start
        self.script = resolve_script_identity(script)

        # Build initial name (may be updated after argparse capture).
        # name_is_auto tracks whether the user ever deliberately named this run:
        # True when we generated the name, False when one was passed explicitly.
        # Internal auto-renames (argparse/notebook capture) keep it True; only a
        # user rename in the dashboard/API flips it to False.
        self.name_is_auto = not bool(name)
        # `naming_hint` names the run without claiming the user chose the name:
        # the shell pipeline generates a name from a `--script` hint that is not
        # the run's `script` field, and passing that generated name in as `name`
        # made every pipeline run look user-named.
        self.id = uuid.uuid4().hex[:12]
        self.name = name or make_run_name(naming_hint or script, self._params,
                                          uid=self.id[:8])

        # Snapshot git state at run time — this is the key traceability link
        ginfo = git_info()
        self.git_branch = ginfo["git_branch"]
        self.git_commit = ginfo["git_commit"]
        diff_text = ginfo["git_diff"]
        # Truncate very large diffs to keep DB size manageable (default 256 KB)
        max_kb = conf.get("max_git_diff_kb", 256)
        if max_kb and diff_text and len(diff_text) > max_kb * 1024:
            diff_text = diff_text[:max_kb * 1024] + "\n\n[truncated — exceeded max_git_diff_kb limit]"
        self.git_diff = diff_text

        self.hostname   = socket.gethostname()
        self.python_ver = platform.python_version()

        # Capture GPU/CUDA state so the experiment records device info
        try:
            ginfo_gpu = gpu_info()
            if ginfo_gpu.get("gpu_count", 0) > 0:
                self._params["_gpu"] = ginfo_gpu
        except (ImportError, OSError, RuntimeError):
            pass  # GPU libs unavailable or device inaccessible
        except Exception as e:
            print(f"[exptrack] warning: GPU detection failed: {e}", file=sys.stderr)
        self._finished  = False
        self._defer_commit = False
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.project    = conf.get("project", cfg.project_root().name)

        # Deduplicate: skip snapshot if this script+params hash was already saved
        self._snapshot_hash = self._compute_snapshot_hash()

        self._save()
        if auto_capture:
            self._install_capture_patches(conf)
        plugins.load_from_config(conf)
        plugins.on_start(self)

        print(f"[exptrack] {self.name}  ({self.id[:6]})", file=sys.stderr)

    def _accumulated_duration(self, this_session: float) -> float:
        """This session's wall time plus whatever earlier sessions recorded."""
        prior = 0.0
        if getattr(self, "_resumed", False):
            try:
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT duration_s FROM experiments WHERE id=?", (self.id,)
                    ).fetchone()
                prior = float(row["duration_s"] or 0.0) if row else 0.0
            except Exception as e:
                debug_log(f"could not read prior duration: {e}")
        return prior + max(0.0, this_session)

    def _install_capture_patches(self, conf, force: bool = False):
        """Arm the zero-friction capture patches for a script that started its
        own run.

        The patches used to be installed only by ``exptrack run`` and the
        notebook extension, so a plain ``python train.py`` with
        ``exp = Experiment()`` in it captured *no parameters at all* — and
        moving a script between the two launchers made every param appear as a
        change in the "What changed" card, because one side had them and the
        other didn't. The run object is the thing that needs the patches, so it
        arms them itself; ``exptrack run`` installs the same ones a moment
        later, and each patch is idempotent.

        Notebook runs are excluded: the notebook extension owns that path and
        installs a superset (cell hooks, output capture) with its own state.
        Best-effort throughout — a capture failure must never break a run.

        A **resumed** run is skipped here because ``Experiment.resume`` bypasses
        ``__init__`` entirely; ``exptrack run`` passes *force* so the resumed
        case is armed from the one place that knows it happened, rather than
        the launcher keeping a second copy of this list.
        """
        if str(self.script).endswith(".ipynb"):
            return
        if getattr(self, "_resumed", False) and not force:
            return
        auto = conf.get("auto_capture", {}) or {}
        try:
            from ..capture import capture_argv, patch_argparse, patch_savefig, patch_tensorboard
            if auto.get("argparse", True):
                patch_argparse(self)
            # Raw-argv capture only when argv actually belongs to this run's
            # script. `sys.argv` is process-global: a run created inside a test
            # runner, a REPL or any host program would otherwise record that
            # host's command line as its hyperparameters. `exptrack run`
            # rewrites argv to the script's own before calling this, so the
            # check passes there too.
            if auto.get("argv", True) and self._argv_is_mine():
                capture_argv(self)
            patch_savefig(self)
            if auto.get("tensorboard", True):
                patch_tensorboard(self)
        except Exception as e:
            debug_log(f"could not install capture patches: {e}")

    def _argv_is_mine(self) -> bool:
        """Whether ``sys.argv[0]`` is this run's own script."""
        try:
            argv0 = sys.argv[0] if sys.argv else ""
            if not argv0 or not self.script:
                return False
            return resolve_script_identity(argv0) == self.script
        except Exception:
            return False

    @classmethod
    def resume(cls, exp_id: str) -> Experiment:
        """Reopen a finished/failed experiment to continue it.

        Refuses a run that is in Trash: it's hidden from every list, so
        appending to it would write metrics nobody can see. Restore it first
        (dashboard Trash view, or ``exptrack`` restore) and resume again. The
        implicit "resume the latest run" lookups skip trashed rows instead and
        start a fresh run, matching the ``_BASELINE_WHERE`` precedent.
        """
        from .queries import find_experiment
        conn = get_db()
        row = find_experiment(conn, exp_id,
            "id, name, script, git_branch, git_commit, git_diff, "
            "hostname, python_ver, notes, tags, created_at, output_dir, project, "
            "deleted_at")
        if not row:
            raise ValueError(f"Experiment '{exp_id}' not found")
        if row.get("deleted_at"):
            raise ValueError(
                f"Experiment '{row['id'][:6]}' is in Trash — restore it before resuming"
            )

        exp = object.__new__(cls)
        for col in ("id", "name", "script", "git_branch", "git_commit",
                     "git_diff", "hostname", "python_ver", "notes",
                     "created_at", "project"):
            setattr(exp, col, row[col] or "")
        exp.tags = json.loads(row["tags"] or "[]")
        exp._output_dir = row["output_dir"] or ""
        exp.status, exp._finished, exp._start = "running", False, time.time()
        exp._resumed = True
        exp._thin_every = exp._snapshot_hash = None
        exp._metric_logged = {}
        # __init__-only attrs the lifecycle methods read but object.__new__ skips.
        # (_defer_commit is covered by the class-level default.)
        exp.name_is_auto = False        # resumed runs already have a chosen name
        exp.duration_s = None           # set by finish(); default so it's never unset
        # Metric-commit coalescing: the class defaults are safe, but a resumed
        # run logs metrics in the same tight loops, so it gets the configured
        # interval and the atexit flush like any other run.
        exp._metric_commit_interval_s = max(
            0.0, cfg.load().get("metric_commit_interval_ms", 250) / 1000.0)
        exp._last_metric_commit = float("-inf")
        exp._metrics_uncommitted = False
        _live_runs.add(exp)

        exp._params = {r["key"]: json.loads(r["value"]) for r in conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?", (exp.id,)).fetchall()}
        exp._timeline_seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM timeline WHERE exp_id=?",
            (exp.id,)).fetchone()[0]

        conn.execute("UPDATE experiments SET status='running', updated_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(), exp.id))
        conn.commit()

        # Log a timeline event so the dashboard shows when/why this was resumed
        exp.log_event("resume", key="command", value=exp._build_command())

        print(f"[exptrack] resumed: {exp.name}  ({exp.id[:6]})", file=sys.stderr)
        return exp

    # `sys.argv` shapes that are not a command anyone can re-run. Only the two
    # genuine argv *forms* are listed — `python -c "…"` and the bare REPL. Which
    # front end is running is answered structurally by `_in_ipython()` instead,
    # because a list of launcher *names* is a list of the front ends we happened
    # to know about: Jupyter, Colab, VS Code, papermill and qtconsole all launch
    # differently, and any one missing from such a list silently reintroduces
    # the bug (see `_build_command`).
    _NON_COMMAND_ARGV0 = frozenset({"-c", ""})

    @staticmethod
    def _in_ipython() -> bool:
        """True inside any live IPython front end (notebook, qtconsole, …).

        Asks `sys.modules` rather than importing IPython — it is an optional
        dependency and exptrack is stdlib-only. A script that merely imports
        IPython without starting a shell gets `get_ipython() is None`, which is
        the right answer for it.
        """
        ipy = sys.modules.get("IPython")
        try:
            return ipy is not None and ipy.get_ipython() is not None
        except Exception:
            return False

    @staticmethod
    def _build_command() -> str:
        """Build a clean command string from sys.argv, or "" if argv isn't one.

        Replaces the full path to the Python entry point (e.g.
        /Users/.../venv/bin/exptrack) with just the binary name.

        Under IPython `sys.argv` is the *kernel's* launch line, so a notebook run
        would otherwise record a Reproduce command like
        `ipykernel_launcher.py -f /tmp/kernel-1a2b.json` — a connection file
        deleted when the kernel stopped. It is unrunnable, and carries no
        `python`/`exptrack` prefix so the box cannot even offer its plain/tracked
        toggle. A blank command is better than a false one: the box then invites
        you to add the real one, and a notebook run falls back to its own path.
        """
        argv = list(sys.argv)
        if not argv or Experiment._in_ipython():
            return ""
        argv[0] = Path(argv[0]).name
        if argv[0] in Experiment._NON_COMMAND_ARGV0:
            return ""
        return " ".join(argv)

    def _resolved_command(self) -> str:
        """The command to record: explicit, else rebuilt from argv, else the
        notebook itself.

        Reproducing a notebook run means opening the notebook, and exptrack
        cannot know whether that is lab, notebook, nbclassic or an editor — so
        naming a launcher would be a guess printed as an instruction. The path
        is the honest answer, and it belongs here rather than at each notebook
        entry point, which had to repeat it verbatim.
        """
        cmd = self._command or self._build_command()
        if not cmd and (self.script or "").endswith(".ipynb"):
            return self.script
        return cmd

    # ── Snapshot dedup ─────────────────────────────────────────────────────

    def _compute_snapshot_hash(self) -> str:
        """Hash of script + params + git commit for dedup of unchanged re-runs."""
        h = hashlib.md5()
        h.update((self.script or "").encode())
        h.update(json.dumps(self._params, sort_keys=True, default=str).encode())
        h.update((self.git_commit or "").encode())
        return h.hexdigest()[:16]

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self):
        conn = get_db()
        # Compute initial output_dir path
        conf = cfg.load()
        self._output_dir = str(
            cfg.project_root() / conf.get("outputs_dir", "outputs") / self.name
        )
        # An earlier run on this connection may still hold metric rows inside
        # the commit-coalescing window (see _commit_metrics), and that leaves an
        # implicit transaction open — BEGIN IMMEDIATE below would then fail with
        # "cannot start a transaction within a transaction". Land them first.
        # (A no-op inside batched_writes(), which owns its own commit and never
        # marks metrics as pending.)
        _flush_live_runs()
        # Deduplicate git diff: store full text once, reference by hash
        diff_for_db = self.git_diff
        if diff_for_db:
            try:
                diff_for_db = store_git_diff(conn, diff_for_db)
                conn.commit()  # commit the dedup insert before main transaction
            except Exception:
                pass  # fall back to storing inline
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Upsert on the columns this method owns, rather than INSERT OR
            # REPLACE: OR REPLACE deletes the row and re-inserts it, so every
            # column absent from this list — duration_s, deleted_at, studies,
            # stage, stage_name, session_node_id — would be silently reset to
            # NULL by any re-save. Today _save runs once per run, which is the
            # only reason that never bit; the upsert makes it safe by
            # construction instead of by accident.
            conn.execute("""
                INSERT INTO experiments
                (id, project, name, status, created_at, updated_at,
                 script, command, git_branch, git_commit, git_diff,
                 hostname, python_ver, notes, tags, output_dir, name_is_auto)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  project=excluded.project, name=excluded.name,
                  status=excluded.status, updated_at=excluded.updated_at,
                  script=excluded.script, command=excluded.command,
                  git_branch=excluded.git_branch, git_commit=excluded.git_commit,
                  git_diff=excluded.git_diff, hostname=excluded.hostname,
                  python_ver=excluded.python_ver, notes=excluded.notes,
                  tags=excluded.tags, output_dir=excluded.output_dir,
                  name_is_auto=excluded.name_is_auto
            """, (
                self.id, self.project, self.name, self.status,
                self.created_at, self.created_at,
                self.script, self._resolved_command(),
                self.git_branch, self.git_commit, diff_for_db,
                self.hostname, self.python_ver,
                self.notes, json.dumps(self.tags),
                self._output_dir, int(getattr(self, "name_is_auto", True)),
            ))
            if self._params:
                self._write_params(conn, self._params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # Log output_dir as artifact so it's visible immediately
        try:
            self.log_artifact(self._output_dir, label="output_dir")
        except Exception as e:
            print(f"[exptrack] warning: could not log output_dir artifact: {e}", file=sys.stderr)

        self._maybe_snapshot_script()

    def _maybe_snapshot_script(self, script: str | None = None):
        """Snapshot the running script's source, if this run has a real one.

        Without this the code snapshot was captured *only* under
        ``exptrack run`` (``__main__`` called it explicitly), so a plain
        ``python train.py`` that builds its own ``Experiment()`` — and every
        shell-pipeline run — recorded no source at all. The consequence was a
        direct contradiction on screen: the "vs previous run" strip reports
        `code changed` from the repository-wide signature, which needs no
        snapshot, while the Code-changes panel right below it had nothing to
        diff and said no code was captured.

        This is the single entry point: ``__main__`` calls it too (passing the
        path it resolved, which ``Experiment.resume`` has no way to know), and
        ``_script_snapshotted`` makes a repeat call for the same file a no-op
        rather than a duplicate timeline event and a second set of params.
        Best-effort throughout — a capture failure must never break a run.
        """
        script = script or self.script
        # run-start passes a *label* ("pipeline", "train"), not a file; and a
        # notebook has no script file. Both are handled by other capture paths.
        if not script or not Path(script).is_file() or script.endswith(".ipynb"):
            return
        try:
            capture_script_snapshot(self, script)
        except Exception as e:
            debug_log(f"could not snapshot script {script}: {e}")

    def _maybe_commit(self, conn):
        """Commit unless we're inside a batched_writes() block."""
        if not self._defer_commit:
            conn.commit()

    @contextmanager
    def batched_writes(self):
        """Defer per-write commits, committing once when the block exits.

        `get_db()` returns one cached per-thread connection, so wrapping a burst
        of `log_event`/`log_params` calls in this collapses many commits (one
        fsync each) into a single commit. Nesting-safe: only the outermost block
        performs the final commit.
        """
        prev = self._defer_commit
        self._defer_commit = True
        try:
            yield
        finally:
            self._defer_commit = prev
            if not prev:
                try:
                    get_db().commit()
                except Exception as e:
                    print(f"[exptrack] warning: batched commit failed: {e}",
                          file=sys.stderr)

    def _write_params(self, conn, params: dict):
        # Warn on param overwrites with different values. Skip exptrack-internal
        # bookkeeping params (any "_"-prefixed key: _var/…, _code_change/…,
        # _cells_ran, _confusion_matrices) — same convention as naming.py — since
        # they legitimately change every cell; the warning is for real user HPs.
        for k, v in params.items():
            if k.startswith("_"):
                continue
            existing = conn.execute(
                "SELECT value FROM params WHERE exp_id=? AND key=?",
                (self.id, k)
            ).fetchone()
            if existing:
                old_val = json.loads(existing["value"])
                if old_val != v:
                    print(f"[exptrack] warning: param '{k}' overwritten: "
                          f"{old_val!r} -> {v!r}", file=sys.stderr)
        # Upsert (not INSERT OR REPLACE) so re-logging a key keeps its existing
        # `source` — OR REPLACE deletes the row and re-inserts, resetting a
        # 'manual' param back to the 'auto' column default.
        conn.executemany(
            "INSERT INTO params (exp_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT(exp_id, key) DO UPDATE SET value=excluded.value",
            [(self.id, k, json.dumps(v)) for k, v in params.items()]
        )

    def forget_params(self, keys):
        """Drop params this run should not have recorded, in memory and in the DB.

        Used by the capture layer to retract a raw-argv key once argparse has
        revealed it was the same hyperparameter under a different name (a
        ``--learning-rate`` flag whose ``dest`` is ``lr`` was stored twice, and
        two keys for one knob show up in "what varies" as two axes).
        """
        keys = [k for k in keys if k in self._params]
        if not keys:
            return
        for k in keys:
            self._params.pop(k, None)
        try:
            with get_db() as conn:
                conn.executemany(
                    "DELETE FROM params WHERE exp_id=? AND key=?",
                    [(self.id, k) for k in keys],
                )
                conn.commit()
        except Exception as e:
            debug_log(f"could not forget params {keys}: {e}")

    def refresh_auto_name(self, quiet: bool = False):
        """Re-generate this run's name now that its params are known.

        The auto-naming *policy*, on the object that owns ``name_is_auto``:
        a **resumed** run keeps its established name and output dir (the
        script may depend on both), and a run the user named keeps that name —
        regenerating over an explicit name replaced it with an auto one while
        still reporting the run as user-named. The rule lived in the argparse
        capture path with only half of it copied into the notebook path, so a
        resumed auto-named run renamed its output dir under a notebook and not
        under a script.
        """
        if getattr(self, "_resumed", False) or not getattr(self, "name_is_auto", True):
            return
        from .naming import make_run_name
        self._rename(make_run_name(self.script, self._params, uid=self.id[:8]),
                     quiet=quiet)

    def _rename(self, new_name: str, quiet: bool = False):
        """Update name in memory and DB (called after auto-capture fills params).

        Also renames the output folder on disk and updates artifact paths.
        """
        if new_name == self.name:
            return
        old_name = self.name
        self.name = new_name
        with get_db() as conn:
            conn.execute("UPDATE experiments SET name=? WHERE id=?", (new_name, self.id))
            moved = rename_output_folder(conn, self.id, old_name, new_name)
            conn.commit()
        if moved:
            self._output_dir = moved
        if not quiet:
            print(f"[exptrack] -> {self.name}", file=sys.stderr)

    # ── Params ────────────────────────────────────────────────────────────────

    def log_params(self, params: dict[str, Any]):
        if self._finished:
            print("[exptrack] warning: logging params after experiment finished",
                  file=sys.stderr)
            return
        params = _redact_params(params)
        self._params.update(params)
        conn = get_db()
        self._write_params(conn, params)
        self._maybe_commit(conn)

    def log_param(self, key: str, value: Any):
        self.log_params({key: value})

    # ── Tags & Notes ─────────────────────────────────────────────────────────

    def add_tag(self, tag: str):
        """Add a tag to this experiment."""
        if tag not in self.tags:
            self.tags.append(tag)
            conn = get_db()
            conn.execute("UPDATE experiments SET tags=? WHERE id=?",
                         (json.dumps(self.tags), self.id))
            self._maybe_commit(conn)

    def remove_tag(self, tag: str):
        """Remove a tag from this experiment."""
        self.tags = [t for t in self.tags if t != tag]
        conn = get_db()
        conn.execute("UPDATE experiments SET tags=? WHERE id=?",
                     (json.dumps(self.tags), self.id))
        self._maybe_commit(conn)

    def set_note(self, text: str):
        """Set (replace) the notes for this experiment."""
        self.notes = text
        conn = get_db()
        conn.execute("UPDATE experiments SET notes=? WHERE id=?",
                     (text, self.id))
        self._maybe_commit(conn)

    def add_note(self, text: str, dedupe: bool = False):
        """Append to the notes for this experiment.

        *dedupe* skips a line that is already present — what the notebook
        `%exp_note` magic needs to stay idempotent under a Run-All, without
        making the plain append-only form (used for timestamped trails) lossy.
        """
        if dedupe and text.strip() in (self.notes or "").splitlines():
            return
        self.notes = join_notes(self.notes, text)
        conn = get_db()
        conn.execute("UPDATE experiments SET notes=? WHERE id=?",
                     (self.notes, self.id))
        self._maybe_commit(conn)

    # ── Metrics ───────────────────────────────────────────────────────────────

    def _keep_every(self) -> int:
        """Write-time thinning factor: ``thin_every`` if set, else config."""
        keep_every = self._thin_every
        if keep_every is None:
            keep_every = cfg.load().get("metric_keep_every", 1)
        try:
            return max(1, int(keep_every))
        except (TypeError, ValueError, OverflowError):
            # OverflowError: json accepts 1e999 → float('inf'), and int(inf)
            # raises it — a hand-edited config must degrade, never crash logging.
            return 1

    def _keep_metric_point(self, key: str) -> bool:
        """Should this point be stored? Keeps 1 of every N *logged points*.

        The count is per metric key, and the first point of every key is always
        kept (count 0). This deliberately does NOT test the step value.

        It used to be ``step % keep_every == 0``, which silently assumes you log
        on every step. Log every 5th step (the common ``if (i+1) % 5 == 0``
        pattern) with ``keep_every=999`` and the two are coprime, so no step ever
        satisfies it and the run stores *nothing* — the setting reads as "thin
        this a bit" and acts as "discard everything". Even a friendly factor was
        wrong: ``keep_every=1000`` on a 200-step run kept only step 0. Counting
        points delivers what the setting has always claimed — every Nth point —
        for any logging cadence, and can never take a series to zero.
        """
        keep_every = self._keep_every()
        if keep_every <= 1:
            return True
        counts = self._metric_logged
        if counts is None:                  # resume/early path built us bare
            counts = self._metric_logged = {}
        n = counts.get(key, 0)
        counts[key] = n + 1
        if n % keep_every == 0:
            return True
        self._metric_dropped += 1
        # Thinning silently dropping data is what made this hard to diagnose:
        # the dashboard just showed an empty chart. Say it once per run.
        if not self._thin_notice_shown:
            self._thin_notice_shown = True
            print(f"[exptrack] metric thinning is on (keep_every={keep_every}): "
                  f"storing 1 of every {keep_every} points per metric. "
                  f"Set metric_keep_every to 1 to record every point.",
                  file=sys.stderr)
        return False

    def _print_thinning_summary(self):
        """One line at finish naming what thinning actually stored.

        The opening notice can only say the factor, and the factor is the thing
        being misread: ``metric_keep_every`` is *1 of every N*, not "keep N
        points", so a loop that already logs every 5th step and a config of
        1,000 store a handful of points from a long run — with a chart that
        looks like the run barely recorded anything and no number anywhere
        connecting the two. The counts are known by the time the run ends, so
        state them, and name the two non-destructive alternatives.
        """
        if not self._metric_dropped:
            return
        logged = sum((self._metric_logged or {}).values())
        stored = logged - self._metric_dropped
        print(f"[exptrack] metric thinning stored {stored:,} of {logged:,} points "
              f"logged (metric_keep_every={self._keep_every()} means 1 of every N, "
              f"not a target count). Set it to 1 to record every point; use "
              f"metric_max_points for chart resolution, or `exptrack prune` to "
              f"thin what is already stored.", file=sys.stderr)

    def _commit_metrics(self, conn):
        """Commit metric writes, but at most once per commit interval.

        Metrics are the one thing written in a tight loop: a 100k-iteration
        training run calls this 100k times, and every commit is an fsync. That
        made the commit ~96% of exptrack's write cost — 100k iterations logging
        5 metrics took 151s, against 6s when the same inserts are committed in
        batches. exptrack is supposed to be a passive observer of a training
        run, not two and a half minutes of it.

        Coalescing on *time* rather than a fixed count is what keeps the
        dashboard live: uncommitted rows aren't visible to the dashboard's
        separate connection, so a count-based batch would stall a slow run's
        chart for however long N iterations take, while a time-based one bounds
        the lag at the interval regardless of loop speed. The cost is symmetric
        and bounded: a run killed with `kill -9` loses at most that interval's
        metrics. Every ordinary exit path — `finish`, `fail`, the context
        manager, interpreter shutdown — flushes, and so does any other logging
        call, since committing the shared connection commits these too.

        `metric_commit_interval_ms: 0` in config restores a commit per call.
        """
        if self._defer_commit:
            return          # inside batched_writes(); that block owns the commit
        interval = self._metric_commit_interval_s
        if interval <= 0:
            conn.commit()
            return
        # perf_counter, not monotonic: on Windows monotonic advances in ~15.6ms
        # ticks, so two writes a few ms apart read as zero elapsed and a window
        # shorter than a tick never closed on time.
        now = time.perf_counter()
        if now - self._last_metric_commit >= interval:
            conn.commit()
            self._window_closed(now)
        else:
            self._metrics_uncommitted = True
            self._pending = (conn, conn.total_changes)
            self._arm_trailing_flush()

    def _arm_trailing_flush(self):
        """Make sure a deferred write is committed once its window has passed.

        Without this the window closed only when a *later* write arrived. A
        loop logging four metrics together every ten epochs committed the
        first and left the other three invisible to the dashboard until the
        next burst — so the chart showed ``loss`` alone at epoch 10, and at
        epoch 20 the other three at 10. Caller holds `_metric_commit_lock`.
        """
        if self in _flush_due:
            return
        _flush_due[self] = self._last_metric_commit + self._metric_commit_interval_s
        _ensure_flusher()
        _flush_cv.notify()

    def _window_closed(self, now: float) -> None:
        """Book-keeping for a commit that closed this run's window. Holds the lock."""
        self._metrics_uncommitted = False
        self._last_metric_commit = now
        self._pending = None
        _flush_due.pop(self, None)

    def _commit_pending_window(self) -> None:
        """The flusher's commit. Runs on its thread, under the lock.

        Commits the connection only if the transaction still holds exactly the
        rows this run's metric writes left there: ``total_changes`` unchanged
        since the last deferred insert. Anything else written on that
        connection since means the open transaction is no longer only ours —
        committing it here would split another writer's unit of work — and
        that writer's own commit lands our rows with it.
        """
        if not self._metrics_uncommitted or self._pending is None:
            return
        conn, changes = self._pending
        try:
            if not conn.in_transaction or conn.total_changes != changes:
                return
            conn.commit()
        except Exception as e:      # closed or switched under us: not ours now
            debug_log(f"metrics: trailing flush skipped: {e}")
            return
        self._window_closed(time.perf_counter())

    def _tick_commit_window(self):
        """Flush a pending coalescing window from a call that stored nothing.

        A thinned-away point (or an all-non-finite `log_metrics`) writes no row,
        but an *earlier* kept point may still be sitting uncommitted — and with
        `metric_keep_every: 1000` the next call that would flush it is a thousand
        iterations away, leaving it invisible to the dashboard's separate
        connection for that whole stretch.

        Deliberately checks the window against instance state *before* touching
        the DB layer: `get_db()` re-derives the path, `mkdir`s the parent and
        runs a `SELECT 1` liveness probe on every call, so calling it per dropped
        point put a syscall and a round trip on the one path that is supposed to
        be nearly free (~99k of each on a 100k-iteration run thinned at 100).
        """
        if not self._metrics_uncommitted or self._metric_commit_interval_s <= 0:
            return
        if time.perf_counter() - self._last_metric_commit >= self._metric_commit_interval_s:
            self.flush_metrics()

    def flush_metrics(self):
        """Commit any metric rows still held by the coalescing window above."""
        with _metric_commit_lock:
            if not self._metrics_uncommitted:
                return
            self._window_closed(time.perf_counter())
            flush_pending()

    def log_metric(self, key: str, value: float, step: int | None = None):
        if self._finished:
            print(f"[exptrack] warning: logging metric '{key}' after experiment finished",
                  file=sys.stderr)
            return
        fval = float(value)
        if not math.isfinite(fval):
            print(f"[exptrack] warning: metric '{key}' has non-finite value: {fval} — skipping",
                  file=sys.stderr)
            self._tick_commit_window()   # same as an all-non-finite log_metrics
            return
        if not self._keep_metric_point(key):
            self._tick_commit_window()
            return
        ts = datetime.now(timezone.utc).isoformat()
        node_id = _active_session_node(self)
        # NB: `conn = get_db()`, not `with get_db() as conn:` — sqlite3's
        # connection context manager commits on exit, which would defeat both
        # the coalescing below and batched_writes(). Same reason log_params
        # takes the connection directly.
        conn = get_db()
        with _metric_commit_lock:   # the trailing flush must not split these
            conn.execute(
                "INSERT INTO metrics (exp_id, key, value, step, ts, session_node_id) "
                "VALUES (?,?,?,?,?,?)",
                (self.id, key, fval, step, ts, node_id)
            )
            self._commit_metrics(conn)
        plugins.on_metric(self, key, value, step)

    def log_metrics(self, metrics: dict[str, float], step: int | None = None):
        if self._finished:
            print("[exptrack] warning: logging metrics after experiment finished",
                  file=sys.stderr)
            return
        ts = datetime.now(timezone.utc).isoformat()
        node_id = _active_session_node(self)
        finite_metrics = {}
        for k, v in metrics.items():
            fv = float(v)
            if not math.isfinite(fv):
                print(f"[exptrack] warning: metric '{k}' has non-finite value: {fv} — skipping",
                      file=sys.stderr)
                continue
            # Per key, not once for the dict: each key carries its own count, so
            # a caller logging {loss, acc} together thins both identically while
            # a key logged on only some calls still keeps every Nth of its own.
            if not self._keep_metric_point(k):
                continue
            finite_metrics[k] = fv
        if not finite_metrics:
            self._tick_commit_window()      # see the note on _tick_commit_window
            return
        conn = get_db()   # not `with` — see the note in log_metric
        with _metric_commit_lock:
            conn.executemany(
                "INSERT INTO metrics (exp_id, key, value, step, ts, session_node_id) "
                "VALUES (?,?,?,?,?,?)",
                [(self.id, k, v, step, ts, node_id)
                 for k, v in finite_metrics.items()]
            )
            self._commit_metrics(conn)
        for k, v in finite_metrics.items():
            plugins.on_metric(self, k, v, step)

    def last_metrics(self) -> dict:
        """Latest value of every metric key for this run."""
        from .queries import last_metrics
        # Read-only: use the shared connection directly (no `with`, which would
        # commit an empty transaction on exit for a SELECT-only body).
        return last_metrics(get_db(), self.id)

    # ── Artifacts / outputs ───────────────────────────────────────────────────

    def output_path(self, filename: str) -> Path:
        """
        Get a namespaced output path for this run.
        outputs/<run_name>/<filename>
        Does NOT register as artifact — use save_output() for that.

        The run's *recorded* output dir wins over its name: a rename that could
        not move the folder (Windows refuses while the tee'd stdout/stderr logs
        are open in it) leaves the run on its first folder, and writing to
        `outputs/<new name>/` split one run's files across two directories.
        """
        recorded = getattr(self, "_output_dir", "")
        if recorded:
            d = Path(recorded)
            d.mkdir(parents=True, exist_ok=True)
            return d / filename
        return output_path(filename, self.name)

    def save_output(self, filename: str) -> Path:
        """Get namespaced path AND register as artifact. Use this for model files, CSVs, etc."""
        p = self.output_path(filename)
        self.log_artifact(p, label=filename)
        return p

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _scan_output_dir(self):
        """Walk output_dir and register any files as artifacts (reference only)."""
        out_dir = getattr(self, '_output_dir', None)
        if not out_dir:
            return
        out_path = Path(out_dir)
        if not out_path.is_dir():
            return
        hidden = {'.exptrack_run.env', '.DS_Store'}
        new_files = []
        for p in out_path.rglob('*'):
            if not p.is_file():
                continue
            if p.name.startswith('.') or p.name in hidden:
                continue
            new_files.append(p)
        if not new_files:
            return
        for p in new_files:
            try:
                self.log_artifact(str(p))
            except Exception as e:
                print(f"[exptrack] warning: could not log artifact {p}: {e}", file=sys.stderr)
        if len(new_files) <= 5:
            for p in new_files:
                print(f"[exptrack] artifact: {p}", file=sys.stderr)
        else:
            print(f"[exptrack] {len(new_files)} artifacts in {out_dir}/", file=sys.stderr)

    def finish(self, status: str = "done"):
        if self._finished:
            raise RuntimeError(
                f"Experiment {self.id[:6]} already finished with status='{self.status}'. "
                "Cannot finish twice."
            )
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {_VALID_STATUSES}"
            )
        # Land any metrics still inside the coalescing window before anything
        # here can raise — the run's last points must not depend on the rest of
        # finish() succeeding.
        self.flush_metrics()
        # Snapshot the project-local modules this run imported. Here rather than
        # in the constructor because the imports have happened by now — and for
        # every status, since a crashed run's code is exactly what you want to
        # read. Must precede `_finished`: it calls log_param.
        try:
            from .script_snapshot import capture_module_snapshots
            capture_module_snapshots(self)
        except Exception as e:
            from .utils import debug_log
            debug_log(f"module capture failed: {e}")
        # The library versions it ran with, for the same reason and at the same
        # point: `sys.modules` now holds everything the run imported.
        if (cfg.load().get("auto_capture") or {}).get("environment", True):
            try:
                from .environment import capture_environment
                capture_environment(self)
            except Exception as e:
                from .utils import debug_log
                debug_log(f"environment capture failed: {e}")
        # Fingerprint any dataset-shaped params before locking the run, so it
        # runs for every finish path (scripts, notebooks, programmatic), not just
        # `exptrack run`. Must precede `_finished` since it calls log_params.
        if status == "done":
            from .dataset import capture_dataset_manifest
            capture_dataset_manifest(self)
            # After the manifest, so the notice can say whether the data moved.
            self._warn_if_duplicate()
        self._finished = True
        # `duration_s` is **wall time this run was actually running, summed
        # across resumes** — not elapsed-since-creation, which for a run resumed
        # the next morning would report the night as compute time, and not
        # this-session-only, which silently discarded every earlier session's
        # work. The two finish paths (here and `run-finish`) disagreed on which
        # of those it meant; both now accumulate.
        self.duration_s = self._accumulated_duration(time.time() - self._start)
        self.status = status
        _live_runs.discard(self)   # already flushed above; nothing left to do at exit

        # Scan output_dir for artifacts before closing
        self._scan_output_dir()

        with get_db() as conn:
            conn.execute("""
                UPDATE experiments
                SET status=?, updated_at=?, duration_s=?, name=?
                WHERE id=?
            """, (status, datetime.now(timezone.utc).isoformat(), self.duration_s, self.name, self.id))
            conn.commit()
        m, s = divmod(self.duration_s, 60)
        icon = "done" if status == "done" else "FAILED"
        print(f"[exptrack] {icon}: {self.name}  ({int(m)}m {s:.1f}s)", file=sys.stderr)
        safe_call(self._print_thinning_summary, context="thinning summary")
        # "What changed since last time" — compare to the previous run of the
        # same script and print a one-line delta. Best-effort; never blocks
        # finishing a run.
        try:
            self._print_delta_vs_previous()
        except Exception as e:
            from .utils import debug_log
            debug_log(f"delta-vs-previous failed: {e}")
        if status == "done":
            plugins.on_finish(self)
        else:
            plugins.on_fail(self, self._params.get("error", ""))
            # Optionally move a broken run straight to Trash so it never needs
            # remembering to delete. Soft (recoverable); opt-in via config.
            if cfg.load().get("auto_trash_failed", False):
                try:
                    with get_db() as conn:
                        from .db import trash_experiment
                        trash_experiment(conn, self.id)
                        conn.commit()
                    print(f"[exptrack] moved failed run to Trash ({self.id[:6]})",
                          file=sys.stderr)
                except Exception as e:
                    print(f"[exptrack] warning: could not auto-trash failed run: {e}",
                          file=sys.stderr)

        # Checkpoint and close the DB connection so the WAL doesn't grow
        # unbounded across runs (especially in notebooks and scripts).
        # Done after plugin hooks so they can still write to the DB.
        # sweep=False: finishing a run can't orphan rows, and the orphan
        # sweep's anti-join scans grow with metrics/timeline size — skip it
        # on this per-run hot path (CLI exit / `exptrack clean` still sweep).
        from .db import close_db
        close_db(sweep=False)

    def _warn_if_duplicate(self):
        """Print the "already run" notice, if this run repeats a configuration.

        A one-line stderr notice, never a prompt and never a refusal:
        re-running a configuration is often deliberate (a seed check, a flaky
        result, a changed machine), so blocking on a heuristic would be wrong.
        The value is in noticing the *accidental* repeat, and for that being
        told once is enough.

        The policy and wording live in ``core/param_study.duplicate_notice``;
        this is the lifecycle hook. Best-effort — it sits on the finish path of
        every run, and an advisory must never be able to break one.
        """
        if getattr(self, "_resumed", False):
            return
        try:
            from . import param_study
            msg = param_study.duplicate_notice(
                get_db(), self.id, dict(self._params or {}), self.script or "")
            if msg:
                print(f"[exptrack] {msg}", file=sys.stderr)
        except Exception as e:
            debug_log(f"duplicate check failed: {e}")

    def _print_delta_vs_previous(self):
        """Print a one-line 'what changed vs the previous run of this script'
        summary to stderr. Silent when there's no previous run or no change."""
        from .queries import ARG_ERROR_KEY, diff_runs, format_run_delta, get_previous_run
        if self._params.get(ARG_ERROR_KEY):
            return  # never ran: its params are a raw-argv guess, not a config
        conn = get_db()
        prev = get_previous_run(conn, self.id)
        if not prev:
            return
        diff = diff_runs(conn, prev["id"], self.id)
        line = format_run_delta(diff, prev)
        if line:
            print(f"[exptrack] {line}", file=sys.stderr)

    def fail(self, error: str = "", traceback: str | None = None,
             interrupted: bool = False):
        """Mark the run as failed.

        ``error`` is the short exception message (stored as the ``error``
        param, kept for backward compat). ``traceback`` is the full formatted
        traceback (file + line); it's stored as the ``_error_traceback`` param
        — ``_``-prefixed so it's skipped by run-naming and the param
        overwrite-warning — and surfaced as a dedicated panel on failed runs in
        the dashboard. Capped so a pathological traceback can't bloat the DB.

        ``interrupted`` marks a deliberate Ctrl-C rather than a crash; see the
        note below for why that is a param and not a fourth status.
        """
        if error:
            self.log_param("error", error)
        if interrupted:
            # A deliberate Ctrl-C and a crash are different facts, but they are
            # both "this run did not produce a result", so the *status* stays
            # `failed` — every filter, baseline rule and cleanup path that
            # already understands `failed` keeps working. The distinction is
            # recorded beside it so the surfaces that show a reason can say
            # "interrupted" instead of implying the code broke.
            self.log_param("_interrupted", True)
        if traceback:
            if len(traceback) > _MAX_TRACEBACK_CHARS:
                traceback = "…(truncated)\n" + traceback[-_MAX_TRACEBACK_CHARS:]
            self.log_param("_error_traceback", traceback)
        self.finish("failed")

    # ── Timeline ──────────────────────────────────────────────────────────────

    _timeline_seq: int = 0

    def reserve_timeline_seq(self) -> int:
        """Claim the next timeline seq without writing an event yet.

        Used by the notebook pre_run_cell hook to reserve the cell_exec event's
        position BEFORE the cell body runs, so any artifacts saved mid-cell
        (e.g. plt.savefig) get a LATER seq and sort *below* the code in the
        timeline rather than above it. Pass the reserved value back as
        ``log_event(..., seq=reserved)``.
        """
        self._timeline_seq += 1
        return self._timeline_seq

    def log_event(self, event_type: str, cell_hash: str | None = None,
                  cell_pos: int | None = None, key: str | None = None, value: Any | None = None,
                  prev_value: Any | None = None, source_diff: str | None = None,
                  seq: int | None = None) -> int:
        """
        Append an event to the execution timeline.

        event_type: 'cell_exec' | 'var_set' | 'artifact' | 'metric' | 'observational'
        seq: optional pre-reserved seq (see reserve_timeline_seq); when omitted a
             fresh seq is allocated.
        Returns the seq number of this event.
        """
        if seq is None:
            self._timeline_seq += 1
            seq = self._timeline_seq
        ts = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        conn.execute(
            """INSERT INTO timeline
               (exp_id, seq, event_type, cell_hash, cell_pos,
                key, value, prev_value, source_diff, ts)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (self.id, seq, event_type, cell_hash, cell_pos, key,
             json.dumps(value, default=str) if value is not None else None,
             json.dumps(prev_value, default=str) if prev_value is not None else None,
             source_diff, ts)
        )
        self._maybe_commit(conn)
        return seq

    def log_artifact(self, path: str | Path, label: str = "",
                     timeline_seq: int | None = None, content_hash: str | None = None):
        """Register an output file path (the file itself stays local).

        Deduplicates by resolved path — if the same file is already registered
        on this experiment the call is a no-op (prevents double-logging from
        savefig patch + auto-detect).

        Computes a SHA-256 content hash for integrity verification.  For very
        large files the hash covers only the first ``hash_max_mb`` MB (see
        config) and is prefixed with ``partial:``.
        """
        from .db import register_artifact
        with get_db() as conn:
            register_artifact(conn, self.id, path, label=label,
                              timeline_seq=timeline_seq, content_hash=content_hash)
            conn.commit()

    def log_file(self, path, label="", category=""):
        """Log any output file as an artifact with auto-detected category."""
        p = Path(str(path)).resolve()
        if not p.exists():
            return
        if not category:
            ext = p.suffix.lower()
            if ext in ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.pdf', '.bmp', '.tiff'):
                category = 'image'
            elif ext in ('.pt', '.pth', '.h5', '.hdf5', '.onnx', '.pkl', '.joblib', '.safetensors'):
                category = 'model'
            elif ext in ('.csv', '.json', '.jsonl', '.parquet', '.tsv', '.npy', '.npz'):
                category = 'data'
            elif ext in ('.log', '.txt', '.out', '.err'):
                category = 'log'
            else:
                category = 'file'
        if not label:
            label = f"[{category}] {p.name}"
        self.log_artifact(str(p), label=label)

    def get_variable_context(self, at_seq: int | None = None) -> dict:
        """
        Reconstruct the variable state at a given timeline seq by walking
        backward through var_set events.  If at_seq is None, returns the
        current (latest) state.
        """
        where = "WHERE exp_id=? AND event_type='var_set'"
        params: list = [self.id]
        if at_seq is not None:
            where += " AND seq <= ?"
            params.append(at_seq)
        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT key, value FROM timeline {where}
                    ORDER BY seq DESC""",
                params,
            ).fetchall()
        # Latest value per key (first seen wins since DESC order)
        ctx: dict = {}
        for r in rows:
            if r["key"] not in ctx:
                ctx[r["key"]] = json.loads(r["value"]) if r["value"] else None
        return ctx

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Guarded like every finish path in __main__: a script may finish()
        # explicitly inside the with-block, and finish() raises on a second
        # call — unguarded, a clean block crashed at exit and, worse, in the
        # exception branch the RuntimeError from fail() replaced the user's
        # real exception as the one propagating.
        if exc_type is not None:
            if not self._finished:
                tb = "".join(_tb.format_exception(exc_type, exc_val, exc_tb))
                # Ctrl-C reaches here too — `KeyboardInterrupt` is a
                # BaseException, but `with` still calls __exit__ for it. It was
                # recorded as a crash with an empty message, so "I stopped this"
                # and "this broke" were only distinguishable under
                # `exptrack run`, which has its own handler.
                self.fail(str(exc_val), traceback=tb,
                          interrupted=exc_type is KeyboardInterrupt)
            return False
        if not self._finished:
            self.finish()
        return False
