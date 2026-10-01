"""
exptrack/dashboard/routes/write_routes/projects.py — dismissing a project
from the switcher.
"""
from __future__ import annotations

from ._shared import body_str


def api_project_forget(body: dict) -> dict:
    """Drop a registered project from the switcher — the dashboard's half of
    `exptrack project forget`.

    Takes the server-issued **id**, never a path: accepting a path here would
    let an authenticated request name any directory on the machine, the same
    hazard `_activate_requested_project` already guards against for every
    other project-scoped request. The id is resolved through
    `projects.discover`, the same listing `/api/projects` itself returns —
    ids there are path-derived hashes, so a path posted as `id` can never
    match one, and an id discover() doesn't recognise is refused rather than
    guessed at (never falls back to "forget whatever's active").

    Calls `projects.forget` — the same function `exptrack project forget`
    calls, not a reimplementation, and it already invalidates the discovery
    cache, so the very next `/api/projects` reflects the removal. Forgetting
    only edits the registry: it never touches the project's database or any
    file under its root, which is why the response says so explicitly rather
    than leaving that to be inferred from a bare `{"ok": true}`.
    """
    from exptrack import config as cfg
    from exptrack import projects

    requested = body_str(body, "id")
    if not requested:
        return {"error": "missing id"}

    root = cfg.project_root()
    match = next((e for e in projects.discover(current_root=root)
                  if e["id"] == requested), None)
    if match is None:
        return {"error": "unknown project"}

    ok = projects.forget(match["path"])
    return {
        "ok": ok,
        "id": requested,
        "note": "Removed from the project list only — its database and "
                "files were not touched.",
    }
