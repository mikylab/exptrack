"""
exptrack/config.py — Project-aware configuration

Config lives at <project_root>/.exptrack/config.json
Project root = nearest ancestor directory containing .git or .exptrack/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULTS: dict = {
    "db":                    ".exptrack/experiments.db",
    "outputs_dir":           "outputs",
    "exports_dir":           "exports",
    "notebook_history_dir":  ".exptrack/notebook_history",
    "max_git_diff_kb":       256,
    "git_diff_exclude":      ["*.ipynb"],   # pathspecs excluded from diff capture
    "artifact_strategy":     "reference",   # "reference" (no copy) | "copy" (legacy)
    "hash_max_mb":           500,            # partial-hash files larger than this
    "protect_on_rerun":      True,           # archive old artifacts on path conflict
    "auto_capture": {
        "argparse":    True,
        "argv":        True,
        "notebook":    True,
        "tensorboard": True,   # mirror SummaryWriter scalars/histograms into metrics
    },
    "naming": {
        "max_param_keys": 4,
        "key_max_len":    8,
        "date_style":     "readable",
    },
    "param_redact_patterns": [
        "api.key", "password", "token", "secret", "credential",
    ],
    "result_types": [
        "accuracy", "loss", "auroc", "f1", "precision", "recall",
        "mse", "mae", "r2", "perplexity", "bleu",
    ],
    "var_fingerprint_max_mb": 100,   # cap content-hashing of vars for change detection; lower if per-cell capture is slow with big DataFrames
    "metric_keep_every":     1,      # store 1 of every N points your code logs, per metric key (1=all). Counts points, not step values, so it works at any logging cadence
    "metric_commit_interval_ms": 250,  # coalesce metric commits (one fsync each) into at most one per this window; 0 = commit every call
    "max_cell_source_kb":    50,     # hard cap on cell source in cell_lineage
    "max_source_diff_kb":    20,     # hard cap on source_diff in timeline events
    "max_vars_per_cell":     50,     # max var_set events per cell execution
    "max_cell_output_chars": 2000,   # output truncation limit for cell snapshots
    "max_assignment_expr_len": 500,  # max chars of an assignment RHS kept in var displays
    "notebook_history":      False,  # write snapshot JSON files to disk
    "auto_trash_failed":     False,  # soft-trash a run when it finishes 'failed'
    "snapshot_max_kb":       512,    # cap on a single stored script/source snapshot
    "code_change_max_chars": 20000,  # cap on the _code_changes summary (truncation is marked)
    "plugins": {
        "enabled": [],
    },
}

_cache: dict | None = None
_root_cache: Path | None = None


def project_root() -> Path:
    """Walk up from cwd to find .git or .exptrack — that's the project root."""
    global _root_cache
    if _root_cache:
        return _root_cache
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists() or (parent / ".exptrack").exists():
            _root_cache = parent
            return parent
    _root_cache = cwd
    return cwd


def exptrack_dir() -> Path:
    d = project_root() / ".exptrack"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return exptrack_dir() / "config.json"


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    p = config_path()
    if p.exists():
        try:
            user = json.loads(p.read_text())
            _cache = _deep_merge(DEFAULTS, user)
            return _cache
        except Exception as e:
            print(f"[exptrack] Config error: {e} — using defaults", file=sys.stderr)
    _cache = dict(DEFAULTS)
    return _cache


def save(cfg: dict) -> None:
    p = config_path()
    p.write_text(json.dumps(cfg, indent=2))
    global _cache
    _cache = cfg


def reload() -> dict:
    """Force reload config from disk (used after upgrade)."""
    global _cache
    _cache = None
    return load()


def token_file_path() -> Path:
    """Path of the dashboard auth token (``.exptrack/dashboard_token``).

    Deliberately *not* ``config.json``: `init` tells users config.json is safe to
    commit and leaves it out of .gitignore, so persisting an auth secret there
    put it one ``git add -A`` from being published.
    """
    return exptrack_dir() / "dashboard_token"


