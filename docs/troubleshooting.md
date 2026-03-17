# Troubleshooting

### `ModuleNotFoundError: No module named 'exptrack'`

expTrack is not installed in the Python environment you're using.

**In Jupyter notebooks**, the kernel's Python is often different from your shell's Python:

```python
import sys
!{sys.executable} -m pip install -e /path/to/exptrack
```

Then **restart the kernel**.

**In scripts**, use the same Python you run scripts with:

```bash
python -m pip install -e /path/to/exptrack
```

### `exptrack init` created `.exptrack/` in the wrong place

`exptrack init` walks up from your current directory looking for `.git/`. If you're inside a larger git repo, `.exptrack/` ends up at the git root. Force creation in the current directory:

```bash
exptrack init --here
```

### Experiments not showing up

expTrack stores data in `.exptrack/experiments.db` relative to the project root. If you run scripts from a different directory than where you initialized, expTrack may create a new `.exptrack/` elsewhere. Always run from within your project directory.
