"""
exptrack/sessions/tree.py — Tree renderers (ASCII for CLI, JSON for dashboard).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _diff_summary(diff: str | None) -> str:
    if not diff:
        return ""
    plus = sum(1 for ln in diff.splitlines()
               if ln.startswith("+") and not ln.startswith("+++"))
    minus = sum(1 for ln in diff.splitlines()
                if ln.startswith("-") and not ln.startswith("---"))
    files = sum(1 for ln in diff.splitlines() if ln.startswith("diff --git"))
    parts = []
    if plus or minus:
        parts.append(f"+{plus} -{minus}")
    if files:
        parts.append(f"{files} file{'s' if files != 1 else ''}")
    return " ".join(parts) if parts else "(diff)"


def _fmt_time(ts: float | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M")
    except Exception:
        return ""


def render_ascii(tree: dict[str, Any]) -> str:
    """Render a session tree as ANSI-colored ASCII art."""
    from ..cli.formatting import C, DIM, G, R, Y, bold, col, dim
    if not tree or "session" not in tree:
        return "(no session)"
    s = tree["session"]
    root = tree.get("root") or {}
    out = []
    started = ""
    if s.get("created_at"):
        try:
            started = datetime.fromtimestamp(s["created_at"]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    header = f"session: {bold(s['name'])}"
    out.append(header)
    sub = []
    if started:
        sub.append(f"started: {started}")
    if s.get("notebook"):
        sub.append(f"notebook: {s['notebook']}")
    if s.get("status"):
        sub.append(f"status: {s['status']}")
    if sub:
        out.append(dim("  •  ".join(sub)))
    out.append("")

    def walk(node: dict, prefix: str, is_last: bool, is_root: bool):
        nt = node.get("node_type", "")
        label = node.get("label", "")
        time_s = _fmt_time(node.get("created_at"))
        diff_s = _diff_summary(node.get("git_diff"))

        if is_root:
            marker = col("○", DIM)
            line = f"{marker} {dim('session start')}: {label}"
        else:
            connector = "└── " if is_last else "├── "
            if nt == "checkpoint":
                marker = col("●", G)
                line = f"{prefix}{connector}{marker} {bold('checkpoint')}: {label}"
            elif nt == "branch":
                marker = col("○", C)
                line = f"{prefix}{connector}{marker} {col('branch', C)}: {label}"
            elif nt == "abandoned":
                marker = col("✗", R)
                line = f"{prefix}{connector}{marker} {col('branch', R)}: {label} {dim('(abandoned)')}"
            else:
                marker = "·"
                line = f"{prefix}{connector}{marker} {label}"
        extras = []
        if time_s:
            extras.append(f"[{time_s}]")
        if diff_s:
            extras.append(f"[diff: {diff_s}]")
        if node.get("exp_id"):
            extras.append(col(f"→ exp {node['exp_id'][:8]}", Y))
        if extras:
            line = line + "  " + dim(" ".join(extras))
        out.append(line)
        if node.get("note"):
            note_prefix = prefix + ("    " if is_last or is_root else "│   ")
            for ln in node["note"].splitlines():
                out.append(note_prefix + dim("  " + ln))

        children = node.get("children", [])
        new_prefix = prefix + ("" if is_root else ("    " if is_last else "│   "))
        for i, ch in enumerate(children):
            walk(ch, new_prefix, i == len(children) - 1, is_root=False)

    if root:
        walk(root, "", True, is_root=True)
    return "\n".join(out)


def render_json(tree: dict[str, Any]) -> dict[str, Any]:
    """Return the tree as a JSON-serializable structure (already is)."""
    return tree


def list_sessions() -> list[dict[str, Any]]:
    """List all sessions with summary counts."""
    from ..core.db import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT s.*, "
        "  COALESCE(SUM(CASE WHEN n.node_type='checkpoint' THEN 1 ELSE 0 END), 0) AS checkpoints, "
        "  COUNT(DISTINCT e.id) AS promoted "
        "FROM sessions s "
        "LEFT JOIN session_nodes n ON n.session_id = s.id "
        "LEFT JOIN experiments e ON e.session_node_id = n.id "
        "GROUP BY s.id "
        "ORDER BY s.created_at DESC",
    ).fetchall()
    return [dict(r) for r in rows]


def find_session(session_id_or_name: str) -> dict | None:
    """Find a session by id prefix or by exact name."""
    from ..core.db import get_db
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sessions WHERE id LIKE ? OR name=? "
        "ORDER BY created_at DESC LIMIT 1",
        (session_id_or_name + "%", session_id_or_name),
    ).fetchone()
    return dict(row) if row else None
