# Monkey-Patching in expTrack

expTrack uses monkey-patching to automatically capture parameters and artifacts without requiring changes to user scripts. This document describes how it works, its limitations, and known edge cases.

## What Gets Patched

### argparse (`capture/argparse_patch.py`)

- **What:** `ArgumentParser.parse_args()` and `ArgumentParser.parse_known_args()`
- **When:** Called once when `Experiment()` is created or when `exptrack run` wraps a script
- **Effect:** After the user's script calls `parse_args()`, all parsed arguments are logged as experiment parameters
- **Thread safety:** Protected by `threading.Lock()` — only one thread can apply the patch

### matplotlib (`capture/matplotlib_patch.py`)

- **What:** `plt.savefig()` and `Figure.savefig()`
- **When:** Called when a notebook experiment starts (including deferred start)
- **Effect:** Every saved plot is automatically registered as an artifact. Plots saved before the experiment is created are buffered and flushed later
- **Thread safety:** Protected by `threading.Lock()`. A reentrance guard (`_savefig_in_progress`) prevents infinite recursion when the hooked function calls the original

## Limitations

### Import Order Sensitivity

If user code imports and caches a reference to `argparse.ArgumentParser.parse_args` **before** expTrack patches it, the cached reference points to the original (unpatched) function. Parameters will not be captured.

**Workaround:** Import expTrack before your argument parsing code, or use `exptrack run script.py` which patches before the script runs.

### Single Experiment Per Process

The argparse patch captures into a single `Experiment` object. If you create multiple experiments in one process, only the first one gets argparse parameters. Subsequent experiments should use `exp.log_params()` directly.

### No Automatic Cleanup on Exception

If a script crashes between patch installation and experiment finish, the monkey-patches remain active for the rest of the process lifetime. This is by design — patches are idempotent and the "patch once" guard prevents re-patching.

### Non-argparse Argument Parsers

Scripts using `click`, `fire`, `typer`, or manual `sys.argv` parsing won't trigger the argparse hook. For these, expTrack falls back to raw `sys.argv` parsing (`capture_argv()`), which handles `--key value` and `--key=value` patterns but may miss framework-specific argument formats.

### Matplotlib Version Compatibility

The patch assumes matplotlib's `Figure.savefig` signature. Non-standard matplotlib forks or very old versions may behave unexpectedly. The patch is wrapped in try/except to avoid crashing the user's script if matplotlib is not installed.

### Notebook Deferred Start

In Jupyter notebooks, `%load_ext exptrack` installs the `post_run_cell` hook but defers experiment creation until the first real (non-magic) cell executes. This means:
- The `%load_ext` cell itself is never counted as part of the experiment
- `plt.savefig()` calls in the first cell are buffered and registered once the experiment starts
- If no non-magic cell ever runs, no experiment is created

## Debugging

If parameters aren't being captured:

1. Check that expTrack is imported/initialized before `parse_args()` is called
2. Verify with `exptrack show <id>` that params are empty (not just unlisted)
3. For non-argparse scripts, check that arguments follow `--key value` format
4. Check stderr for `[exptrack]` warning messages
