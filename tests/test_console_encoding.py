"""A command must print on a console that can't spell its glyphs.

On Windows the console encoding is the system ANSI codepage unless the user
opted into UTF-8, so a `print()` carrying a box-drawing character, an arrow or
an em-dash raises UnicodeEncodeError and the command dies with a traceback
instead of its output. The two commands hit hardest are the ones a notebook
user reaches for first: `notebook-guard` (the cell that makes a shared notebook
run without exptrack) and `session show` (the ASCII tree, drawn with box rails).

The console cases run the real CLI entry point in a subprocess under
`PYTHONIOENCODING=cp1252`, which is the only faithful way to reproduce it —
in-process, pytest owns `sys.stdout` and no monkeypatch of it survives the call.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

from exptrack.cli import admin_cmds, formatting

_RUN_CLI = "from exptrack.cli.main import main; main()"


def _cli_on_ansi_console(*args, cwd=None):
    """Run the CLI with a cp1252 stdout, as a default Windows console has."""
    env = dict(os.environ, PYTHONIOENCODING="cp1252", NO_COLOR="1")
    return subprocess.run([sys.executable, "-c", _RUN_CLI, *args],
                          capture_output=True, text=True, encoding="cp1252",
                          errors="replace", cwd=cwd, env=env)


def test_notebook_guard_prints_on_an_ansi_console(tmp_project):
    """`exptrack notebook-guard` is the answer to "how do I share this
    notebook" — it must not be the command that can't print."""
    r = _cli_on_ansi_console("notebook-guard", cwd=str(tmp_project))
    assert "UnicodeEncodeError" not in r.stderr, r.stderr[-400:]
    assert r.returncode == 0
    assert "load_ext" in r.stdout and "run_cell" in r.stdout


def test_the_guard_cell_is_ascii():
    """The guard is *code the user pastes into a notebook*, so any lossy
    substitution would land in their file. It carries no glyph a non-UTF-8
    console has to translate."""
    offenders = sorted({c for c in admin_cmds.NOTEBOOK_GUARD if ord(c) > 127})
    assert not offenders, f"guard text has non-ASCII: {offenders}"


def test_session_show_draws_its_tree_on_an_ansi_console(tmp_project):
    """`session show` rails are box glyphs; none exist in cp1252. It used to
    die on the first branch."""
    from exptrack.sessions import SessionManager

    sm = SessionManager()
    sid = sm.start("ansi", notebook="n.ipynb")
    sm.checkpoint("cp")
    sm.branch("try-a")
    from exptrack.core.db import close_db
    close_db()

    r = _cli_on_ansi_console("session", "show", sid, cwd=str(tmp_project))
    assert "UnicodeEncodeError" not in r.stderr, r.stderr[-400:]
    assert "try-a" in r.stdout and "cp" in r.stdout
    # and the shape survives as ASCII rather than a wall of identical `?`
    assert "--" in r.stdout, "tree rails should degrade to ASCII, not to `?`"


def test_the_fallback_spells_a_glyph_rather_than_blanking_it():
    """`errors="replace"` keeps the command alive but turns every rail, arrow
    and separator into the same `?`, which loses the shape the tree exists to
    show. The handler spells the ones this CLI draws with."""
    encoded = "├── checkpoint → branch".encode("cp1252", errors="exptrack_ascii")
    assert encoded.decode("cp1252") == "+-- checkpoint -> branch"
    # anything it doesn't know still degrades instead of raising
    assert "☃".encode("cp1252", errors="exptrack_ascii") == b"?"


def test_hardening_leaves_a_utf8_console_alone(monkeypatch):
    """A UTF-8 console loses nothing: no re-encoding, no substitution."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)
    formatting.harden_stdio()
    stream.write("├── checkpoint → branch")
    stream.flush()
    assert stream.buffer.getvalue().decode("utf-8") == "├── checkpoint → branch"


def test_hardening_survives_a_stream_that_cannot_reconfigure(monkeypatch):
    """Under pytest's capture (and any wrapper) stdout is not a real file."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    formatting.harden_stdio()  # must not raise


def test_notebook_logging_prints_on_an_ansi_console(tmp_project):
    """`%exp_log` confirms with `logged acc → <run>`. In a terminal IPython on
    Windows that arrow raised after the metric was written, so the cell
    reported a failure for a write that had succeeded. The notebook module
    never goes through the CLI's main(), so it hardens on its own."""
    code = ("import exptrack.notebook as nb\n"
            "nb.start(lr=0.1)\n"
            "nb.log_last(acc=0.9)\n"
            "nb.done()\n")
    env = dict(os.environ, PYTHONIOENCODING="cp1252", NO_COLOR="1")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, encoding="cp1252", errors="replace",
                       cwd=str(tmp_project), env=env)
    assert "UnicodeEncodeError" not in r.stderr, r.stderr[-400:]
    assert r.returncode == 0, r.stderr[-400:]
    assert "logged acc -> " in r.stdout
