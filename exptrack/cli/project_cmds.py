"""
exptrack/cli/project_cmds.py — inspecting and pruning the project registry.

The dashboard's switcher reads the same list. These commands exist so the
registry is inspectable and fixable without opening a browser, and so a stale
entry has an obvious remedy. This module stays thin: `forget()` and
`discover()` live in `projects.py` so the dashboard's dismiss control can call
the same logic without going through argparse.
"""
from __future__ import annotations

import sys

from .. import config as cfg
from .. import projects
from .formatting import G, Y, col, die, dim


def cmd_project(args):
    """Dispatch for `exptrack project <subcommand>`."""
    sub = getattr(args, "project_sub", None)
    if sub == "forget":
        return _project_forget(args)
    return _project_list(args)


def _project_list(args):
    try:
        found = projects.discover(current_root=cfg.project_root())
    except Exception as e:                      # discovery must never crash
        die(f"Could not read the project list: {e}")
    if not found:
        print(dim("No projects registered. A project is remembered when you "
                  "run `exptrack init` or `exptrack ui start` in it."),
              file=sys.stderr)
        return
    for entry in found:
        marker = "" if entry["status"] == projects.SCHEMA_OK else \
            col(f"  [{entry['status']}]", Y)
        print(f"{entry['name']:<20} {entry['path']}{marker}")
        if entry["message"]:
            print(dim(f"  {entry['message']}"), file=sys.stderr)


def _project_forget(args):
    if not projects.forget(args.name):
        die(f"No registered project named {args.name!r}. "
            f"List them with: exptrack project list")
    print(col(f"Forgot project {args.name!r}.", G), file=sys.stderr)
