"""
exptrack/core.py — Experiment class

One Experiment = one run of a script or a notebook session.
Captures: params, metrics, git state (branch + uncommitted diff),
output file paths, and fires plugin hooks on lifecycle events.
"""
from __future__ import annotations
import json
import os
import platform
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config as cfg
from .plugins import registry as plugins


# ── Database ──────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    root = cfg.project_root()
    conf = cfg.load()
    p = root / conf.get("db", ".exptrack/experiments.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS experiments (
            id          TEXT PRIMARY KEY,
            project     TEXT,
            name        TEXT NOT NULL,
            status      TEXT DEFAULT 'running',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            script      TEXT,
            command     TEXT,
            git_branch  TEXT,
            git_commit  TEXT,
            git_diff    TEXT,
            hostname    TEXT,
            python_ver  TEXT,
            duration_s  REAL,
            notes       TEXT,
            tags        TEXT
        );
        CREATE TABLE IF NOT EXISTS params (
            exp_id  TEXT NOT NULL REFERENCES experiments(id),
            key     TEXT NOT NULL,
            value   TEXT,
            PRIMARY KEY (exp_id, key)
        );
        CREATE TABLE IF NOT EXISTS metrics (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id  TEXT NOT NULL REFERENCES experiments(id),
            key     TEXT NOT NULL,
            value   REAL,
            step    INTEGER,
            ts      TEXT
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id      TEXT NOT NULL REFERENCES experiments(id),
            label       TEXT,
            path        TEXT,
            created_at  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_exp ON metrics(exp_id, key);
        CREATE INDEX IF NOT EXISTS idx_params_exp  ON params(exp_id);
    """)
    conn.commit()


# ── Git ───────────────────────────────────────────────────────────────────────

def _git(*cmd) -> str:
    try:
        r = subprocess.run(["git", *cmd], capture_output=True, text=True, timeout=10,
                           cwd=str(cfg.project_root()))
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def git_info() -> dict:
    return {
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_diff":   _git("diff", "HEAD"),   # captures ALL uncommitted changes
    }


# ── Run naming ────────────────────────────────────────────────────────────────

def make_run_name(script: str = "", params: dict = None) -> str:
    """
    Produces:   train__lr0.01_bs32__0312_a3f2
    Script stem + top N params + date + short uid.
    Always unique, always tells you what it was.
    """
    ncfg     = cfg.load().get("naming", {})
    max_keys = ncfg.get("max_param_keys", 4)
    key_len  = ncfg.get("key_max_len", 8)

    base  = Path(script).stem if script else "exp"
    parts = []
    if params:
        for k, v in list(params.items())[:max_keys]:
            short_k = k.split(".")[-1][:key_len]
            if isinstance(v, float):
                parts.append(f"{short_k}{v:.3g}")
            elif isinstance(v, bool):
                parts.append(f"{short_k}{int(v)}")
            else:
                parts.append(f"{short_k}{str(v)[:12]}")

    uid   = uuid.uuid4().hex[:4]
    today = datetime.now().strftime("%m%d")
    name  = base
    if parts:
        name += "__" + "_".join(parts)
    name += f"__{today}_{uid}"
    return name


def output_path(filename: str, exp_name: str = "") -> Path:
    """Return outputs/<exp_name>/<filename>, creating dirs as needed."""
    conf = cfg.load()
    base = cfg.project_root() / conf.get("outputs_dir", "outputs")
    if exp_name:
        base = base / exp_name
    base.mkdir(parents=True, exist_ok=True)
    return base / filename


# ── Experiment ────────────────────────────────────────────────────────────────

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
        params: dict[str, Any] = None,
        tags: list[str] = None,
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
                script = sys.argv[0]
        self.script = str(Path(script).resolve()) if script else ""

        # Build initial name (may be updated after argparse capture)
        self.name = name or make_run_name(script, self._params)

        # Snapshot git state at run time — this is the key traceability link
        ginfo = git_info()
        self.git_branch = ginfo["git_branch"]
        self.git_commit = ginfo["git_commit"]
        self.git_diff   = ginfo["git_diff"]   # full uncommitted diff

        self.hostname   = socket.gethostname()
        self.python_ver = platform.python_version()
        self.id         = uuid.uuid4().hex[:12]
        self.created_at = datetime.utcnow().isoformat()
        self.project    = conf.get("project", cfg.project_root().name)

        self._save()
        plugins.load_from_config(conf)
        plugins.on_start(self)

        print(f"[exptrack] {self.name}  ({self.id[:6]})", file=sys.stderr)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self):
        with get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO experiments
                (id, project, name, status, created_at, updated_at,
                 script, command, git_branch, git_commit, git_diff,
                 hostname, python_ver, notes, tags)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                self.id, self.project, self.name, self.status,
                self.created_at, self.created_at,
                self.script, " ".join(sys.argv),
                self.git_branch, self.git_commit, self.git_diff,
                self.hostname, self.python_ver,
                self.notes, json.dumps(self.tags),
            ))
            if self._params:
                self._write_params(conn, self._params)
            conn.commit()

    def _write_params(self, conn, params: dict):
        conn.executemany(
            "INSERT OR REPLACE INTO params (exp_id, key, value) VALUES (?,?,?)",
            [(self.id, k, json.dumps(v)) for k, v in params.items()]
        )

    def _rename(self, new_name: str):
        """Update name in memory and DB (called after auto-capture fills params)."""
        if new_name == self.name:
            return
        self.name = new_name
        with get_db() as conn:
            conn.execute("UPDATE experiments SET name=? WHERE id=?", (new_name, self.id))
            conn.commit()
        print(f"[exptrack] -> {self.name}", file=sys.stderr)

    # ── Params ────────────────────────────────────────────────────────────────

    def log_params(self, params: dict[str, Any]):
        self._params.update(params)
        with get_db() as conn:
            self._write_params(conn, params)
            conn.commit()

    def log_param(self, key: str, value: Any):
        self.log_params({key: value})

    # ── Metrics ───────────────────────────────────────────────────────────────

    def log_metric(self, key: str, value: float, step: int = None):
        ts = datetime.utcnow().isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)",
                (self.id, key, float(value), step, ts)
            )
            conn.commit()
        plugins.on_metric(self, key, value, step)

    def log_metrics(self, metrics: dict[str, float], step: int = None):
        ts = datetime.utcnow().isoformat()
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

    def log_artifact(self, path: str | Path, label: str = ""):
        """Register an output file path (the file itself stays local)."""
        ts = datetime.utcnow().isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
                (self.id, label or Path(path).name, str(path), ts)
            )
            conn.commit()

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

    def finish(self, status: str = "done"):
        self.duration_s = time.time() - self._start
        self.status = status
        with get_db() as conn:
            conn.execute("""
                UPDATE experiments
                SET status=?, updated_at=?, duration_s=?, name=?
                WHERE id=?
            """, (status, datetime.utcnow().isoformat(), self.duration_s, self.name, self.id))
            conn.commit()
        m, s = divmod(self.duration_s, 60)
        icon = "done" if status == "done" else "FAILED"
        print(f"[exptrack] {icon}: {self.name}  ({int(m)}m {s:.1f}s)", file=sys.stderr)
        if status == "done":
            plugins.on_finish(self)
        else:
            plugins.on_fail(self, self._params.get("error", ""))

    def fail(self, error: str = ""):
        if error:
            self.log_param("error", error)
        self.finish("failed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.fail(str(exc_val))
            return False
        self.finish()
        return False
