# Troubleshooting

### `ModuleNotFoundError: No module named 'exptrack'`

exptrack isn't installed in the Python environment you're using.

**Jupyter notebooks** often use a different Python than your shell:

```python
import sys
!{sys.executable} -m pip install -e /path/to/exptrack
```

Then **restart the kernel**.

**Scripts** — make sure you install with the same Python you run scripts with:

```bash
python -m pip install -e /path/to/exptrack
```

### `.exptrack/` created in the wrong place

`exptrack init` walks up to find `.git/` and creates `.exptrack/` there. If you're inside a larger repo, use:

```bash
exptrack init --here    # force current directory
```

### Experiments not showing up

exptrack looks for `.exptrack/experiments.db` relative to the project root. If you run scripts from a different directory, it may create a separate `.exptrack/` elsewhere. Always run from within your project directory (where you ran `exptrack init`).

### Params not captured

1. Make sure `exptrack run` wraps your script (patches are applied before your code runs)
2. Check `exptrack show <id>` — params might be captured but just not visible in `ls`
3. For non-argparse scripts, arguments must follow `--key value` or `--key=value` format
4. Look for `[exptrack]` warnings on stderr

### Dashboard port already in use

Usually a previous `exptrack ui` is still running — either you backgrounded it
in a different terminal, or a parent shell died without delivering SIGHUP and
the process got reparented to init. Clean up with:

```bash
exptrack ui-stop --port 7331    # kills whoever is listening on the port
```

Under the hood this uses `fuser` (Linux) or `lsof` (macOS/BSD) to find the PID
and send SIGTERM. Inspect first without killing with `lsof -i :7331`.

### Lost the dashboard auth token

`exptrack ui` prints a URL with `?token=...` on startup. If you close that
terminal, stop and relaunch — a fresh token is generated each run. The token
is in-memory only; it isn't written to disk. If you want a persistent token
that survives restarts, set one explicitly:

```bash
exptrack ui --token mysecret      # saved to .exptrack/config.json
exptrack ui --clear-token         # remove it
```
