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

The script sees sys.argv exactly as if it were called directly.
"""
import sys
import runpy
from pathlib import Path

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m exptrack <script.py> [args...]")
        print("       exptrack run <script.py> [args...]")
        print()
        print("Wraps script.py with full experiment tracking.")
        print("No changes to your script needed.")
        sys.exit(0)

    script_path = Path(sys.argv[1]).resolve()
    if not script_path.exists():
        print(f"[exptrack] Error: {script_path} not found")
        sys.exit(1)

    # Strip 'exptrack' from argv so the script sees its own args
    sys.argv = sys.argv[1:]

    from .core import Experiment
    from .capture import patch_argparse, capture_argv
    from . import config as cfg

    conf = cfg.load()

    # Start the experiment before anything in the script runs
    exp = Experiment(script=str(script_path), _caller_depth=0)

    # Patch argparse BEFORE the script runs — so parse_args() auto-logs params
    if conf.get("auto_capture", {}).get("argparse", True):
        patch_argparse(exp)

    # Also capture raw argv now (catches --flags even if argparse isn't used)
    if conf.get("auto_capture", {}).get("argv", True):
        capture_argv(exp)

    # Run the script in its own namespace
    try:
        runpy.run_path(
            str(script_path),
            run_name="__main__",
            init_globals={"__exptrack__": exp},  # script can access via globals()
        )
        exp.finish()
    except SystemExit as e:
        # Normal exit — treat code 0 as success
        if e.code == 0 or e.code is None:
            exp.finish()
        else:
            exp.fail(f"SystemExit({e.code})")
        sys.exit(e.code or 0)
    except Exception as e:
        import traceback
        traceback.print_exc()
        exp.fail(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
