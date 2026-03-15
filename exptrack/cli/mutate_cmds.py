"""
exptrack/cli/mutate_cmds.py — Commands that modify experiments

tag, untag, note, edit-note, rm, clean, finish
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone

from ..core import get_db, delete_experiment
from .formatting import G, R, Y, col, dim


def cmd_tag(args):
    from ..core.queries import find_experiment, update_experiment_tags
    conn = get_db()
    exp = find_experiment(conn, args.id, "id, tags")
    if not exp: print(col(f"Not found: {args.id}", R)); return
    tags = json.loads(exp["tags"] or "[]")
    if args.tag not in tags:
        tags.append(args.tag)
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    print(col(f"Tagged #{args.tag}", G))


def cmd_note(args):
    from ..core.queries import append_note
    conn = get_db()
    result = append_note(conn, args.id, args.text)
    if result.get("error"):
        print(col(f"Not found: {args.id}", R)); return
    conn.commit()
    print(col("Note saved.", G))


def cmd_untag(args):
    from ..core.queries import find_experiment, update_experiment_tags
    conn = get_db()
    exp = find_experiment(conn, args.id, "id, tags")
    if not exp: print(col(f"Not found: {args.id}", R)); return
    tags = json.loads(exp["tags"] or "[]")
    if args.tag not in tags:
        print(dim(f"Tag '{args.tag}' not found on this experiment.")); return
    tags = [t for t in tags if t != args.tag]
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    print(col(f"Removed #{args.tag}", G))


def cmd_delete_tag(args):
    """Remove a tag from ALL experiments globally."""
    from ..core.queries import remove_tag_global
    conn = get_db()
    # Preview count before confirmation
    rows = conn.execute(
        "SELECT id, tags FROM experiments WHERE tags LIKE ?",
        (f'%"{args.tag}"%',)
    ).fetchall()
    match_count = sum(1 for r in rows if args.tag in json.loads(r["tags"] or "[]"))
    if not match_count:
        print(dim(f"Tag '{args.tag}' not found on any experiment.")); return
    if not getattr(args, "yes", False):
        confirm = input(f"Remove #{args.tag} from {match_count} experiment(s)? [y/N] ")
        if confirm.lower() != "y":
            print(dim("Cancelled.")); return
    count = remove_tag_global(conn, args.tag)
    conn.commit()
    print(col(f"Removed #{args.tag} from {count} experiment(s).", G))


def cmd_edit_note(args):
    from ..core.queries import replace_notes
    conn = get_db()
    result = replace_notes(conn, args.id, args.text)
    if result.get("error"):
        print(col(f"Not found: {args.id}", R)); return
    conn.commit()
    print(col("Note updated.", G))


def cmd_rm(args):
    conn = get_db()
    # Check for ambiguous prefix matches — require exact or unique prefix
    matches = conn.execute("SELECT id, name FROM experiments WHERE id LIKE ?",
                           (args.id + "%",)).fetchall()
    if not matches:
        print(col(f"Not found: {args.id}", R)); return
    if len(matches) > 1:
        print(col(f"Ambiguous ID prefix '{args.id}' matches {len(matches)} experiments:", R))
        for m in matches[:10]:
            print(f"  {m['id'][:8]}  {m['name']}")
        print(dim("Provide a longer ID prefix to uniquely identify the experiment."))
        return
    exp = matches[0]
    confirm = input(f"Delete '{exp['name']}' ({exp['id'][:6]})? [y/N] ")
    if confirm.lower() == "y":
        delete_experiment(conn, exp["id"])
        conn.commit()
        print(col("Deleted (including output files).", G))


def cmd_clean(args):
    conn = get_db()
    dry_run = getattr(args, "dry_run", False)

    # --baselines: wipe code_baselines table
    if getattr(args, "baselines", False):
        try:
            n = conn.execute("SELECT COUNT(*) FROM code_baselines").fetchone()[0]
        except Exception as e:
            print(f"[exptrack] warning: could not count code baselines: {e}", file=sys.stderr)
            n = 0
        if not n:
            print(dim("No code baselines stored.")); return
        print(f"Found {n} code baseline(s).")
        if input("Delete all code baselines? [y/N] ").lower() == "y":
            conn.execute("DELETE FROM code_baselines")
            conn.commit()
            print(col(f"Cleared {n} code baseline(s).", G))
        return

    # --older-than: retention policy (e.g. "30d" = 30 days)
    older_than = getattr(args, "older_than", None)
    if older_than:
        _clean_older_than(conn, older_than, getattr(args, "all_statuses", False), dry_run)
        return

    rows = conn.execute("SELECT id, name FROM experiments WHERE status='failed'").fetchall()
    if not rows: print(dim("No failed experiments.")); return
    print(f"Found {len(rows)} failed:")
    for r in rows: print(f"  {r['id'][:6]}  {r['name']}")
    if dry_run:
        print(dim(f"Dry run: would delete {len(rows)} experiment(s).")); return
    if input("Delete all? [y/N] ").lower() == "y":
        for r in rows:
            delete_experiment(conn, r["id"])
        conn.commit()
        print(col(f"Cleaned {len(rows)} experiments (including output files).", G))


def _clean_older_than(conn, age_str: str, all_statuses: bool, dry_run: bool = False):
    """Delete experiments older than the specified age (e.g. '30d')."""
    import re as _re
    match = _re.match(r"(\d+)d$", age_str)
    if not match:
        print(col(f"Invalid age format: '{age_str}'. Use format like '30d' for 30 days.", R))
        return

    days = int(match.group(1))
    cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)

    status_filter = "" if all_statuses else "AND status='failed'"
    rows = conn.execute(f"""
        SELECT id, name, status, created_at FROM experiments
        WHERE created_at < ? {status_filter}
        ORDER BY created_at
    """, (cutoff.isoformat(),)).fetchall()

    if not rows:
        status_desc = "experiments" if all_statuses else "failed experiments"
        print(dim(f"No {status_desc} older than {days} days.")); return

    print(f"Found {len(rows)} experiment(s) older than {days} days:")
    for r in rows[:10]:
        print(f"  {r['id'][:6]}  {r['name'][:50]}  ({r['status']})")
    if len(rows) > 10:
        print(dim(f"  ... and {len(rows) - 10} more"))

    if dry_run:
        print(dim(f"Dry run: would delete {len(rows)} experiment(s).")); return
    if input(f"Delete {len(rows)} experiment(s)? [y/N] ").lower() == "y":
        for r in rows:
            delete_experiment(conn, r["id"])
        conn.commit()
        print(col(f"Cleaned {len(rows)} experiment(s).", G))


def cmd_finish(args):
    """Manually mark a running experiment as done: exptrack finish <id>"""
    from ..core.queries import finish_experiment
    conn = get_db()
    result = finish_experiment(conn, args.id)
    if result.get("error"):
        print(col(f"Not found: {args.id}", R)); return
    if result.get("message") == "already done":
        print(dim(f"Experiment '{result['name']}' is already done.")); return
    conn.commit()

    duration = result["duration_s"]
    m, s = divmod(duration, 60)
    prev = result["prev_status"]
    print(col(f"Marked '{result['name']}' as done ({prev} -> done, {int(m)}m {s:.0f}s)", G))

    # Fire plugin hooks
    try:
        from ..plugins import registry as plugins
        from .. import config as cfg
        plugins.load_from_config(cfg.load())

        class _FinishProxy:
            """Lightweight proxy so plugins get the expected experiment interface."""
            def __init__(self, r):
                self.id = r["id"]
                self.name = r["name"]
                self.status = "done"
        plugins.on_finish(_FinishProxy(result))
    except Exception as e:
        print(f"[exptrack] warning: plugin hooks failed: {e}", file=sys.stderr)


# ── Group commands ────────────────────────────────────────────────────────────

def cmd_group(args):
    """Add an experiment to a group: exptrack group <id> <group>"""
    from ..core.queries import add_to_group
    conn = get_db()
    groups = add_to_group(conn, args.id, args.group)
    if groups is None:
        print(col(f"Not found: {args.id}", R)); return
    conn.commit()
    print(col(f"Added to group '{args.group}'", G))


def cmd_ungroup(args):
    """Remove an experiment from a group: exptrack ungroup <id> <group>"""
    from ..core.queries import remove_from_group
    conn = get_db()
    groups = remove_from_group(conn, args.id, args.group)
    if groups is None:
        print(col(f"Not found: {args.id}", R)); return
    conn.commit()
    print(col(f"Removed from group '{args.group}'", G))


def cmd_groups(args):
    """List all experiment groups: exptrack groups"""
    from ..core.queries import get_groups
    from .formatting import bold, dim, col, C, W, G as GRN, R, Y, fmt_dt
    conn = get_db()
    groups = get_groups(conn)
    if not groups:
        print(dim("No groups defined yet.")); return

    print()
    print(bold(col("  Experiment Groups", W)))
    print(dim("  " + "-" * 60))
    for g in groups:
        status_parts = []
        if g["done"]: status_parts.append(col(f"{g['done']} done", GRN))
        if g["failed"]: status_parts.append(col(f"{g['failed']} failed", R))
        if g["running"]: status_parts.append(col(f"{g['running']} running", Y))
        status_str = ", ".join(status_parts) if status_parts else dim("empty")
        print(f"  {col(g['name'], C):<30} {g['count']} exp(s)  [{status_str}]")
        if g.get("latest"):
            print(dim(f"    latest: {fmt_dt(g['latest'])}"))
    print()


def cmd_delete_group(args):
    """Remove a group from ALL experiments globally: exptrack delete-group <name>"""
    from ..core.queries import remove_group_global, get_all_groups
    conn = get_db()
    # Check if group exists
    all_groups = get_all_groups(conn)
    match = [g for g in all_groups if g["name"] == args.name]
    if not match:
        print(dim(f"Group '{args.name}' not found.")); return
    count = match[0]["count"]
    if not getattr(args, "yes", False):
        confirm = input(f"Remove group '{args.name}' from {count} experiment(s)? [y/N] ")
        if confirm.lower() != "y":
            print(dim("Cancelled.")); return
    removed = remove_group_global(conn, args.name)
    conn.commit()
    print(col(f"Removed group '{args.name}' from {removed} experiment(s).", G))
