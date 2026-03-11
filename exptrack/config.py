"""
exptrack/config.py — Project-aware configuration

Config lives at <project_root>/.exptrack/config.json
Project root = nearest ancestor directory containing .git or .exptrack/
"""
from __future__ import annotations
import json
import os
from pathlib import Path

DEFAULTS: dict = {
    "db":                    ".exptrack/experiments.db",
    "outputs_dir":           "outputs",
    "notebook_history_dir":  ".exptrack/notebook_history",
    "auto_capture": {
        "argparse": True,
        "argv":     True,
        "notebook": True,
    },
    "naming": {
        "max_param_keys": 4,
        "key_max_len":    8,
    },
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
            print(f"[exptrack] Config error: {e} — using defaults")
    _cache = dict(DEFAULTS)
    return _cache


def save(cfg: dict):
    p = config_path()
    p.write_text(json.dumps(cfg, indent=2))
    global _cache
    _cache = cfg


def reload():
    """Force reload config from disk (used after upgrade)."""
    global _cache
    _cache = None
    return load()


def init(project_name: str = "", here: bool = False):
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
    d = exptrack_dir()
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
    gitignore = root / ".gitignore"
    rules = [
        "",
        "# exptrack — local only (db + snapshots); config.json is safe to commit",
        ".exptrack/experiments.db",
        ".exptrack/experiments.db-wal",
        ".exptrack/experiments.db-shm",
        ".exptrack/notebook_history/",
        "outputs/",
    ]
    existing = gitignore.read_text() if gitignore.exists() else ""
    to_add = [r for r in rules if r not in existing]
    if to_add:
        with gitignore.open("a") as f:
            f.write("\n".join(to_add) + "\n")
        print(f"[exptrack] Updated .gitignore")

    print(f"\n  Project root : {root}")
    print(f"  DB           : .exptrack/experiments.db  (local, gitignored)")
    print(f"  Config       : .exptrack/config.json     (commit this)")
    print(f"  Outputs      : outputs/                  (gitignored)")


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
