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
