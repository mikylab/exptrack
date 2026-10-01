"""A temp HOME for test *subprocesses*.

pytest's autouse `_never_the_real_user_dir` fixture (conftest.py) points HOME
at a temp directory for every test in the suite, because `exptrack init` and
`exptrack ui start` both register the current project in
`~/.exptrack/projects.json` — user-global state that belongs to the person
running the tests, not to the tests.

A fixture cannot cover the runners that execute test files as *separate
processes*: `tests/run_all.py` (the legacy per-file runner, also in CI) spawns
each file with `sys.executable`, and `tests/smoke.py` drives the real CLI in a
fresh subprocess per command. Neither loads conftest.py, so both ran against
the developer's real HOME and appended their temp directories to the real
registry on every run — which is how the project switcher filled up with dead
`tmp*` entries nobody could click.

The isolation is applied to the runner's **own environment**, not threaded
through each `subprocess.run(env=...)` call. A child inherits the environment
by default, so one call at import time covers every process either runner
spawns — including the `git` invocations and anything added later. Threading
`env=` per call site made the next `subprocess.run` someone adds a silent
regression back to the real HOME.
"""
from __future__ import annotations

import contextlib
import os
import tempfile


def isolate_home(prefix: str) -> tempfile.TemporaryDirectory:
    """Point this process (and so its children) at a throwaway HOME.

    Returns the temp-directory handle; the caller keeps it alive for as long
    as it spawns children and lets it clean up on exit. A child that writes
    there afterwards simply recreates it, which is harmless.

    Both HOME and USERPROFILE are set: `os.path.expanduser("~")` reads
    USERPROFILE first on Windows, so setting only HOME isolates nothing there
    — the exact platform the registry clutter was found on.
    """
    handle = tempfile.TemporaryDirectory(prefix=prefix)
    os.environ["HOME"] = handle.name
    os.environ["USERPROFILE"] = handle.name
    return handle


@contextlib.contextmanager
def project_tempdir():
    """A throwaway directory to ``chdir`` into and build a project in.

    Replaces the bare ``with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)`` these tests used to open with, which only ever passed on
    Linux and macOS. Windows refuses to delete a file something still holds
    open, and refuses to delete a process's working directory — and at the
    moment that block's cleanup ran, the thread's cached `get_db()` connection
    still held ``experiments.db`` and the process was still standing in the
    directory. Every such test passed its assertions and then failed on
    ``PermissionError: [WinError 32]`` in `TemporaryDirectory.cleanup`.

    So the exit does, in order, what Windows needs before the delete: close
    the cached connection, and step back to the directory the test started
    in. Both are harmless where they were not needed, which is what keeps the
    Linux and macOS runs byte-for-byte what they were.
    """
    saved = os.getcwd()
    handle = tempfile.TemporaryDirectory()
    try:
        os.chdir(handle.name)
        yield handle.name
    finally:
        try:
            from exptrack.core import db as _db
            _db.close_db(sweep=False, checkpoint=False)
        except Exception:
            pass
        os.chdir(saved)
        handle.cleanup()
