"""
exptrack/__main__.py

Enables:  python -m exptrack script.py --lr 0.01 --bs 32

This wraps any script with full experiment tracking — zero changes to the
script itself. Works by:
  1. Starting an Experiment before the script runs
  2. Patching ArgumentParser.parse_args() so params are auto-captured
  3. Falling back to raw sys.argv parsing if argparse isn't used
  4. Catching exceptions to mark the run as failed
  5. Calling finish() when the script exits cleanly
  6. Capturing stdout/stderr to log files in the output directory

The script sees sys.argv exactly as if it were called directly.
"""
import os
import runpy
import sys
import traceback
from pathlib import Path


class _TeeWriter:
    """Write to both the original stream and a log file."""
    def __init__(self, original, log_file):
        self._original = original
        self._log = log_file

    def write(self, data):
        self._original.write(data)
        self._tee(lambda: (self._log.write(data), self._log.flush()), "write to")
        return len(data) if isinstance(data, str) else None

    def flush(self):
        self._original.flush()
        self._tee(self._log.flush, "flush")

    def _tee(self, action, label):
        # A late write after the log file has been closed (interpreter
        # shutdown, or a library that captured a reference to this tee) is
        # expected — skip it silently rather than warning on a closed file.
        if getattr(self._log, "closed", False):
            return
        try:
            action()
        except ValueError:
            pass  # "I/O operation on closed file" — log already closed
        except Exception as e:
            self._original.write(
                f"[exptrack] warning: could not tee {label} log: {e}\n"
            )

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return self._original.isatty()

    def __getattr__(self, name):
        return getattr(self._original, name)

