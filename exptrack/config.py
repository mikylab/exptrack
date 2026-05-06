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
    "artifact_strategy":     "reference",   # "reference" (no copy) | "copy" (legacy)
    "hash_max_mb":           500,            # partial-hash files larger than this
    "protect_on_rerun":      True,           # archive old artifacts on path conflict
    "auto_capture": {
        "argparse": True,
        "argv":     True,
        "notebook": True,
    },
    "naming": {
        "max_param_keys": 4,
        "key_max_len":    8,
    },
    "param_redact_patterns": [
        "api.key", "password", "token", "secret", "credential",
    ],
    "result_types": [
        "accuracy", "loss", "auroc", "f1", "precision", "recall",
        "mse", "mae", "r2", "perplexity", "bleu",
    ],
    "metric_keep_every":     1,      # store every Nth metric point (1=all, 10=every 10th)
    "max_cell_source_kb":    50,     # hard cap on cell source in cell_lineage
    "max_source_diff_kb":    20,     # hard cap on source_diff in timeline events
    "max_vars_per_cell":     50,     # max var_set events per cell execution
    "max_cell_output_chars": 2000,   # output truncation limit for cell snapshots
    "notebook_history":      False,  # write snapshot JSON files to disk
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
