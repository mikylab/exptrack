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
from pathlib import Path


class _TeeWriter:
    """Write to both the original stream and a log file."""
    def __init__(self, original, log_file):
        self._original = original
        self._log = log_file

    def write(self, data):
        self._original.write(data)
        try:
            self._log.write(data)
            self._log.flush()
        except Exception:
            pass
        return len(data) if isinstance(data, str) else None

    def flush(self):
        self._original.flush()
        try:
            self._log.flush()
        except Exception:
            pass

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
        print("       exptrack run <script.py> --resume [EXP_ID]")
        print()
        print("Wraps script.py with full experiment tracking.")
        print("No changes to your script needed.")
        sys.exit(0)

    script_path = Path(sys.argv[1]).resolve()
    if not script_path.exists():
        print(f"[exptrack] Error: {script_path} not found")
        sys.exit(1)
    if not script_path.is_file():
        print(f"[exptrack] Error: {script_path} is not a file")
        sys.exit(1)

    # Strip 'exptrack' from argv so the script sees its own args
    sys.argv = sys.argv[1:]

    from . import config as cfg
    from .capture import capture_argv, capture_script_snapshot, patch_argparse, patch_savefig
    from .core import Experiment

    conf = cfg.load()

    # Resume an existing experiment or start a new one
    if resume:
        if resume == "latest":
            exp = _find_latest_experiment(str(script_path))
        else:
            exp = Experiment.resume(resume)
    else:
        exp = Experiment(script=str(script_path), _caller_depth=0)

    # Snapshot the script source and diff against previous runs
    capture_script_snapshot(exp, str(script_path))

    # Patch argparse BEFORE the script runs — so parse_args() auto-logs params
    if conf.get("auto_capture", {}).get("argparse", True):
        patch_argparse(exp)

    # Also capture raw argv now (catches --flags even if argparse isn't used)
    if conf.get("auto_capture", {}).get("argv", True):
        capture_argv(exp)

    # Patch matplotlib.savefig so saved plots auto-register as artifacts
    patch_savefig(exp)

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
        _auto_detect_outputs(exp, start_ts)
        exp.finish()
    except SystemExit as e:
        _restore_streams(log_files)
        # Normal exit — treat code 0 as success
        if e.code == 0 or e.code is None:
            _auto_detect_outputs(exp, start_ts)
            exp.finish()
        else:
            exp.fail(f"SystemExit({e.code})")
        sys.exit(e.code or 0)
    except Exception as e:
        _restore_streams(log_files)
        import traceback
        traceback.print_exc()
        exp.fail(str(e))
        sys.exit(1)
    finally:
        # Restore sys.path[0] so exptrack's own imports aren't affected
        if original_path0 is not None and sys.path:
            sys.path[0] = original_path0


def _find_latest_experiment(script_path: str):
    """Find and resume the most recent experiment for this script."""
    from .core import Experiment
    from .core.db import get_db

    resolved = str(Path(script_path).resolve())
    with get_db() as conn:
        row = conn.execute(
            """SELECT id FROM experiments
               WHERE script=?
               ORDER BY created_at DESC LIMIT 1""",
            (resolved,)
        ).fetchone()
    if not row:
        print(f"[exptrack] No previous experiment found for {Path(script_path).name}, starting new",
              file=sys.stderr)
        return Experiment(script=script_path, _caller_depth=0)
    return Experiment.resume(row["id"])


def _restore_streams(log_files):
    """Restore original stdout/stderr and close log files."""
    if isinstance(sys.stdout, _TeeWriter):
        sys.stdout = sys.stdout._original
    if isinstance(sys.stderr, _TeeWriter):
        sys.stderr = sys.stderr._original
    for f in log_files:
        try:
            f.close()
        except Exception:
            pass


_AUTO_DETECT_EXTS = {
    '.png', '.jpg', '.jpeg', '.pdf', '.svg', '.gif', '.bmp',
    '.csv', '.json', '.jsonl', '.tsv', '.parquet',
    '.pt', '.pth', '.h5', '.hdf5', '.onnx', '.pkl', '.safetensors',
    '.ckpt', '.bin', '.tflite', '.pb', '.msgpack', '.joblib',
    '.log', '.npy', '.npz',
}
_SKIP_DIRS = {'.exptrack', '.git', '__pycache__', 'node_modules', '.venv', 'venv'}


def _auto_detect_outputs(exp, start_ts):
    """Scan working directory for files created during the run and log them.

    Deduplicates against artifacts already registered on this experiment
    (e.g. by the savefig patch) so the same file is never logged twice.
    """
    skip_dirs = _SKIP_DIRS

    # Collect paths already registered so we don't double-log
    already_registered: set[str] = set()
    try:
        from .core import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT path FROM artifacts WHERE exp_id=?", (exp.id,)
            ).fetchall()
        for r in rows:
            if r["path"]:
                try:
                    already_registered.add(str(Path(r["path"]).resolve()))
                except Exception as e:
                    print(f"[exptrack] warning: could not resolve artifact path: {e}", file=sys.stderr)
                    already_registered.add(r["path"])
    except Exception as e:
        print(f"[exptrack] warning: could not load existing artifacts: {e}", file=sys.stderr)

    try:
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in _AUTO_DETECT_EXTS:
                    continue
                fp = os.path.join(root, f)
                try:
                    resolved = str(Path(fp).resolve())
                    if os.path.getmtime(fp) >= start_ts and resolved not in already_registered:
                        exp.log_file(fp)
                        already_registered.add(resolved)
                except OSError:
                    pass
    except Exception as e:
        print(f"[exptrack] warning: auto-detect outputs scan failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