def readable_project_path(rel_path: str | Path) -> Path | None:
    """Resolve *rel_path* against the project root, or None if it is off-limits.

    The single definition of "a path the dashboard may read on the user's
    behalf", applied by both the file server (`/api/file/`) and the Images /
    Data Files scan-path walks. Two rules, and both halves matter:

    * **Inside the project root.** ``realpath`` on both sides with a separator
      boundary — a bare ``startswith(root)`` also accepts a sibling directory
      whose name merely begins with the root's (``/home/me/proj`` matching
      ``/home/me/proj2``), and without resolving symlinks a link inside the
      project reaches anywhere on disk.
    * **Not under ``.exptrack/``.** That directory holds the database, the
      dashboard token and notebook history — internals, not user artifacts.

    It lives here because where a path sits relative to the project (and which
    subtrees are exptrack's own) is config-layer knowledge. It was previously
    inline in the HTTP handler, and the scan routes carried a weaker copy of
    only the first rule, which is exactly the drift a shared predicate ends.
    """
    import os
    root = project_root()
    if not root:
        return None
    real_root = os.path.realpath(str(root))
    abs_path = os.path.realpath(os.path.join(str(root), str(rel_path)))
    if abs_path != real_root and not abs_path.startswith(real_root + os.sep):
        return None
    # Literal rather than exptrack_dir(), which creates the directory — a
    # read-only predicate must not have that side effect.
    internals = os.path.realpath(os.path.join(real_root, ".exptrack"))
    if abs_path == internals or abs_path.startswith(internals + os.sep):
        return None
    return Path(abs_path)


def write_token(token: str) -> Path:
    """Persist the dashboard token 0600 and guarantee it is gitignored.

    The ignore rule is *established here*, not merely assumed: `init` writes the
    rule list, so a project initialized before the token moved out of
    config.json would otherwise have no rule for it — the write path must not
    claim a protection it didn't put in place.
    """
    ensure_gitignore_rules()
    p = token_file_path()
    p.write_text(token + "\n")
    try:
        p.chmod(0o600)
    except OSError:
        pass  # best-effort on filesystems without POSIX modes
    return p


# Paths exptrack writes that must never be committed: the DB and its sidecars,
# notebook snapshots, the auth token, the local OS-Trash fallback (deleted
# artifacts/checkpoints), and run outputs. config.json is intentionally absent —
# it is meant to be committed, which is why no secret may live in it.
GITIGNORE_RULES = (
    "# exptrack — local only (db + snapshots); config.json is safe to commit",
    ".exptrack/experiments.db",
    ".exptrack/experiments.db-wal",
    ".exptrack/experiments.db-shm",
    ".exptrack/notebook_history/",
    ".exptrack/dashboard_token",
    ".exptrack/trash/",
    "outputs/",
)


def ensure_gitignore_rules() -> bool:
    """Append any missing exptrack rules to the project's .gitignore.

    Idempotent and additive — never rewrites or reorders existing content.
    Returns True if anything was added.
    """
    gitignore = project_root() / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    to_add = [r for r in GITIGNORE_RULES if r not in existing]
    if not to_add:
        return False
    with gitignore.open("a") as f:
        f.write("\n" + "\n".join(to_add) + "\n")
    return True


def init(project_name: str = "", here: bool = False) -> None:
    """Called by `exptrack init` — writes config + .gitignore rules.

    By default, init creates .exptrack/ in the current working directory.
    If a parent git root is found and --here is NOT set, it will still
    prefer cwd but print a note about the detected git root.
    """
    global _root_cache
    cwd = Path.cwd()

    # Always init in cwd — that's what the user means by "init"
    _root_cache = cwd
    root = cwd

    # If there's a git root above cwd, let the user know
    if not here:
        git_root = _find_git_root(cwd)
        if git_root and git_root != cwd:
            import sys
            print(f"[exptrack] Note: git root detected at {git_root}",
                  file=sys.stderr)
            print(f"[exptrack] Initializing in current directory: {cwd}",
                  file=sys.stderr)
    exptrack_dir()
    p = config_path()

    if not p.exists():
        cfg = dict(DEFAULTS)
        if project_name:
            cfg["project"] = project_name
        save(cfg)
        print(f"[exptrack] Created {p.relative_to(root)}")
    else:
        print(f"[exptrack] Config already exists at {p.relative_to(root)}")

    # Patch .gitignore — DB and history are local-only, config is committable
    if ensure_gitignore_rules():
        print("[exptrack] Updated .gitignore")

    print(f"\n  Project root : {root}")
    print("  DB           : .exptrack/experiments.db  (local, gitignored)")
    print("  Config       : .exptrack/config.json     (commit this)")
    print("  Outputs      : outputs/                  (gitignored)")


def _find_git_root(start: Path) -> Path | None:
    """Walk up from start looking for a .git directory."""
    for parent in [start, *start.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
