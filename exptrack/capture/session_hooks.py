"""
exptrack/capture/session_hooks.py — IPython magics for Session Trees.

Registers:
    %exptrack session start "name"
    %exptrack session end
    %exptrack checkpoint "label"
    %exptrack branch "label"
    %exptrack promote "label"
    %%scratch                 (cell magic — runs cell but is never logged)

When no session is active, all line magics (except `session start`) are
silent no-ops, leaving existing %load_ext exptrack tracking unaffected.
"""
from __future__ import annotations

import shlex
import sys

from ..sessions import SessionManager, get_current_session, set_current_session


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _parse_args(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:
        return line.strip().split()


def _exptrack_magic(line: str):
    """Top-level dispatcher for `%exptrack <subcommand> ...`."""
    args = _parse_args(line)
    if not args:
        print("[exptrack] usage: %exptrack <session|checkpoint|branch|promote> ...",
              file=sys.stderr)
        return
    cmd = args[0]
    rest = " ".join(args[1:]).strip()

    if cmd == "session":
        if not args[1:]:
            print("[exptrack] usage: %exptrack session start <name> | end",
                  file=sys.stderr)
            return
        sub = args[1]
        sub_rest = _strip_quotes(" ".join(args[2:]).strip())
        if sub == "start":
            return _session_start(sub_rest)
        if sub == "end":
            return _session_end()
        print(f"[exptrack] unknown session subcommand: {sub}", file=sys.stderr)
        return

    if cmd == "checkpoint":
        return _checkpoint(_strip_quotes(rest))
    if cmd == "branch":
        return _branch(_strip_quotes(rest))
    if cmd == "promote":
        return _promote(_strip_quotes(rest))

    print(f"[exptrack] unknown magic: %exptrack {cmd}", file=sys.stderr)


def _session_start(name: str):
    if not name:
        print("[exptrack] session start requires a name", file=sys.stderr)
        return
    sm = get_current_session()
    if sm is not None and sm.session_id:
        print(f"[exptrack] session already active: {sm.session_id[:8]}",
              file=sys.stderr)
        return
    nb = ""
    try:
        from ..notebook import _detect_nb_name
        nb = _detect_nb_name()
    except Exception:
        pass
    sm = SessionManager()
    sid = sm.start(name, notebook=nb)
    set_current_session(sm)
    print(f"[exptrack] session started: {name}  ({sid[:8]})")


def _session_end():
    sm = get_current_session()
    if sm is None or not sm.session_id:
        return  # silent no-op
    sm.end()
    set_current_session(None)
    print("[exptrack] session ended.")


def _checkpoint(label: str):
    sm = get_current_session()
    if sm is None or not sm.session_id:
        return  # silent no-op
    if not label:
        print("[exptrack] checkpoint requires a label", file=sys.stderr)
        return
    nid = sm.checkpoint(label)
    if nid:
        print(f"[exptrack] checkpoint: {label}  ({nid[:8]})")


def _branch(label: str):
    sm = get_current_session()
    if sm is None or not sm.session_id:
        return  # silent no-op
    if not label:
        print("[exptrack] branch requires a label", file=sys.stderr)
        return
    nid = sm.branch(label)
    if nid is None:
        print("[exptrack] cannot branch — no checkpoint yet. Run %exptrack checkpoint first.",
              file=sys.stderr)
        return
    print(f"[exptrack] branch: {label}  ({nid[:8]})")


def _promote(label: str):
    sm = get_current_session()
    if sm is None or not sm.session_id:
        return  # silent no-op
    try:
        from ..notebook import current
        exp = current()
    except Exception:
        exp = None
    if exp is None:
        print("[exptrack] no active experiment to promote — start one with "
              "%load_ext exptrack first", file=sys.stderr)
        return
    sm.promote(label, exp.id)
    print(f"[exptrack] promoted experiment {exp.id[:8]} to current session node")


def _pin_magic(line: str, cell: str):
    """Cell magic — execute the cell, capture stdout + last expression value,
    and snapshot it as a markdown artifact on the active experiment.

    Usage:
        %%pin "label describing this result"
        df.describe()

    Saves `pin_<timestamp>_<label>.md` into the active Experiment's output
    directory (and registers it as an artifact). If a session is active, also
    appends "pinned: label" to the current node's note.
    """
    import ast
    import contextlib
    import io
    import re
    from datetime import datetime
    from pathlib import Path

    label = _strip_quotes(line.strip()) or "pin"
    try:
        from IPython import get_ipython
        ip = get_ipython()
    except Exception:
        ip = None
    if ip is None:
        return

    buf = io.StringIO()
    result_repr = None
    err = None
    try:
        # Split off the trailing expression so its value is captured like
        # IPython would normally render it
        try:
            tree = ast.parse(cell, mode="exec")
        except SyntaxError as e:
            err = f"SyntaxError: {e}"
            tree = None

        with contextlib.redirect_stdout(buf):
            if tree is not None:
                trailing = None
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    trailing = tree.body.pop()
                exec(compile(ast.Module(body=tree.body, type_ignores=[]),
                             "<pin>", "exec"),
                     ip.user_ns)
                if trailing is not None:
                    val = eval(compile(ast.Expression(trailing.value),
                                       "<pin>", "eval"),
                               ip.user_ns)
                    if val is not None:
                        try:
                            result_repr = repr(val)
                        except Exception as e:
                            result_repr = f"<repr error: {e}>"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"

    captured = buf.getvalue()
    # Echo back to the user so the cell behaves like a normal one
    if captured:
        sys.stdout.write(captured)
    if result_repr is not None:
        print(result_repr)
    if err:
        print(f"[exptrack:pin] {err}", file=sys.stderr)

    # Save artifact onto the active experiment
    try:
        from ..notebook import current
        exp = current()
    except Exception:
        exp = None
    if exp is None:
        print("[exptrack:pin] no active experiment — start one with "
              "%load_ext exptrack to attach pins", file=sys.stderr)
        return

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)[:40] or "pin"
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    fname = f"pin_{ts}_{safe}.md"
    body_parts = [
        f"# Pinned: {label}",
        "",
        f"_Captured at {datetime.now().isoformat(timespec='seconds')}_",
        "",
        "## Cell source",
        "",
        "```python",
        cell.rstrip(),
        "```",
        "",
        "## Output",
        "",
        "```",
        captured.rstrip() or "(no stdout)",
        "```",
    ]
    if result_repr is not None:
        body_parts += ["", "## Result", "", "```", result_repr, "```"]
    if err:
        body_parts += ["", "## Error", "", "```", err, "```"]
    try:
        target: Path = exp.save_output(fname)
        target.write_text("\n".join(body_parts))
        print(f"[exptrack] pinned: {target.name} (artifact attached to {exp.id[:8]})")
    except Exception as e:
        print(f"[exptrack:pin] could not save artifact: {e}", file=sys.stderr)
        return

    try:
        sm = get_current_session()
        if sm is not None:
            sm.append_to_current_note(f"pinned: {label} → {fname}")
    except Exception:
        pass


def _scratch_magic(line: str, cell: str):
    """Cell magic — execute the cell but tag it so logging is skipped.

    The notebook_hooks._post_run_cell handler checks the raw cell for
    a leading `%%scratch` and bails out early. We just exec the body here.
    """
    try:
        from IPython import get_ipython
        ip = get_ipython()
    except Exception:
        ip = None
    if ip is None:
        return
    try:
        compiled = compile(cell, "<scratch>", "exec")
        exec(compiled, ip.user_ns)
    except Exception as e:
        print(f"[exptrack:scratch] {type(e).__name__}: {e}", file=sys.stderr)


def is_scratch_cell(source: str) -> bool:
    """Return True if a cell source begins with %%scratch."""
    if not source:
        return False
    for ln in source.splitlines():
        s = ln.strip()
        if not s:
            continue
        return s.startswith("%%scratch")
    return False


def register_session_magics(ip) -> None:
    """Register the %exptrack, %%scratch, and %%pin magics on the given IPython shell."""
    ip.register_magic_function(_exptrack_magic, magic_kind="line", magic_name="exptrack")
    ip.register_magic_function(_scratch_magic, magic_kind="cell", magic_name="scratch")
    ip.register_magic_function(_pin_magic, magic_kind="cell", magic_name="pin")
