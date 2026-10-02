"""
exptrack/config.py — Project-aware configuration

Config lives at <project_root>/.exptrack/config.json
Project root = nearest ancestor directory containing .git or .exptrack/
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
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
        # Results files `exptrack run` reads metrics from at finish: written
        # during the run, top-level numbers (nested dicts flatten to `a/b`).
        # [] turns it off.
        "results_files": ["results.json", "metrics.json",
                          "*_results.json", "*_metrics.json"],
        # A notebook hyperparameter changed after the run logged results
        # starts a new run instead of overwriting the old one's value.
        "notebook_new_run_on_hp_change": True,
        # Record `__version__` of the third-party packages a run imported.
        "environment": True,
    },
    "naming": {
        "max_param_keys": 4,
        "key_max_len":    8,
        "date_style":     "readable",
    },
    "param_redact_patterns": [
        "api.key", "password", "token", "secret", "credential",
    ],
    # One-line stderr notice at finish when a run repeats a configuration
    # already run. Advisory only — never a prompt, never a refusal.
    "warn_duplicate_runs":   True,
    # The metric runs are judged by, project-wide. Unset by default: with
    # nothing configured the heuristic in core/primary_metric.py guesses from
    # what each run logged, and says it guessed. Either a bare key
    # ("val_acc") or {"key": "val_acc", "goal": "max"|"min"}; an omitted goal
    # is inferred from the metric's name.
    "primary_metric":        "",
    # Per-study overrides, {"<study name>": <same shape as above>}. Studies
    # have no row of their own — they are names inside each run's `studies`
    # JSON list — so the override lives here rather than on a record.
    "primary_metric_by_study": {},
    # One name for one measurement, across models that name it differently:
    # {"val_acc": ["accuracy", "val/acc"]}. The key is the canonical name every
    # surface will show; the list is the spellings that mean it. Without this,
    # two models logging the same measurement under different names shared no
    # metric at all — compare showed two rows of `--` and ranking excluded one
    # of them. See core/metric_alias.py.
    "metric_aliases":        {},
    # The run everything else is measured against — the current production
    # model, the published number. Deliberately separate from a run's own
    # `_variant_of` lineage, and it never falls through to "the best run so
    # far": a baseline that moves on its own is one you cannot reason about.
    "reference_run":         "",
    "reference_run_by_study": {},
    "result_types": [
        "accuracy", "loss", "auroc", "f1", "precision", "recall",
        "mse", "mae", "r2", "perplexity", "bleu",
    ],
    "var_fingerprint_max_mb": 100,   # cap content-hashing of vars for change detection; lower if per-cell capture is slow with big DataFrames
    "metric_keep_every":     1,      # store 1 of every N points your code logs, per metric key (1=all). Counts points, not step values, so it works at any logging cadence
    "metric_commit_interval_ms": 250,  # coalesce metric commits (one fsync each) into at most one per this window; 0 = commit every call
    # These three are documented settings that were only ever read with an
    # inline fallback (`conf.get(k, <default>)`), so they never reached
    # `_coerce_numeric` — a hand-edited `"metric_max_points": "lots"` raised
    # instead of degrading to the default, which is the one thing config.json is
    # promised never to do. Listing them here is what applies that rule.
    "metric_max_points":     500,    # max points a chart request returns (server-side downsampling)
    "resume_flags":          ["--resume"],  # argv flags that trigger auto-resume
    "timezone":              "",     # dashboard display timezone; "" = UTC
    "max_cell_source_kb":    50,     # hard cap on cell source in cell_lineage
    "max_source_diff_kb":    20,     # hard cap on source_diff in timeline events
    "max_vars_per_cell":     50,     # max var_set events per cell execution
    "max_cell_output_chars": 2000,   # output truncation limit for cell snapshots
    "max_assignment_expr_len": 500,  # max chars of an assignment RHS kept in var displays
    "notebook_history":      False,  # write snapshot JSON files to disk
    "auto_trash_failed":     False,  # soft-trash a run when it finishes 'failed'
    "snapshot_max_kb":       512,    # cap on a single stored script/source snapshot
    "snapshot_max_files":    50,     # cap on project-local modules snapshotted per run
    "code_change_max_chars": 20000,  # cap on the _code_changes summary (truncation is marked)
    "plugins": {
        "enabled": [],
    },
}

_cache: dict | None = None
_root_cache: Path | None = None

# Per-thread project override. The dashboard serves many projects from one
# process, so resolution has to answer differently per thread.
#
# This is a layer ABOVE the module globals, not a replacement for them. 28
# test files patch `_root_cache` directly; converting it to thread-local
# storage would make every one of those patches set an attribute nothing
# reads — the tests would not fail, they would silently resolve against the
# real cwd. Resolution order is: thread override, then the module global,
# then the cwd walk. The two never collide: tests never activate, and the
# dashboard never sets the module global.
_tls = threading.local()


def activate_project(root: Path) -> None:
    """Bind this thread to *root* until ``reset_project``."""
    _tls.root = Path(root)
    _tls.conf = None          # config is per-project; drop the last one


def active_project() -> Path | None:
    """The project this thread is bound to, or None."""
    return getattr(_tls, "root", None)


def reset_project() -> None:
    """Unbind this thread, restoring cwd-derived resolution."""
    _tls.root = None
    _tls.conf = None


@contextlib.contextmanager
def project_scope(root: Path):
    """Activate *root* for the duration of the block, then restore.

    Restores the *previous* override rather than clearing, so nesting works —
    Compare resolves one run under another project and must come back to the
    request's own project, not to no project at all.
    """
    previous_root = getattr(_tls, "root", None)
    previous_conf = getattr(_tls, "conf", None)
    activate_project(root)
    try:
        yield
    finally:
        _tls.root = previous_root
        _tls.conf = previous_conf


def project_root() -> Path:
    """Walk up from cwd to find .git or .exptrack — that's the project root.

    A thread bound by ``activate_project`` short-circuits the walk; see the
    comment on ``_tls``.
    """
    override = getattr(_tls, "root", None)
    if override is not None:
        return override
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
    """The project's ``.exptrack/`` directory, created 0700 if absent.

    0700 rather than the umask default because this directory holds the runs
    database, and on a shared workstation directory permissions are the only
    thing protecting it. An *existing* directory is left exactly as the user
    set it — silently tightening permissions on something they may have
    deliberately shared is not this function's call. ``warn_if_world_readable``
    is how that case is surfaced instead.
    """
    d = project_root() / ".exptrack"
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        try:
            d.chmod(0o700)
        except OSError:
            pass  # best-effort: Windows and some network filesystems
    return d


def user_dir() -> Path:
    """``~/.exptrack`` — user-global state, created 0700 if absent.

    Shared by everything that is a *machine* fact rather than a *checkout*
    fact: saved remotes, and — added for the multi-project registry — the set
    of projects this machine knows about. The dashboard token is per-project
    and does NOT live here; it stays under that project's ``exptrack_dir()``.
    This directory is deliberately outside any project's ``exptrack_dir()``
    and outside any virtualenv, so whichever install's `exptrack` runs still
    finds the same user-global files.
    """
    d = Path(os.path.expanduser("~")) / ".exptrack"
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        try:
            d.chmod(0o700)
        except OSError:
            pass  # best-effort: Windows and some network filesystems
    return d


def remotes_file_path() -> Path:
    """``~/.exptrack/remotes.json`` — user-global, not project-local.

    A saved remote (host, directory, ports) describes a *machine pair* — this
    laptop and that GPU box — not a checkout, so it does not live under the
    project's ``exptrack_dir()``.
    """
    return user_dir() / "remotes.json"


def warn_if_world_readable() -> str:
    """A warning if ``.exptrack/`` is group- or world-accessible, else "".

    This matters more than any question about the dashboard token: on a
    shared workstation, directory permissions are the *only* thing standing
    between a colleague's account and ``.exptrack/experiments.db`` — every
    run, param and metric, regardless of whether the dashboard is even
    running. Returns the message rather than printing it so callers decide
    where it goes and tests can assert on it.
    """
    if os.name == "nt":
        return ""  # POSIX modes do not map to a meaningful ACL here
    d = project_root() / ".exptrack"
    try:
        mode = d.stat().st_mode & 0o777
    except OSError:
        return ""
    if not mode & 0o077:
        return ""
    return (f"{d} is accessible to other users on this machine (mode "
            f"{oct(mode)[-3:]}). Anyone with an account here can read your "
            f"runs database.\n  Fix it with:  exptrack fix-perms")


def config_path() -> Path:
    return exptrack_dir() / "config.json"


def _read_config(p: Path) -> dict:
    """*p* merged over DEFAULTS, or a copy of DEFAULTS if it can't be read.

    Split out of ``load()`` so the per-thread and module-global caches share
    one reader — including the UTF-8-then-locale fallback below. Two copies
    of that would drift.
    """
    if p.exists():
        try:
            try:
                raw = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # save() always writes UTF-8 (json.dumps defaults to
                # ensure_ascii=True, so anything exptrack itself wrote is
                # plain ASCII and can't hit this branch) — but a hand-edited
                # config.json with non-ASCII saved in the OS locale encoding
                # used to read back fine under the old locale-default
                # read_text(). Falling straight to the outer except here
                # would silently drop every setting (primary_metric,
                # metric_aliases, reference_run, ...) to defaults, which is
                # a worse outcome than the mojibake bug the UTF-8 switch
                # fixed. Try the locale encoding before giving up; the file
                # self-heals to UTF-8 the next time anything calls save().
                import locale
                fallback = locale.getpreferredencoding(False)
                raw = p.read_text(encoding=fallback)
                print(f"[exptrack] Config warning: {p} is not UTF-8 (read "
                      f"as {fallback}); it will be rewritten as UTF-8 on "
                      f"next save.", file=sys.stderr)
            user = json.loads(raw)
            merged = _deep_merge(DEFAULTS, user)
            _coerce_numeric(DEFAULTS, merged)
            return merged
        except Exception as e:
            print(f"[exptrack] Config error: {e} — using defaults", file=sys.stderr)
    return dict(DEFAULTS)


def load() -> dict:
    # A thread bound to a project caches that project's config on the thread,
    # never in the module global — otherwise a thread on project B would be
    # served project A's settings.
    if getattr(_tls, "root", None) is not None:
        if getattr(_tls, "conf", None) is not None:
            return _tls.conf
        _tls.conf = _read_config(config_path())
        return _tls.conf
    global _cache
    if _cache is not None:
        return _cache
    _cache = _read_config(config_path())
    return _cache


def _overrides_only(cfg: dict, defaults: dict) -> dict:
    """*cfg* with every key that still equals its default dropped, recursively.

    An empty nested dict is dropped too, so a section the user never touched
    leaves no trace.
    """
    out = {}
    for key, value in cfg.items():
        if key not in defaults:
            out[key] = value
            continue
        default = defaults[key]
        if isinstance(default, dict) and isinstance(value, dict):
            nested = _overrides_only(value, default)
            if nested:
                out[key] = nested
            continue
        if value != default:
            out[key] = value
    return out


def save(cfg: dict) -> None:
    """Persist *cfg*, writing only what differs from the defaults.

    Callers pass the dict `load()` gave them, which is the defaults merged with
    the file — so writing it verbatim froze every current default into
    config.json. That file is documented as safe to commit, so a later change
    to a default silently never applied to any project whose config had ever
    been written. `load()` merges the defaults back, so nothing is lost by
    leaving them out.
    """
    p = config_path()
    p.write_text(json.dumps(_overrides_only(cfg, DEFAULTS), indent=2),
                 encoding="utf-8")
    # The cache that gets the new value is the one `load()` would read on this
    # thread. A bound thread writing the module global would hand *cfg* to
    # every unbound caller — the dashboard saving project B's settings would
    # serve them to a CLI resolving from cwd — while its own per-thread copy
    # stayed stale.
    if getattr(_tls, "root", None) is not None:
        _tls.conf = cfg
        return
    global _cache
    _cache = cfg


def reload() -> dict:
    """Force reload config from disk (used after upgrade)."""
    if getattr(_tls, "root", None) is not None:
        _tls.conf = None
        return load()
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


def open_private(path: Path, flags: int) -> int:
    """Open *path* with mode 0600, refusing to follow a symlink.

    Lives here rather than in dashboard/daemon.py (which used to own it)
    because config.py is the lower layer — daemon already imports config, and
    write_token (below) needs the exact same guarantee: the mode is set *at
    creation*, not chmod-ed on afterwards. Creating world-readable and
    tightening permissions later leaves a window in which the file — a
    security-relevant secret, in write_token's case the dashboard auth token
    itself — is readable by anyone else on the box, and on a shared
    workstation a window is all it takes. O_NOFOLLOW means a symlink planted
    at this path is an error rather than a write to wherever it points.

    Deliberately not O_EXCL: callers (write_token, daemon.write_state,
    daemon.spawn_detached's log) must be able to rewrite an existing file of
    theirs — token rotation, state updates, log appends — so O_TRUNC/O_APPEND
    is the caller's choice, not a one-time-only create.
    """
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    return os.open(str(path), flags, 0o600)


def write_token(token: str) -> Path:
    """Persist the dashboard token 0600 and guarantee it is gitignored.

    The ignore rule is *established here*, not merely assumed: `init` writes the
    rule list, so a project initialized before the token moved out of
    config.json would otherwise have no rule for it — the write path must not
    claim a protection it didn't put in place.

    Routed through open_private rather than write_text()+chmod(): the token is
    the most security-relevant of the three lifecycle files (it's the bearer
    credential for the dashboard), so it gets the same create-time-0600 +
    O_NOFOLLOW guarantee dashboard.json/dashboard.log already had — a
    write-then-chmod window and a followable symlink are both bugs the other
    two files don't have.
    """
    ensure_gitignore_rules()
    p = token_file_path()
    fd = open_private(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
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
    ".exptrack/dashboard.json",
    ".exptrack/dashboard.log",
    ".exptrack/trash/",
    "outputs/",
)


def ensure_gitignore_rules() -> bool:
    """Append any missing exptrack rules to the project's .gitignore.

    Idempotent and additive — never rewrites or reorders existing content.
    Returns True if anything was added.
    """
    gitignore = project_root() / ".gitignore"
    # errors="replace": this is the *reader* half of the mojibake bug whose
    # writer half is fixed below (encoding="utf-8" on the append). A
    # .gitignore written by a pre-fix Windows install (or by any other tool,
    # in any legacy encoding) can contain bytes that are not valid UTF-8 —
    # strict decoding raised UnicodeDecodeError here uncaught, so `exptrack
    # init`, `write_token` (and therefore `ui --token` / first dashboard
    # start) and daemon.write_state/spawn_detached (both call
    # ensure_gitignore_rules) all crashed on a file this function only reads
    # for substring membership. Lossy decoding can't corrupt anything here —
    # the result is used solely to check which rules are already present —
    # and it never raises.
    existing = (gitignore.read_text(encoding="utf-8", errors="replace")
                if gitignore.exists() else "")
    to_add = [r for r in GITIGNORE_RULES if r not in existing]
    if not to_add:
        return False
    # encoding="utf-8" is load-bearing: GITIGNORE_RULES[0] has an em-dash, and
    # without it Windows opens this in the system ANSI codepage and writes
    # mojibake into the project's .gitignore.
    with gitignore.open("a", encoding="utf-8") as f:
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

    # Function-local: projects.py imports config at module level (for
    # database_path/_SCHEMA_VERSION plumbing), so a module-level import here
    # would be a cycle. Registering on init is what lets a fresh venv-local
    # `exptrack ui` still discover a project it was never told about directly.
    from . import projects
    projects.register(project_root())


def _find_git_root(start: Path) -> Path | None:
    """Walk up from start looking for a .git directory."""
    for parent in [start, *start.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _coerce_numeric(defaults: dict, cfg: dict) -> None:
    """Coerce hand-editable settings to their default's type, in place.

    config.json is documented as safe to hand-edit, and several caps
    (``var_fingerprint_max_mb``, ``max_cell_source_kb``, ``max_vars_per_cell`` …)
    are read with a bare ``int(...)`` deep in the capture path. A non-numeric
    value there — ``"var_fingerprint_max_mb": "lots"`` — raised inside capture
    and, caught only at the top-level boundary, aborted capture on *every*
    notebook cell: the run recorded nothing while spamming a traceback. The
    documented invariant is the opposite ("an unusable value must always degrade
    to the documented default — a hand-edited config must never be the reason a
    run records nothing"), so enforce it once here rather than at each call site.

    For every key whose default is an ``int`` (bools excluded — ``bool`` is an
    ``int`` subclass, and the booleans are read as booleans, not coerced),
    coerce the user's value; if it can't be coerced, keep the default and say so
    once on stderr. Recurses into nested dicts (e.g. ``naming.*``).
    """
    # Validate-and-fall-back, one row per default type. Booleans are read as
    # booleans and `bool` is an `int` subclass, so coercing would turn a stray
    # "yes" into True rather than rejecting it — every type here is *checked*,
    # and only `int` below is genuinely coerced. A dict is accepted for a
    # text-defaulted key because a few take a structured override too
    # (`primary_metric` is either "val_acc" or {"key": …, "goal": …}) and their
    # own parser validates it; what must not pass is a number where a path or a
    # name is expected — `"db": 123` reached get_db() as an int and raised a
    # TypeError on *every* command.
    checks = (
        (bool, (bool,), "true/false", lambda d: d),
        (str, (str, dict), "text", lambda d: d),
        (list, (list,), "a list", list),
        (dict, (dict,), "an object", dict),
    )
    for key, default in defaults.items():
        matched = False
        for kind, allowed, label, copy in checks:
            if not isinstance(default, kind):
                continue
            matched = True
            if key in cfg and not isinstance(cfg[key], allowed):
                print(f"[exptrack] Config: {key}={cfg[key]!r} is not {label} — "
                      f"using default {default!r}", file=sys.stderr)
                cfg[key] = copy(default)
            break
        # A dict default still recurses into a well-typed override below.
        if matched and not isinstance(default, dict):
            continue
        if isinstance(default, int):
            val = cfg.get(key, default)
            if isinstance(val, int) and not isinstance(val, bool):
                continue  # already a clean int — nothing to do
            try:
                cfg[key] = int(val)
            except (TypeError, ValueError):
                print(f"[exptrack] Config: {key}={val!r} is not a number — "
                      f"using default {default}", file=sys.stderr)
                cfg[key] = default
        elif isinstance(default, dict) and isinstance(cfg.get(key), dict):
            _coerce_numeric(default, cfg[key])


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
