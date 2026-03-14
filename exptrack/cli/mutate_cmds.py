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
    conn = get_db()
    exp = conn.execute("SELECT id, tags FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp: print(col(f"Not found: {args.id}", R)); return
    tags = json.loads(exp["tags"] or "[]") + [args.tag]
    conn.execute("UPDATE experiments SET tags=? WHERE id=?",
                 (json.dumps(tags), exp["id"]))
    conn.commit()
    print(col(f"Tagged #{args.tag}", G))


def cmd_note(args):
    conn = get_db()
    exp = conn.execute("SELECT id, notes FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp: print(col(f"Not found: {args.id}", R)); return
    new = ((exp["notes"] or "") + "\n" + args.text).strip()
    conn.execute("UPDATE experiments SET notes=? WHERE id=?", (new, exp["id"]))
    conn.commit()
    print(col("Note saved.", G))


def cmd_untag(args):
    conn = get_db()
    exp = conn.execute("SELECT id, tags FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp: print(col(f"Not found: {args.id}", R)); return
    tags = json.loads(exp["tags"] or "[]")
    if args.tag not in tags:
        print(dim(f"Tag '{args.tag}' not found on this experiment.")); return
    tags = [t for t in tags if t != args.tag]
    conn.execute("UPDATE experiments SET tags=? WHERE id=?",
                 (json.dumps(tags), exp["id"]))
    conn.commit()
    print(col(f"Removed #{args.tag}", G))


def cmd_delete_tag(args):
    """Remove a tag from ALL experiments globally."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, tags FROM experiments WHERE tags LIKE ?",
        (f'%"{args.tag}"%',)
    ).fetchall()
    matches = []
    for r in rows:
        tags = json.loads(r["tags"] or "[]")
        if args.tag in tags:
            matches.append(r["id"])
    if not matches:
        print(dim(f"Tag '{args.tag}' not found on any experiment.")); return
    if not getattr(args, "yes", False):
        confirm = input(f"Remove #{args.tag} from {len(matches)} experiment(s)? [y/N] ")
        if confirm.lower() != "y":
            print(dim("Cancelled.")); return
    for exp_id in matches:
        row = conn.execute("SELECT tags FROM experiments WHERE id=?", (exp_id,)).fetchone()
        tags = [t for t in json.loads(row["tags"] or "[]") if t != args.tag]
        conn.execute("UPDATE experiments SET tags=?, updated_at=? WHERE id=?",
                     (json.dumps(tags), datetime.now(timezone.utc).isoformat(), exp_id))
    conn.commit()
    print(col(f"Removed #{args.tag} from {len(matches)} experiment(s).", G))


def cmd_edit_note(args):
    conn = get_db()
    exp = conn.execute("SELECT id, notes FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp: print(col(f"Not found: {args.id}", R)); return
    conn.execute("UPDATE experiments SET notes=? WHERE id=?", (args.text, exp["id"]))
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
        _clean_older_than(conn, older_than, getattr(args, "all_statuses", False))
        return

    rows = conn.execute("SELECT id, name FROM experiments WHERE status='failed'").fetchall()
    if not rows: print(dim("No failed experiments.")); return
    print(f"Found {len(rows)} failed:")
    for r in rows: print(f"  {r['id'][:6]}  {r['name']}")
    if input("Delete all? [y/N] ").lower() == "y":
        for r in rows:
            delete_experiment(conn, r["id"])
        conn.commit()
        print(col(f"Cleaned {len(rows)} experiments (including output files).", G))


def _clean_older_than(conn, age_str: str, all_statuses: bool):
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

    if input(f"Delete {len(rows)} experiment(s)? [y/N] ").lower() == "y":
        for r in rows:
            delete_experiment(conn, r["id"])
        conn.commit()
        print(col(f"Cleaned {len(rows)} experiment(s).", G))


def cmd_finish(args):
    """Manually mark a running experiment as done: exptrack finish <id>"""
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id, name, status, created_at FROM experiments WHERE id LIKE ?",
        (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(col(f"Not found: {args.id}", R)); return

    if exp_row["status"] == "done":
        print(dim(f"Experiment '{exp_row['name']}' is already done.")); return

    now = datetime.now(timezone.utc).isoformat()
    duration = (datetime.fromisoformat(now) -
                datetime.fromisoformat(exp_row["created_at"])).total_seconds()
    with conn:
        conn.execute("""
            UPDATE experiments SET status='done', updated_at=?, duration_s=? WHERE id=?
        """, (now, duration, exp_row["id"]))
    m, s = divmod(duration, 60)
    prev = exp_row["status"]
    print(col(f"Marked '{exp_row['name']}' as done ({prev} -> done, {int(m)}m {s:.0f}s)", G))

    # Fire plugin hooks
    try:
        from ..plugins import registry as plugins
        from .. import config as cfg
        plugins.load_from_config(cfg.load())

        class _FinishProxy:
            """Lightweight proxy so plugins get the expected experiment interface."""
            def __init__(self, row):
                self.id = row["id"]
                self.name = row["name"]
                self.status = "done"
        plugins.on_finish(_FinishProxy(exp_row))
    except Exception as e:
        print(f"[exptrack] warning: plugin hooks failed: {e}", file=sys.stderr)
