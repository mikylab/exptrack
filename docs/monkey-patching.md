# Monkey-Patching

expTrack patches argparse and matplotlib to capture params and artifacts automatically. Here's how it works and what to watch out for.

## What Gets Patched

### argparse

- **What:** `ArgumentParser.parse_args()` and `parse_known_args()`
- **When:** Before your script runs (via `exptrack run` or `Experiment()`)
- **Effect:** Parsed arguments are logged as experiment parameters
- **Cleanup:** Patch is removed when the script exits
- **Thread-safe:** Yes (protected by `threading.Lock`)

### matplotlib

- **What:** `plt.savefig()` and `Figure.savefig()`
- **When:** When a notebook experiment starts
- **Effect:** Saved plots are auto-registered as artifacts
- **Buffering:** Plots saved before the experiment starts are queued and linked later
- **Thread-safe:** Yes (with reentrance guard to prevent infinite recursion)

## Known Limitations

**Import order:** If your code caches a reference to `parse_args` before expTrack patches it, params won't be captured. Fix: use `exptrack run script.py` (patches before your code runs).

**One experiment per process:** The argparse patch captures into a single `Experiment`. For multiple experiments in one process, use `exp.log_params()` directly.

**Non-argparse parsers:** Click, Fire, Typer, and manual `sys.argv` parsing won't trigger the argparse hook. expTrack falls back to `sys.argv` parsing, which handles `--key value` and `--key=value` but may miss framework-specific formats.

**Notebook deferred start:** `%load_ext exptrack` installs hooks but defers experiment creation until the first real cell runs. The `%load_ext` cell itself is never tracked.

## Debugging Missing Params

1. Check that `exptrack run` wraps your script (not `python script.py`)
2. Run `exptrack show <id>` to verify params are truly empty
3. For non-argparse scripts, ensure arguments use `--key value` format
4. Check stderr for `[exptrack]` warnings
