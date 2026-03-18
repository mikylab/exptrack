"""
exptrack/cli/mutate_cmds.py — Commands that modify experiments

tag, untag, note, edit-note, rm, clean, finish
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from ..core import delete_experiment, get_db
from .formatting import G, R, Y, col, dim


def cmd_tag(args):
    from ..core.queries import find_experiment, update_experiment_tags
    conn = get_db()
    # Support both old-style (id=str, tag=str) and new batch-style (id=[...])
    if hasattr(args, "tag"):
        # Old calling convention: tag <id> <tag>
        exp_ids = [args.id] if isinstance(args.id, str) else args.id
        tag_name = args.tag
    else:
        # New convention: last element of id list is the tag name
        all_args = args.id  # list from nargs="+"
        if len(all_args) < 2:
            print(col("Usage: exptrack tag <id> [id2 ...] <tag>", R), file=sys.stderr); return
        tag_name = all_args[-1]
        exp_ids = all_args[:-1]
    count = 0
    for eid in exp_ids:
        exp = find_experiment(conn, eid, "id, tags")
        if not exp:
            print(col(f"Not found: {eid}", R), file=sys.stderr); continue
        tags = json.loads(exp["tags"] or "[]")
        if tag_name not in tags:
            tags.append(tag_name)
        update_experiment_tags(conn, exp["id"], tags)
        count += 1
    conn.commit()
    print(col(f"Tagged #{tag_name} on {count} experiment(s)", G), file=sys.stderr)


def cmd_note(args):
    from ..core.queries import append_note
    conn = get_db()
    result = append_note(conn, args.id, args.text)
    if result.get("error"):
        print(col(f"Not found: {args.id}", R), file=sys.stderr); return
    conn.commit()
    print(col("Note saved.", G), file=sys.stderr)


def cmd_untag(args):
    from ..core.queries import find_experiment, update_experiment_tags
    conn = get_db()
    # Support both old-style (id=str, tag=str) and new batch-style (id=[...])
    if hasattr(args, "tag"):
        exp_ids = [args.id] if isinstance(args.id, str) else args.id
        tag_name = args.tag
    else:
        all_args = args.id  # list from nargs="+"
        if len(all_args) < 2:
            print(col("Usage: exptrack untag <id> [id2 ...] <tag>", R), file=sys.stderr); return
        tag_name = all_args[-1]
        exp_ids = all_args[:-1]
    count = 0
    for eid in exp_ids:
        exp = find_experiment(conn, eid, "id, tags")
        if not exp:
            print(col(f"Not found: {eid}", R), file=sys.stderr); continue
        tags = json.loads(exp["tags"] or "[]")
        if tag_name not in tags:
            print(dim(f"Tag '{tag_name}' not found on {eid}"), file=sys.stderr); continue
        tags = [t for t in tags if t != tag_name]
        update_experiment_tags(conn, exp["id"], tags)
        count += 1
    conn.commit()
    print(col(f"Removed #{tag_name} from {count} experiment(s)", G), file=sys.stderr)


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
        print(col(f"Not found: {args.id}", R), file=sys.stderr); return
    conn.commit()
    print(col("Note updated.", G), file=sys.stderr)


def cmd_rm(args):
    conn = get_db()
    raw_ids = args.id
    exp_ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
    to_delete = []
    for eid in exp_ids:
        matches = conn.execute("SELECT id, name FROM experiments WHERE id LIKE ?",
                               (eid + "%",)).fetchall()
        if not matches:
            print(col(f"Not found: {eid}", R), file=sys.stderr); continue
        if len(matches) > 1:
            print(col(f"Ambiguous ID prefix '{eid}' matches {len(matches)} experiments:", R),
                  file=sys.stderr)
            for m in matches[:10]:
                print(f"  {m['id'][:8]}  {m['name']}", file=sys.stderr)
            print(dim("Provide a longer ID prefix to uniquely identify the experiment."),
                  file=sys.stderr)
            continue
        to_delete.append(matches[0])

    if not to_delete:
        return

    if len(to_delete) == 1:
        prompt = f"Delete '{to_delete[0]['name']}' ({to_delete[0]['id'][:6]})? [y/N] "
    else:
        for exp in to_delete:
            print(f"  {exp['id'][:6]}  {exp['name']}", file=sys.stderr)
        prompt = f"Delete {len(to_delete)} experiment(s)? [y/N] "

    if input(prompt).lower() == "y":
        for exp in to_delete:
            delete_experiment(conn, exp["id"])
        conn.commit()
        print(col(f"Deleted {len(to_delete)} experiment(s) (including output files).", G),
              file=sys.stderr)


def cmd_clean(args):
    conn = get_db()
    dry_run = getattr(args, "dry_run", False)

    # --reset: delete EVERYTHING and VACUUM
    if getattr(args, "reset", False):
        _clean_reset(conn, dry_run)
        return

    # --orphans: purge rows not linked to any existing experiment
    if getattr(args, "orphans", False):
        _clean_orphans(conn, dry_run)
        return

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


def _clean_reset(conn, dry_run: bool = False):
    """Delete ALL experiments and data, VACUUM to shrink DB to minimum."""
    n_exp = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    n_params = conn.execute("SELECT COUNT(*) FROM params").fetchone()[0]
    n_metrics = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    n_artifacts = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    n_timeline = conn.execute("SELECT COUNT(*) FROM timeline").fetchone()[0]

    total = n_exp + n_params + n_metrics + n_artifacts + n_timeline
    if not total:
        print(dim("Database is already empty.")); return

    print(f"This will delete ALL data:")
    print(f"  experiments: {n_exp}")
    print(f"  params:      {n_params}")
    print(f"  metrics:     {n_metrics}")
    print(f"  artifacts:   {n_artifacts}")
    print(f"  timeline:    {n_timeline}")

    if dry_run:
        print(dim(f"Dry run: would delete {total} row(s) and VACUUM.")); return

    if input(col("Delete everything? This cannot be undone. [y/N] ", R)).lower() != "y":
        return

    # Delete experiment files first
    rows = conn.execute("SELECT id FROM experiments").fetchall()
    for r in rows:
        delete_experiment(conn, r["id"])

    # Clear remaining tables
    for table in ("params", "metrics", "artifacts", "timeline",
                  "cell_lineage", "code_baselines", "git_diffs"):
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            pass
    conn.commit()

    # VACUUM to reclaim all space
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except Exception:
        pass

    print(col("Database reset to empty state.", G))


def _clean_older_than(conn, age_str: str, all_statuses: bool, dry_run: bool = False):
    """Delete experiments older than the specified age (e.g. '30d')."""
    import re as _re
    match = _re.match(r"(\d+)d$", age_str)
    if not match:
        print(col(f"Invalid age format: '{age_str}'. Use format like '30d' for 30 days.", R))
        return

    days = int(match.group(1))
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

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


def _clean_orphans(conn, dry_run: bool = False):
    """Purge DB rows and files not linked to any existing experiment."""
    from .. import config as cfg

    orphan_tables = ("params", "metrics", "artifacts", "timeline")
    total = 0
    for table in orphan_tables:
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE exp_id NOT IN (SELECT id FROM experiments)"
        ).fetchone()[0]
        if n:
            print(f"  {table}: {n} orphaned row(s)", file=sys.stderr)
            total += n

    # cell_lineage: cells not referenced by any timeline row
    n_cells = conn.execute(
        "SELECT COUNT(*) FROM cell_lineage "
        "WHERE cell_hash NOT IN ("
        "  SELECT DISTINCT cell_hash FROM timeline WHERE cell_hash IS NOT NULL"
        ")"
    ).fetchone()[0]
    if n_cells:
        print(f"  cell_lineage: {n_cells} unreferenced cell(s)", file=sys.stderr)
        total += n_cells

    # code_baselines: check if any exist
    try:
        n_baselines = conn.execute("SELECT COUNT(*) FROM code_baselines").fetchone()[0]
    except Exception:
        n_baselines = 0
    # Only count as orphans if no experiments exist at all
    exp_count = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    if n_baselines and exp_count == 0:
        print(f"  code_baselines: {n_baselines} row(s) (no experiments remain)",
              file=sys.stderr)
        total += n_baselines
    else:
        n_baselines = 0  # don't delete if experiments still exist

    # notebook_history: snapshots referencing non-existent experiments
    n_snaps = 0
    snap_files = []
    try:
        root = cfg.project_root()
        hist_dir = root / cfg.load().get("notebook_history_dir",
                                          ".exptrack/notebook_history")
        if hist_dir.is_dir():
            exp_ids = {r[0] for r in conn.execute("SELECT id FROM experiments").fetchall()}
            for fp in hist_dir.rglob("*.json"):
                try:
                    snap = json.loads(fp.read_text())
                    if snap.get("exp_id") and snap["exp_id"] not in exp_ids:
                        snap_files.append(fp)
                        n_snaps += 1
                except Exception:
                    continue
            if n_snaps:
                print(f"  notebook_history: {n_snaps} orphaned snapshot(s)",
                      file=sys.stderr)
                total += n_snaps
    except Exception:
        pass

    if not total:
        print(dim("No orphaned data found."), file=sys.stderr)
        return

    if dry_run:
        print(dim(f"Dry run: would purge {total} orphaned item(s)."), file=sys.stderr)
        return

    if input(f"Purge {total} orphaned item(s)? [y/N] ").lower() != "y":
        return

    for table in orphan_tables:
        conn.execute(
            f"DELETE FROM {table} "
            f"WHERE exp_id NOT IN (SELECT id FROM experiments)"
        )
    if n_cells:
        conn.execute(
            "DELETE FROM cell_lineage "
            "WHERE cell_hash NOT IN ("
            "  SELECT DISTINCT cell_hash FROM timeline WHERE cell_hash IS NOT NULL"
            ")"
        )
    if n_baselines:
        conn.execute("DELETE FROM code_baselines")
    conn.commit()

    for fp in snap_files:
        try:
            fp.unlink()
        except Exception:
            pass
    # Clean up empty notebook_history dirs
    try:
        root = cfg.project_root()
        hist_dir = root / cfg.load().get("notebook_history_dir",
                                          ".exptrack/notebook_history")
        if hist_dir.is_dir():
            for d in sorted(hist_dir.rglob("*"), reverse=True):
                if d.is_dir():
                    try:
                        d.rmdir()
                    except OSError:
                        pass
    except Exception:
        pass

    # VACUUM to reclaim space — checkpoint WAL first so VACUUM can shrink it
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except Exception:
        pass

    print(col(f"Purged {total} orphaned item(s).", G), file=sys.stderr)


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
        from .. import config as cfg
        from ..plugins import registry as plugins
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


# ── Study commands ────────────────────────────────────────────────────────────

def cmd_study(args):
    """Add a run to a study: exptrack study <id> <study>"""
    from ..core.queries import add_to_study
    conn = get_db()
    studies = add_to_study(conn, args.id, args.study)
    if studies is None:
        print(col(f"Not found: {args.id}", R)); return
    conn.commit()
    print(col(f"Added to study '{args.study}'", G))


def cmd_unstudy(args):
    """Remove a run from a study: exptrack unstudy <id> <study>"""
    from ..core.queries import remove_from_study
    conn = get_db()
    studies = remove_from_study(conn, args.id, args.study)
    if studies is None:
        print(col(f"Not found: {args.id}", R)); return
    conn.commit()
    print(col(f"Removed from study '{args.study}'", G))


def cmd_studies(args):
    """List all studies: exptrack studies"""
    from ..core.queries import get_studies
    from .formatting import C, R, W, bold, col, dim, fmt_dt
    from .formatting import G as GRN
    conn = get_db()
    studies = get_studies(conn)
    if not studies:
        print(dim("No studies defined yet.")); return

    print()
    print(bold(col("  Studies", W)))
    print(dim("  " + "-" * 60))
    for s in studies:
        status_parts = []
        if s["done"]: status_parts.append(col(f"{s['done']} done", GRN))
        if s["failed"]: status_parts.append(col(f"{s['failed']} failed", R))
        if s["running"]: status_parts.append(col(f"{s['running']} running", Y))
        status_str = ", ".join(status_parts) if status_parts else dim("empty")
        print(f"  {col(s['name'], C):<30} {s['count']} exp(s)  [{status_str}]")
        if s.get("latest"):
            print(dim(f"    latest: {fmt_dt(s['latest'])}"))
    print()


def cmd_delete_study(args):
    """Remove a study from ALL runs globally: exptrack delete-study <name>"""
    from ..core.queries import get_all_studies, remove_study_global
    conn = get_db()
    all_studies = get_all_studies(conn)
    match = [s for s in all_studies if s["name"] == args.name]
    if not match:
        print(dim(f"Study '{args.name}' not found.")); return
    count = match[0]["count"]
    if not getattr(args, "yes", False):
        confirm = input(f"Remove study '{args.name}' from {count} experiment(s)? [y/N] ")
        if confirm.lower() != "y":
            print(dim("Cancelled.")); return
    removed = remove_study_global(conn, args.name)
    conn.commit()
    print(col(f"Removed study '{args.name}' from {removed} experiment(s).", G))


def cmd_stage(args):
    """Set stage number and optional label on a run: exptrack stage <id> <number> [--name label]"""
    from ..core.queries import find_experiment, update_experiment_stage
    conn = get_db()
    exp = find_experiment(conn, args.id, "id")
    if not exp:
        print(col(f"Not found: {args.id}", R)); return
    update_experiment_stage(conn, exp["id"], args.number, args.name)
    conn.commit()
    label = f" ({args.name})" if args.name else ""
    print(col(f"Set stage {args.number}{label} on {exp['id'][:12]}", G))
