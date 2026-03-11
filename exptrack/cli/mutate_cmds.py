"""
exptrack/cli/mutate_cmds.py — Commands that modify experiments

tag, untag, note, edit-note, rm, clean, finish
"""
from __future__ import annotations
import json
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
    exp = conn.execute("SELECT id, name FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp: print(col(f"Not found: {args.id}", R)); return
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
        except Exception:
            n = 0
        if not n:
            print(dim("No code baselines stored.")); return
        print(f"Found {n} code baseline(s).")
        if input("Delete all code baselines? [y/N] ").lower() == "y":
            conn.execute("DELETE FROM code_baselines")
            conn.commit()
            print(col(f"Cleared {n} code baseline(s).", G))
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
