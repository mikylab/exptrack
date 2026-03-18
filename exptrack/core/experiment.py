"""
exptrack/core/experiment.py — Experiment class

One Experiment = one run of a script or a notebook session.
Captures: params, metrics, git state (branch + uncommitted diff),
output file paths, and fires plugin hooks on lifecycle events.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re as _re
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config as cfg
from ..plugins import registry as plugins
from .db import get_db, rename_output_folder, store_git_diff
from .git import git_info
from .naming import make_run_name, output_path

_VALID_STATUSES = {"running", "done", "failed"}


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
    except Exception:
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

    def __init__(
        self,
        name: str = "",
        params: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        notes: str = "",
        script: str = "",
        _caller_depth: int = 1,
    ):
        conf          = cfg.load()
        self._start   = time.time()
        self._params: dict[str, Any] = dict(params or {})
        self.tags     = list(tags or [])
        self.notes    = notes
        self.status   = "running"
        self.duration_s: float | None = None

        # Detect caller script if not given
        if not script:
            try:
                frame = sys._getframe(_caller_depth)
                script = frame.f_globals.get("__file__", "") or sys.argv[0]
            except Exception:
                script = sys.argv[0]  # frame detection failed, fall back to argv
        # Resolve to absolute path if it looks like a real file path;
        # keep labels (e.g. "pipeline", "train") as-is from run-start
        if script and (Path(script).is_file() or os.path.sep in script or script.startswith("/")):
            self.script = str(Path(script).resolve())
        else:
            self.script = script

        # Build initial name (may be updated after argparse capture)
        self.name = name or make_run_name(script, self._params)

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
        self.id         = uuid.uuid4().hex[:12]
        self._finished  = False
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.project    = conf.get("project", cfg.project_root().name)

        # Deduplicate: skip snapshot if this script+params hash was already saved
        self._snapshot_hash = self._compute_snapshot_hash()

        self._save()
        plugins.load_from_config(conf)
        plugins.on_start(self)

        print(f"[exptrack] {self.name}  ({self.id[:6]})", file=sys.stderr)

    @staticmethod
    def _build_command() -> str:
        """Build a clean command string from sys.argv.

        Replaces the full path to the Python entry point (e.g.
        /Users/.../venv/bin/exptrack) with just the binary name.
        """
        argv = list(sys.argv)
        if argv:
            argv[0] = Path(argv[0]).name
        return " ".join(argv)

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
            conn.execute("""
                INSERT OR REPLACE INTO experiments
                (id, project, name, status, created_at, updated_at,
                 script, command, git_branch, git_commit, git_diff,
                 hostname, python_ver, notes, tags, output_dir)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                self.id, self.project, self.name, self.status,
                self.created_at, self.created_at,
                self.script, self._build_command(),
                self.git_branch, self.git_commit, diff_for_db,
                self.hostname, self.python_ver,
                self.notes, json.dumps(self.tags),
                self._output_dir,
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

    def _write_params(self, conn, params: dict):
        # Warn on param overwrites with different values
        for k, v in params.items():
            existing = conn.execute(
                "SELECT value FROM params WHERE exp_id=? AND key=?",
                (self.id, k)
            ).fetchone()
            if existing:
                old_val = json.loads(existing["value"])
                if old_val != v:
                    print(f"[exptrack] warning: param '{k}' overwritten: "
                          f"{old_val!r} -> {v!r}", file=sys.stderr)
        conn.executemany(
            "INSERT OR REPLACE INTO params (exp_id, key, value) VALUES (?,?,?)",
            [(self.id, k, json.dumps(v)) for k, v in params.items()]
        )

    def _rename(self, new_name: str):
        """Update name in memory and DB (called after auto-capture fills params).

        Also renames the output folder on disk and updates artifact paths.
        """
        if new_name == self.name:
            return
        old_name = self.name
        self.name = new_name
        with get_db() as conn:
            conn.execute("UPDATE experiments SET name=? WHERE id=?", (new_name, self.id))
            rename_output_folder(conn, self.id, old_name, new_name)
            conn.commit()
        print(f"[exptrack] -> {self.name}", file=sys.stderr)

    # ── Params ────────────────────────────────────────────────────────────────

    def log_params(self, params: dict[str, Any]):
        if self._finished:
            print("[exptrack] warning: logging params after experiment finished",
                  file=sys.stderr)
            return
        params = _redact_params(params)
        self._params.update(params)
        with get_db() as conn:
            self._write_params(conn, params)
            conn.commit()

    def log_param(self, key: str, value: Any):
        self.log_params({key: value})

    # ── Tags & Notes ─────────────────────────────────────────────────────────

    def add_tag(self, tag: str):
        """Add a tag to this experiment."""
        if tag not in self.tags:
            self.tags.append(tag)
            with get_db() as conn:
                conn.execute("UPDATE experiments SET tags=? WHERE id=?",
                             (json.dumps(self.tags), self.id))
                conn.commit()

    def remove_tag(self, tag: str):
        """Remove a tag from this experiment."""
        self.tags = [t for t in self.tags if t != tag]
        with get_db() as conn:
            conn.execute("UPDATE experiments SET tags=? WHERE id=?",
                         (json.dumps(self.tags), self.id))
            conn.commit()

    def set_note(self, text: str):
        """Set (replace) the notes for this experiment."""
        self.notes = text
        with get_db() as conn:
            conn.execute("UPDATE experiments SET notes=? WHERE id=?",
                         (text, self.id))
            conn.commit()

    def add_note(self, text: str):
        """Append to the notes for this experiment."""
        self.notes = ((self.notes or "") + "\n" + text).strip()
        with get_db() as conn:
            conn.execute("UPDATE experiments SET notes=? WHERE id=?",
                         (self.notes, self.id))
            conn.commit()

    # ── Metrics ───────────────────────────────────────────────────────────────

    def log_metric(self, key: str, value: float, step: int | None = None):
        if self._finished:
            print(f"[exptrack] warning: logging metric '{key}' after experiment finished",
                  file=sys.stderr)
        fval = float(value)
        if not math.isfinite(fval):
            print(f"[exptrack] warning: metric '{key}' has non-finite value: {fval}",
                  file=sys.stderr)
        ts = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)",
                (self.id, key, fval, step, ts)
            )
            conn.commit()
        plugins.on_metric(self, key, value, step)

    def log_metrics(self, metrics: dict[str, float], step: int | None = None):
        if self._finished:
            print("[exptrack] warning: logging metrics after experiment finished",
                  file=sys.stderr)
        ts = datetime.now(timezone.utc).isoformat()
        for k, v in metrics.items():
            fv = float(v)
            if not math.isfinite(fv):
                print(f"[exptrack] warning: metric '{k}' has non-finite value: {fv}",
                      file=sys.stderr)
        with get_db() as conn:
            conn.executemany(
                "INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)",
                [(self.id, k, float(v), step, ts) for k, v in metrics.items()]
            )
            conn.commit()
        for k, v in metrics.items():
            plugins.on_metric(self, k, v, step)

    def last_metrics(self) -> dict:
        """Latest value of every metric key for this run."""
        with get_db() as conn:
            rows = conn.execute("""
                SELECT key, value FROM metrics
                WHERE exp_id=?
                GROUP BY key HAVING MAX(COALESCE(step, 0))
            """, (self.id,)).fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── Artifacts / outputs ───────────────────────────────────────────────────

    def output_path(self, filename: str) -> Path:
        """
        Get a namespaced output path for this run.
        outputs/<run_name>/<filename>
        Does NOT register as artifact — use save_output() for that.
        """
        return output_path(filename, self.name)

    def save_output(self, filename: str) -> Path:
        """Get namespaced path AND register as artifact. Use this for model files, CSVs, etc."""
        p = output_path(filename, self.name)
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
        self._finished = True
        self.duration_s = time.time() - self._start
        self.status = status

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
        if status == "done":
            plugins.on_finish(self)
        else:
            plugins.on_fail(self, self._params.get("error", ""))

        # Checkpoint and close the DB connection so the WAL doesn't grow
        # unbounded across runs (especially in notebooks and scripts).
        # Done after plugin hooks so they can still write to the DB.
        from .db import close_db
        close_db()

    def fail(self, error: str = ""):
        if error:
            self.log_param("error", error)
        self.finish("failed")

    # ── Timeline ──────────────────────────────────────────────────────────────

    _timeline_seq: int = 0

    def log_event(self, event_type: str, cell_hash: str | None = None,
                  cell_pos: int | None = None, key: str | None = None, value: Any | None = None,
                  prev_value: Any | None = None, source_diff: str | None = None) -> int:
        """
        Append an event to the execution timeline.

        event_type: 'cell_exec' | 'var_set' | 'artifact' | 'metric' | 'observational'
        Returns the seq number of this event.
        """
        self._timeline_seq += 1
        seq = self._timeline_seq
        ts = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
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
            conn.commit()
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
        resolved = str(Path(str(path)).resolve())
        ts = datetime.now(timezone.utc).isoformat()

        # Compute content hash if not provided and file exists
        size_bytes = None
        if content_hash is None:
            rp = Path(resolved)
            if rp.is_file():
                try:
                    from .. import config as _cfg
                    from .hashing import file_hash
                    conf = _cfg.load()
                    max_bytes = int(conf.get("hash_max_mb", 500)) * 1024 * 1024
                    content_hash, size_bytes = file_hash(rp, max_bytes=max_bytes)
                except Exception as e:
                    print(f"[exptrack] warning: could not hash artifact {resolved}: {e}", file=sys.stderr)

        with get_db() as conn:
            existing = conn.execute(
                "SELECT id FROM artifacts WHERE exp_id=? AND path=?",
                (self.id, resolved)
            ).fetchone()
            if existing:
                return
            conn.execute(
                """INSERT INTO artifacts
                   (exp_id, label, path, created_at, timeline_seq,
                    content_hash, size_bytes)
                   VALUES (?,?,?,?,?,?,?)""",
                (self.id, label or Path(path).name, resolved, ts,
                 timeline_seq, content_hash, size_bytes)
            )
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
        if exc_type is not None:
            self.fail(str(exc_val))
            return False
        self.finish()
        return False