def main(resume=None):
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m exptrack <script.py> [args...]")
        print("       exptrack run <script.py> [args...]")
        print()
        print("Wraps script.py with full experiment tracking.")
        print("No changes to your script needed.")
        print("Auto-resumes when --resume is in the script's args.")
        sys.exit(0)

    script_path = Path(sys.argv[1]).resolve()
    if not script_path.exists():
        print(f"[exptrack] Error: {script_path} not found")
        sys.exit(1)
    if not script_path.is_file():
        print(f"[exptrack] Error: {script_path} is not a file")
        sys.exit(1)

    # Build a reproducible command for the Reproduce box BEFORE we mutate argv.
    # sys.argv[1] is the script (resolved to an absolute path above), sys.argv[2:]
    # its args. Store the plain, runnable form — `python <abs-path> <args>` — so
    # the dashboard shows a real command with an interpreter, not the bare script
    # basename that _build_command() would produce once argv[0] becomes the script.
    run_command = " ".join(["python", str(script_path), *sys.argv[2:]])

    # Strip 'exptrack' from argv so the script sees its own args
    sys.argv = sys.argv[1:]

    from . import config as cfg
    from .core import Experiment

    conf = cfg.load()

    # Auto-detect resume: check if the script's args contain --resume
    # (or a configurable set of flags), and if so resume the latest
    # experiment for this script instead of creating a new one.
    # The resume flag can also be passed explicitly from the CLI layer.
    if not resume:
        resume_flags = set(conf.get("resume_flags", ["--resume"]))
        script_args = sys.argv[1:]  # everything after the script path
        if any(arg in resume_flags for arg in script_args):
            resume = "latest"

    if resume:
        if resume == "latest":
            exp = _find_latest_experiment(str(script_path), run_command)
        else:
            exp = Experiment.resume(resume)
    else:
        exp = Experiment(script=str(script_path), command=run_command, _caller_depth=0)

    # Publish this run so a wrapped script that creates its OWN Experiment()
    # (one written for plain `python script.py`) adopts it instead of spawning a
    # redundant second run for the same script. See core.experiment for details.
    from .core.experiment import publish_run_wrapper
    publish_run_wrapper(exp)

    # Snapshot the script source and diff against previous runs. The
    # constructor already did this for a fresh run; it is still called here
    # because `Experiment.resume` bypasses __init__ and cannot know the path
    # this invocation resolved. Idempotent for the same file.
    exp._maybe_snapshot_script(str(script_path))

    # Arm argparse / argv / savefig / TensorBoard capture BEFORE the script
    # runs. The run object owns the list (a plain `python train.py` with its own
    # `Experiment()` arms the same patches from __init__); `force=True` covers
    # the one case the constructor can't, a resumed run, since
    # `Experiment.resume` bypasses __init__. A second copy of the list here
    # re-ran argv capture — an identical `log_params` write and a redundant
    # rename — on every wrapped run.
    exp._install_capture_patches(conf, force=True)

    # Record start time for auto-detecting new output files
    start_ts = exp._start

    # Set up stdout/stderr capture to log files
    capture_output = conf.get("auto_capture", {}).get("stdout", True)
    log_files = []
    if capture_output:
        try:
            out_dir = getattr(exp, '_output_dir', None)
            if not out_dir:
                out_dir = cfg.project_root() / conf.get("outputs_dir", "outputs") / exp.name
                out_dir.mkdir(parents=True, exist_ok=True)
            else:
                out_dir = Path(out_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
            log_mode = "a" if resume else "w"
            stdout_log = open(out_dir / "stdout.log", log_mode)
            stderr_log = open(out_dir / "stderr.log", log_mode)
            log_files = [stdout_log, stderr_log]
            sys.stdout = _TeeWriter(sys.stdout, stdout_log)
            sys.stderr = _TeeWriter(sys.stderr, stderr_log)
        except Exception as e:
            print(f"[exptrack] warning: could not set up output capture: {e}", file=sys.stderr)

    # Ensure sys.path[0] is the script's directory, matching the behavior of
    # `python script.py`.  runpy.run_path does NOT do this automatically, so
    # sibling imports (and any path-relative config loading) would break.
    script_dir = str(script_path.parent)
    original_path0 = sys.path[0] if sys.path else None
    if sys.path and sys.path[0] != script_dir:
        sys.path[0] = script_dir
    elif not sys.path:
        sys.path.insert(0, script_dir)

    # Run the script in its own namespace
    try:
        runpy.run_path(
            str(script_path),
            run_name="__main__",
            init_globals={"__exptrack__": exp},  # script can access via globals()
        )
        _restore_streams(log_files)
        # A self-tracking script may have adopted this run and already finished
        # it (its own `with Experiment()` block, or an explicit finish); don't
        # finish twice (Experiment.finish raises on a double-finish).
        if not exp._finished:
            _auto_detect_outputs(exp, start_ts)
            _capture_results_metrics(exp, start_ts, conf, script_path)
            exp.finish()
        _maybe_trash_phantom_wrapper(exp, resume)
    except SystemExit as e:
        # Normal exit — treat code 0 as success
        if e.code == 0 or e.code is None:
            _restore_streams(log_files)
            if not exp._finished:
                _auto_detect_outputs(exp, start_ts)
                _capture_results_metrics(exp, start_ts, conf, script_path)
                exp.finish()
            _maybe_trash_phantom_wrapper(exp, resume)
            sys.exit(0)
        # Non-zero exit. A script (or a framework/library it uses) commonly
        # catches an exception and calls sys.exit(1); the real error is then
        # chained on SystemExit.__context__. Surface that cause instead of
        # swallowing it behind a bare "SystemExit(code)" — print it BEFORE
        # restoring streams so it tees into the terminal AND stderr.log, and
        # capture it on the run so the dashboard shows the file + line.
        tb = None
        cause = e.__context__
        if cause is not None and not isinstance(cause, SystemExit):
            tb = "".join(
                traceback.format_exception(type(cause), cause, cause.__traceback__)
            )
            sys.stderr.write(tb)
        _restore_streams(log_files)
        # If the script adopted this run and already finished it, leave that
        # outcome in place rather than double-finishing (which would raise).
        if not exp._finished:
            if _raised_by_argparse(e):
                from .core.queries import ARG_ERROR_KEY
                exp.log_param(ARG_ERROR_KEY, True)
            exp.fail(f"SystemExit({e.code})", traceback=tb)
        sys.exit(e.code)
    except KeyboardInterrupt:
        # Ctrl-C is how a training run most often ends early, and it is not an
        # `Exception` — so it fell straight through both handlers below and the
        # run stayed `running` with no duration, no error and its log files
        # still open. A run stuck `running` is excluded from every baseline
        # (`_BASELINE_WHERE`) and only `stale` recovers it, 24 hours later.
        sys.stderr.write("\n[exptrack] interrupted (Ctrl-C)\n")
        _restore_streams(log_files)
        if not exp._finished:
            _auto_detect_outputs(exp, start_ts)
            exp.fail("KeyboardInterrupt", interrupted=True)
        # 130 is the conventional shell status for SIGINT, so a job script can
        # tell "I stopped this" from "it crashed".
        sys.exit(130)
    except Exception as e:
        # Print the traceback BEFORE restoring streams so it tees into
        # stderr.log (restoring closes the log files), and capture the full
        # formatted traceback into the run so the failure — file + line —
        # is visible in the dashboard, not just the bare message as a param.
        tb = traceback.format_exc()
        traceback.print_exc()
        _restore_streams(log_files)
        # If the script adopted this run and already finished it, leave that
        # outcome in place rather than double-finishing (which would raise).
        if not exp._finished:
            exp.fail(str(e), traceback=tb)
        sys.exit(1)
    finally:
        # Restore sys.path[0] so exptrack's own imports aren't affected
        if original_path0 is not None and sys.path:
            sys.path[0] = original_path0


def _find_latest_experiment(script_path: str, run_command: str = ""):
    """Find and resume the most recent experiment for this script.

    *run_command* is threaded through for the no-previous-run fallback: without
    it the fresh run reconstructed its command from the mutated argv, recording
    a Reproduce line with no interpreter that still carried ``--resume`` — i.e.
    a command that cannot reproduce the run it describes.
    """
    from .core import Experiment
    from .core.db import get_db
    from .core.utils import resolve_script_identity
    resolved = resolve_script_identity(script_path)
    with get_db() as conn:
        # Trashed runs are excluded: they're gone from every list, so silently
        # continuing one would append metrics to a run the user can't see.
        # The rowid tie-break makes "latest" deterministic when two runs share
        # a created_at (same clock tick) — rowid is insertion, i.e. launch, order.
        row = conn.execute(
            """SELECT id FROM experiments
               WHERE script=? AND deleted_at IS NULL
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (resolved,)
        ).fetchone()
    if not row:
        print(f"[exptrack] No previous experiment found for {Path(script_path).name}, starting new",
              file=sys.stderr)
        return Experiment(script=script_path, command=run_command, _caller_depth=0)
    return Experiment.resume(row["id"])


def _maybe_trash_phantom_wrapper(exp, resume):
    """Soft-delete a metrics-less phantom wrapper left by a self-tracking sweep.

    A script written for plain `python script.py` that builds its own
    Experiment(s) with explicit identity (a param sweep, e.g.
    ``Experiment(name=..., params=...)`` per iteration) doesn't adopt the
    `exptrack run` wrapper — adopting would silently drop each run's distinct
    name/params. Those runs get their own rows (correct), but the wrapper is
    then left with the code snapshot and no metrics of its own: a phantom row
    that clutters the experiment list and floods same-script comparisons.

    When the wrapper saw such a foreign-built run AND recorded no data of its
    own, move it to Trash (soft-delete — fully recoverable, no files touched).
    A resumed run is never touched (it's a deliberate continuation), and a
    hybrid wrapper that logged its own metrics is kept.

    "No data of its own" means neither metrics *nor* artifacts: savefig capture
    and the auto output detection stay pointed at the wrapper for the whole
    sweep, so a script that plots per iteration without logging a metric leaves
    its only artifact rows on the wrapper. Trashing on the metric count alone
    hid them.

    The rows every wrapper gets for free are excluded, because counting them
    means no wrapper is ever a phantom: the ``output_dir`` row, and the
    ``[log] stdout.log`` / ``[log] stderr.log`` rows the stream tee registers.
    They say nothing about whether the run did any work of its own.
    """
    if resume or exp._adopted:
        return
    if not exp._had_foreign_child:
        return
    try:
        from .core.db import get_db, trash_experiment
        with get_db() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM metrics WHERE exp_id=?", (exp.id,)
            ).fetchone()["n"]
            if n:
                return  # wrapper logged its own metrics — a real run, keep it
            n_art = conn.execute(
                "SELECT COUNT(*) AS n FROM artifacts "
                "WHERE exp_id=? AND COALESCE(label,'') <> 'output_dir' "
                "AND COALESCE(label,'') NOT LIKE '[log] %'",
                (exp.id,)
            ).fetchone()["n"]
            if n_art:
                return  # wrapper holds this run's plots/outputs — keep it
            if trash_experiment(conn, exp.id):
                conn.commit()
                print(
                    f"[exptrack] wrapper run {exp.id[:6]} logged no metrics or artifacts of its own "
                    "(the script created its own experiments) — moved to Trash",
                    file=sys.stderr,
                )
    except Exception as e:
        print(f"[exptrack] warning: could not trash phantom wrapper: {e}", file=sys.stderr)


def _restore_streams(log_files):
    """Restore original stdout/stderr and close log files."""
    if isinstance(sys.stdout, _TeeWriter):
        sys.stdout = sys.stdout._original
    if isinstance(sys.stderr, _TeeWriter):
        sys.stderr = sys.stderr._original
    for f in log_files:
        try:
            f.close()
        except Exception as e:
            print(f"[exptrack] warning: could not close log file {getattr(f, 'name', '?')}: {e}",
                  file=sys.stderr)


_AUTO_DETECT_EXTS = {
    '.png', '.jpg', '.jpeg', '.pdf', '.svg', '.gif', '.bmp',
    '.csv', '.json', '.jsonl', '.tsv', '.parquet',
    '.pt', '.pth', '.h5', '.hdf5', '.onnx', '.pkl', '.safetensors',
    '.ckpt', '.bin', '.tflite', '.pb', '.msgpack', '.joblib',
    '.log', '.npy', '.npz',
}
_SKIP_DIRS = {'.exptrack', '.git', '__pycache__', 'node_modules', '.venv', 'venv'}


def _same_content_already_logged(fp: str, own_content: dict) -> bool:
    """True if this run already registered a file with *fp*'s exact content.

    The savefig copy and the file the script wrote are the same bytes under two
    paths and the same name; one artifact row is the honest count. Hashing is
    gated on the (size, name) map, so a file no registered artifact could be a
    copy of is never read.
    """
    try:
        size = os.path.getsize(fp)
    except OSError:
        return False
    hashes = own_content.get((size, os.path.basename(fp)))
    if not hashes:
        return False
    try:
        from . import config as _cfg
        from .core.hashing import file_hash
        max_bytes = int(_cfg.load().get("hash_max_mb", 500)) * 1024 * 1024
        digest, _ = file_hash(fp, max_bytes=max_bytes)
    except Exception as e:
        from .core.utils import debug_log
        debug_log(f"content dedupe hash failed for {fp}: {e}")
        return False
    return digest in hashes


def _raised_by_argparse(e: SystemExit) -> bool:
    """True when *e* is argparse rejecting the command line (a usage error),
    i.e. the innermost frame that raised it is in the argparse module."""
    import argparse
    tb, last = e.__traceback__, None
    while tb is not None:
        last, tb = tb, tb.tb_next
    if last is None:
        return False
    try:
        return (Path(last.tb_frame.f_code.co_filename).resolve()
                == Path(argparse.__file__).resolve())
    except (OSError, TypeError):
        return False


_DEFAULT_RESULTS_FILES = ("results.json", "metrics.json",
                          "*_results.json", "*_metrics.json")


def _results_file_patterns(conf) -> tuple:
    """`auto_capture.results_files`, degrading to the default when unusable."""
    pats = (conf.get("auto_capture") or {}).get("results_files", _DEFAULT_RESULTS_FILES)
    if not isinstance(pats, (list, tuple)) or not all(isinstance(p, str) for p in pats):
        return _DEFAULT_RESULTS_FILES
    return tuple(pats)


def _capture_results_metrics(exp, start_ts, conf, script_path):
    """Log the numbers in a results file the script wrote as the run's metrics.

    A script that ends with `json.dump(results, open("results.json", "w"))`
    recorded no metrics under `exptrack run`: the file was registered as a data
    output and its numbers never read, so the table, the vs-previous delta and
    Compare all showed `--` for a run whose result was sitting on disk. The
    shell pipeline already had `run-finish --metrics results.json`.

    Only files written during this run, only top-level numbers (nested dicts
    flatten to `outer/inner`), and never a key the script already logged
    itself — its own series is the better record. Says which keys it took.
    """
    import fnmatch
    import json
    pats = _results_file_patterns(conf)
    if not pats:
        return
    try:
        from .core import get_db
        # Same connection the run writes on, so points still inside the
        # commit-coalescing window are visible.
        logged = {r[0] for r in get_db().execute(
            "SELECT DISTINCT key FROM metrics WHERE exp_id=?", (exp.id,))}
    except Exception:
        logged = set()
    dirs = []
    for d in (Path.cwd(), Path(script_path).parent, getattr(exp, "_output_dir", "")):
        try:
            d = Path(d).resolve() if d else None
        except OSError:
            d = None
        if d and d.is_dir() and d not in dirs:
            dirs.append(d)
    for d in dirs:
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for f in entries:
            if not any(fnmatch.fnmatch(f.name, p) for p in pats):
                continue
            try:
                if not f.is_file() or f.stat().st_mtime < start_ts:
                    continue
                raw = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            from .cli.pipeline_cmds import _flatten_dict
            nums = {k: v for k, v in _flatten_dict(raw).items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                    and k not in logged}
            if not nums:
                continue
            exp.log_metrics(nums)
            logged.update(nums)
            print(f"[exptrack] metrics from {f.name}: {', '.join(sorted(nums))}",
                  file=sys.stderr)


def _auto_detect_outputs(exp, start_ts):
    """Scan working directory for files created during the run and log them.

    Deduplicates against artifacts already registered on this experiment
    (e.g. by the savefig patch) so the same file is never logged twice, and
    **skips files that belong to another run**.

    Deduplication is by *content* as well as by path. The savefig patch copies
    each figure into the run's own output dir and registers **the copy**, so a
    path-only check left the original (``figs/loss.png`` next to the copy at
    ``outputs/<run>/loss.png``) looking unregistered: every plot got two
    artifact rows, the Images tab showed every image twice, and Compare's
    grid — which pairs runs by file name — saw two images sharing one name
    inside a single run, fell back to full paths, and so paired nothing.

    The mtime window alone is not ownership. Two runs launched together — a
    SLURM array, two terminals, a sweep — write into the window at the same
    time, and whichever finished first registered the other's weights and log
    files as its own artifacts. That also defeated the phantom-wrapper trash: a
    sweep wrapper looked like it had "data of its own" because the scan had
    swept its children's checkpoints onto it.
    """
    skip_dirs = _SKIP_DIRS
    from .core.db import _norm_path, path_within_any
    from .core.utils import is_python_env_dir

    # Collect paths already registered so we don't double-log, and the paths
    # other runs own so we never log them at all. All three sets hold
    # `_norm_path` forms so the walk below can compare against them without a
    # `resolve()` syscall per candidate file.
    already_registered: set[str] = set()
    own_content: dict = {}   # (size, filename) -> hashes this run already has
    foreign_paths: dict[str, str] = {}     # path -> the run still holding it
    foreign_dirs: set[str] = set()
    in_flight: set[str] = set()
    try:
        from .core import get_db
        from .core.db import claimed_output_paths, runs_in_flight_since
        with get_db() as conn:
            # One pass over the table, split in Python: mine and everyone
            # else's answer two different questions about the same rows, and
            # asking twice re-read the whole table at the end of every run.
            rows = conn.execute(
                "SELECT path, exp_id, content_hash, size_bytes FROM artifacts "
                "WHERE path IS NOT NULL AND path != ''"
            ).fetchall()
            foreign_dirs = claimed_output_paths(conn, exclude_id=exp.id)
            # Only a run that could still have been writing owns anything here:
            # a run that finished before this one started has an artifact row
            # for a file this run has since overwritten. See
            # `runs_in_flight_since`.
            in_flight = runs_in_flight_since(conn, start_ts, exclude_id=exp.id)
        for r in rows:
            try:
                # `register_artifact` stores resolved paths, but rows written
                # before it existed may be relative, so normalize lexically —
                # the same rule the ownership scan compares claims with, and
                # no syscall per row.
                norm = _norm_path(r["path"])
            except Exception:
                norm = r["path"]
            if r["exp_id"] == exp.id:
                already_registered.add(norm)
                # Size-keyed so the walk hashes a candidate only when this run
                # already holds a file of exactly that size — never every
                # checkpoint in the tree.
                if r["content_hash"] and r["size_bytes"]:
                    # Keyed on the file *name* too: the savefig copy keeps the
                    # original's name, while two genuinely different plots that
                    # happen to hold the same bytes usually do not — and
                    # dropping one of those would hide an output.
                    key = (int(r["size_bytes"]), os.path.basename(norm))
                    own_content.setdefault(key, set()).add(r["content_hash"])
            elif r["exp_id"] in in_flight:
                foreign_paths[norm] = r["exp_id"]
    except Exception as e:
        print(f"[exptrack] warning: could not load existing artifacts: {e}", file=sys.stderr)

    try:
        for root, dirs, files in os.walk('.'):
            # By marker as well as by name: a venv called `env` or `myenv`
            # is still an environment, never a run's output.
            dirs[:] = [d for d in dirs if d not in skip_dirs
                       and not is_python_env_dir(os.path.join(root, d))]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in _AUTO_DETECT_EXTS:
                    continue
                fp = os.path.join(root, f)
                try:
                    norm = _norm_path(fp)
                    if (os.path.getmtime(fp) < start_ts
                            or norm in already_registered
                            or path_within_any(norm, foreign_dirs)):
                        continue
                    owner = foreign_paths.get(norm)
                    if owner:
                        # Not silent: a run killed outright stays `running` and
                        # keeps its claim, so this is also how a stale claim
                        # shows up. `exptrack stale` releases those.
                        print(f"[exptrack] note: not logging {fp} — run "
                              f"{owner[:6]} is still running and holds it",
                              file=sys.stderr)
                        continue
                    if _same_content_already_logged(fp, own_content):
                        already_registered.add(norm)
                        continue
                    exp.log_file(fp)
                    already_registered.add(norm)
                except OSError as e:
                    print(f"[exptrack] warning: could not auto-detect output {fp}: {e}",
                          file=sys.stderr)
    except Exception as e:
        print(f"[exptrack] warning: auto-detect outputs scan failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
