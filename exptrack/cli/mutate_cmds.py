"""
exptrack/cli/mutate_cmds.py — Commands that modify experiments

tag, untag, note, edit-note, rm, clean, finish
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import config as cfg
from ..core import delete_experiment, get_db
from ..core.db import _sweep_blobs, _trash_or_local
from .formatting import (
    G,
    R,
    Y,
    col,
    confirm,
    die,
    dim,
    fmt_bytes,
    parse_age_delta,
)

# Below this a "freed space" note is noise — a couple of pages moving to the
# free list is not something anyone acts on.
_RECLAIM_NOTE_MIN_BYTES = 256 * 1024


def _free_bytes(conn) -> int:
    """Bytes on the database's free list right now (cheap: two pragmas)."""
    from ..core.storage import free_space
    return free_space(conn)["bytes"]


def _print_reclaimed(conn, before: int):
    """Say what a delete actually freed, and how to get it back from the file.

    A delete removes the rows immediately, but SQLite moves their pages to the
    file's free list rather than shrinking the file — so `ls` shows the same
    size afterwards and the delete looks like it did nothing. Reporting the
    delta (and naming the one command that returns it to the filesystem) is
    the difference between "that worked" and "that silently failed". Call
    after ``conn.commit()``; the free list only moves when the write lands.
    """
    freed = max(0, _free_bytes(conn) - before)
    if freed < _RECLAIM_NOTE_MIN_BYTES:
        return
    print(dim(f"  ~{fmt_bytes(freed)} freed inside the database file — reusable "
              f"immediately. Run \"exptrack clean --vacuum\" to return it to "
              f"the filesystem."), file=sys.stderr)


def cmd_tag(args):
    from ..core.queries import find_experiment, update_experiment_tags
    conn = get_db()
    # `id` is nargs="+"; the last element is the tag name, the rest are exp ids.
    all_args = args.id
    if len(all_args) < 2:
        die("Usage: exptrack tag <id> [id2 ...] <tag>")
    tag_name = all_args[-1]
    exp_ids = all_args[:-1]
    count = 0
    missing = 0
    for eid in exp_ids:
        exp = find_experiment(conn, eid, "id, tags")
        if not exp:
            print(col(f"Not found: {eid}", R), file=sys.stderr); missing += 1; continue
        tags = json.loads(exp["tags"] or "[]")
        if tag_name not in tags:
            tags.append(tag_name)
        update_experiment_tags(conn, exp["id"], tags)
        count += 1
    conn.commit()
    print(col(f"Tagged #{tag_name} on {count} experiment(s)", G), file=sys.stderr)
    # A script tagging a list of ids must be able to detect a typo'd/unknown id;
    # note/study/edit-note already die() on a missing id, so match them.
    if missing:
        sys.exit(1)


def cmd_note(args):
    from ..core.queries import append_note
    conn = get_db()
    result = append_note(conn, args.id, args.text)
    if result.get("error"):
        die(f"Not found: {args.id}")
    conn.commit()
    print(col("Note saved.", G), file=sys.stderr)


def cmd_variant_of(args):
    """Point a run at the run it should be compared against.

    Chronology is the wrong baseline for the "same notebook, different model"
    loop — the previous run of the script is whatever happened to run last, not
    the run you mean. Declaring a target overrides that everywhere the delta is
    computed. Omit the baseline to clear the link.
    """
    from ..core.queries import set_variant_of
    conn = get_db()
    result = set_variant_of(conn, args.id, args.baseline)
    if result.get("error"):
        die(result["error"])
    if result.get("variant_of"):
        print(col(f"Baseline set: comparing against {result['name']}.", G), file=sys.stderr)
    else:
        print(col("Baseline cleared — back to the previous run by time.", G),
              file=sys.stderr)


def cmd_primary_metric(args):
    """Show, set or clear the metric runs are judged by, at one of three levels.

    A bare ``exptrack primary-metric`` **shows** what is set; clearing takes
    ``--clear``. It used to clear on the bare form, which made the obvious way
    to check a setting silently destroy it — and print "cleared", which reads as
    confirmation of an action nobody asked for. ``exptrack reference`` follows
    the same convention; two levelled-setting commands with opposite bare-form
    semantics, one of them destructive, is a trap rather than a shorthand.

    Which level is written is the whole point of the command, so it is chosen
    explicitly (``--run`` / ``--study``) rather than inferred: the levels
    resolve run → study → project, and silently writing the wrong one leaves a
    setting that appears to do nothing because a more specific level shadows it.
    """
    from ..core import primary_metric as pm
    from ..core.queries import find_experiment

    key = (args.key or "").strip()
    goal = (args.goal or "").strip()
    clear = getattr(args, "clear", False)

    if not key and not clear:
        _print_primary_metrics(args, pm)
        return

    if args.run:
        conn = get_db()
        exp = find_experiment(conn, args.run, "id, name")
        if not exp:
            die(f"Not found: {args.run}")
        pm.set_run_primary_metric(conn, exp["id"], key, goal)
        where = f"run {exp['name']}"
    elif args.study:
        result = pm.set_study_primary_metric(args.study, key, goal)
        if result.get("error"):
            die(result["error"])
        where = f"study '{args.study}'"
    else:
        pm.set_project_primary_metric(key, goal)
        where = "this project"

    if not key:
        print(col(f"Primary metric cleared for {where}.", G), file=sys.stderr)
        return
    resolved = goal or pm.goal_for_key(key)
    how = "" if goal else " (inferred from the name)"
    print(col(f"Primary metric for {where}: {key} — {resolved}imize{how}.", G),
          file=sys.stderr)


def _print_primary_metrics(args, pm):
    """What is configured, at whichever level the flags name.

    The run level is a param, the other two are config, so there is no single
    listing — the command shows the level you asked about, and the project
    default beneath it, since that is what a narrower level shadows.
    """
    from ..core.queries import find_experiment
    from .formatting import dim

    lines = []
    if args.run:
        conn = get_db()
        exp = find_experiment(conn, args.run, "id, name")
        if not exp:
            die(f"Not found: {args.run}")
        lines.append((f"run {exp['name']}", pm.run_primary_metric(conn, exp["id"])))
    if args.study:
        lines.append((f"study '{args.study}'", pm.study_primary_metric(args.study)))
    lines.append(("this project", pm.project_primary_metric()))

    if not any(spec for _, spec in lines):
        print(dim("No primary metric set — each run falls back to a metric "
                  "chosen from its own. Set one with "
                  "`exptrack primary-metric <key>`."), file=sys.stderr)
        return
    for label, spec in lines:
        if not spec:
            print(f"{label:<24} " + dim("not set"), file=sys.stderr)
            continue
        goal = spec["goal"] or pm.goal_for_key(spec["key"])
        how = "" if spec["goal"] else dim(" (inferred)")
        print(f"{label:<24} {spec['key']} — {goal}imize{how}", file=sys.stderr)


def cmd_reference(args):
    """Show, set or clear the run everything else is measured against.

    A bare ``exptrack reference`` shows what is pinned; clearing takes
    ``--clear``. ``primary-metric`` follows the same convention.
    """
    from ..core import reference as ref

    conn = get_db()
    study = (getattr(args, "study", "") or "").strip()
    where = f"study '{study}'" if study else "this project"

    if not args.id and not args.clear:
        _print_references(conn, ref)
        return

    # No pre-lookup: set_reference resolves the id itself, with the same prefix
    # semantics, and additionally refuses a trashed run — so a second
    # find_experiment here would be a duplicate query and a second wording for
    # "not found".
    result = ref.set_reference(conn, "" if args.clear else args.id, study)
    if result.get("error"):
        die(result["error"])
    if args.clear:
        print(col(f"Reference cleared for {where}.", G), file=sys.stderr)
    else:
        print(col(f"Reference for {where}: {result['name']}", G), file=sys.stderr)
        if result.get("warning"):
            print(col(f"  note: {result['warning']}", Y), file=sys.stderr)


def _print_references(conn, ref):
    """The configured references, resolved — including the broken ones.

    A reference pointing at a deleted or trashed run is the failure this
    command exists to surface: nothing else tells you the comparison you have
    been reading stopped happening.
    """
    from .formatting import dim

    conf = ref.all_configured(conn)
    if not conf["project"] and not conf["studies"]:
        print(dim("No reference run set. Set one with "
                  "`exptrack reference <id>`."), file=sys.stderr)
        return

    entries = ([(conf["project"], "project")] if conf["project"] else [])
    entries += [(e, f"study {e['study']}") for e in conf["studies"]]
    for entry, label in entries:
        if entry["stale"] == ref.STALE_MISSING:
            state = col(f"  ← run {entry['id'][:8]} no longer exists", R)
        elif entry["stale"] == ref.STALE_TRASHED:
            state = col("  ← in the Trash; restore it or set another", R)
        else:
            state = dim(f"  {entry['status']}")
        print(f"{label:<24} {entry['name'] or entry['id']}{state}", file=sys.stderr)


def cmd_untag(args):
    from ..core.queries import find_experiment, update_experiment_tags
    conn = get_db()
    # `id` is nargs="+"; the last element is the tag name, the rest are exp ids.
    all_args = args.id
    if len(all_args) < 2:
        die("Usage: exptrack untag <id> [id2 ...] <tag>")
    tag_name = all_args[-1]
    exp_ids = all_args[:-1]
    count = 0
    missing = 0
    for eid in exp_ids:
        exp = find_experiment(conn, eid, "id, tags")
        if not exp:
            print(col(f"Not found: {eid}", R), file=sys.stderr); missing += 1; continue
        tags = json.loads(exp["tags"] or "[]")
        if tag_name not in tags:
            print(dim(f"Tag '{tag_name}' not found on {eid}"), file=sys.stderr); continue
        tags = [t for t in tags if t != tag_name]
        update_experiment_tags(conn, exp["id"], tags)
        count += 1
    conn.commit()
    print(col(f"Removed #{tag_name} from {count} experiment(s)", G), file=sys.stderr)
    if missing:
        sys.exit(1)


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
        print(dim(f"Tag '{args.tag}' not found on any experiment."), file=sys.stderr); return
    if not confirm(f"Remove #{args.tag} from {match_count} experiment(s)? [y/N] ",
                   getattr(args, "yes", False)):
        print(dim("Cancelled.")); return
    count = remove_tag_global(conn, args.tag)
    conn.commit()
    print(col(f"Removed #{args.tag} from {count} experiment(s).", G))


def cmd_edit_note(args):
    from ..core.queries import replace_notes
    conn = get_db()
    result = replace_notes(conn, args.id, args.text)
    if result.get("error"):
        die(f"Not found: {args.id}")
    conn.commit()
    print(col("Note updated.", G), file=sys.stderr)


def cmd_trash(args):
    """List the runs in the Trash — the CLI half of a recoverable delete.

    Sessions have had `session trash` since Session Trees shipped; experiments
    had no listing, no restore and no soft delete from the terminal at all, so
    a CLI-only user's `rm` was always permanent.
    """
    from ..core.db import list_trashed_experiments
    from .formatting import fmt_dt

    conn = get_db()
    rows = list_trashed_experiments(conn)
    if not rows:
        print(dim("Trash is empty.")); return
    print()
    print(f"  {'ID':<8}{'NAME':<34}{'STATUS':<10}TRASHED")
    print(dim("  " + "-" * 74))
    for r in rows:
        print(f"  {col(r['id'][:6], Y):<17}{r['name'][:32]:<34}"
              f"{r['status']:<10}{fmt_dt(r['deleted_at'])}")
    print()
    print(dim(f"  {len(rows)} run(s). Restore with `exptrack restore-run <id>`, "
              f"or delete permanently with `exptrack rm <id>`."))


def cmd_restore_run(args):
    """Bring a run back out of the Trash."""
    from ..core.db import restore_experiment
    from ..core.queries import find_experiment

    conn = get_db()
    # Single-run lookups deliberately see trashed runs (see storage.md), which
    # is what makes this resolvable at all.
    exp = find_experiment(conn, args.id, "id, name, deleted_at")
    if not exp:
        die(f"Not found: {args.id}")
    if not exp.get("deleted_at"):
        print(dim(f"'{exp['name']}' is not in the Trash.")); return
    restore_experiment(conn, exp["id"])
    conn.commit()
    print(col(f"Restored '{exp['name']}'.", G), file=sys.stderr)


def cmd_rm(args):
    from ..core.queries import AmbiguousPrefixError, find_experiment
    conn = get_db()
    raw_ids = args.id
    exp_ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
    to_delete = []
    for eid in exp_ids:
        # One lookup rule for every command: `find_experiment` escapes the
        # prefix's LIKE wildcards (`exptrack rm %` matched — and offered to
        # permanently delete — every run in the project) and refuses an
        # ambiguous one rather than resolving to whichever row sorts first.
        try:
            match = find_experiment(conn, eid, "id, name")
        except AmbiguousPrefixError as e:
            print(col(f"Ambiguous ID prefix '{eid}' matches "
                      f"{len(e.matches)} experiments:", R), file=sys.stderr)
            for mid, mname in e.matches[:10]:
                print(f"  {mid[:8]}  {mname}", file=sys.stderr)
            print(dim("Provide a longer ID prefix to uniquely identify the experiment."),
                  file=sys.stderr)
            continue
        if not match:
            print(col(f"Not found: {eid}", R), file=sys.stderr); continue
        to_delete.append(match)

    if not to_delete:
        return

    if len(to_delete) == 1:
        prompt = f"Delete '{to_delete[0]['name']}' ({to_delete[0]['id'][:6]})? [y/N] "
    else:
        for exp in to_delete:
            print(f"  {exp['id'][:6]}  {exp['name']}", file=sys.stderr)
        prompt = f"Delete {len(to_delete)} experiment(s)? [y/N] "

    to_trash = getattr(args, "trash", False)
    keep_files = getattr(args, "keep_files", False)
    if to_trash:
        prompt = prompt.replace("Delete", "Move to Trash:", 1)

    if not confirm(prompt, getattr(args, "yes", False)):
        return

    if to_trash:
        # Recoverable, like the dashboard's delete and like `session rm` — the
        # CLI could previously only delete permanently, so a terminal-only user
        # had no undo at all.
        from ..core.db import trash_experiment
        for exp in to_delete:
            trash_experiment(conn, exp["id"])
        conn.commit()
        print(col(f"Moved {len(to_delete)} experiment(s) to the Trash "
                  f"(restore with `exptrack restore-run <id>`).", G), file=sys.stderr)
        return

    free_before = _free_bytes(conn)
    for exp in to_delete:
        delete_experiment(conn, exp["id"], delete_files=not keep_files,
                          reclaim_blobs=False)
    _sweep_blobs(conn)  # once for the batch, not per run
    conn.commit()
    what = "records only" if keep_files else "including output files"
    print(col(f"Deleted {len(to_delete)} experiment(s) ({what}).", G),
          file=sys.stderr)
    _print_reclaimed(conn, free_before)


def cmd_clean(args):
    """Delete data, by one of several selections.

    The selections are mutually exclusive, but ``--vacuum`` is not a selection —
    it is "and then hand the free pages back to the filesystem". Dispatching on
    the first matching flag made ``clean --older-than 30d --vacuum`` run *only*
    the VACUUM: exit 0, no warning, and the retention delete the user asked for
    silently never happened. Now a selection runs, and ``--vacuum`` runs after
    it.
    """
    conn = get_db()
    dry_run = getattr(args, "dry_run", False)
    assume_yes = getattr(args, "yes", False)
    vacuum = getattr(args, "vacuum", False)

    # Each selection paired with what runs it, so the flag name is written once
    # instead of appearing in a tuple, a dispatcher and an error message.
    handlers = [
        ("reset", lambda: _clean_reset(conn, dry_run, assume_yes)),
        ("orphans", lambda: _clean_orphans(conn, dry_run, assume_yes)),
        ("baselines", lambda: _clean_baselines(conn, dry_run, assume_yes)),
        ("older-than", lambda: _clean_older_than(
            conn, args.older_than, getattr(args, "all_statuses", False),
            dry_run, assume_yes)),
    ]
    chosen = [(name, run) for name, run in handlers
              if getattr(args, name.replace("-", "_"), None)]
    if len(chosen) > 1:
        die("clean: --" + ", --".join(name for name, _ in chosen) +
            " select different things to delete; pass one at a time.")

    if not chosen:
        # Bare `clean` (failed runs) or a lone `--vacuum`.
        if vacuum:
            _clean_vacuum(conn, dry_run)
            return
        _clean_failed(conn, dry_run, assume_yes)
        return

    chosen[0][1]()
    if vacuum:
        _clean_vacuum(conn, dry_run)


def _clean_baselines(conn, dry_run, assume_yes):
    try:
        n = conn.execute("SELECT COUNT(*) FROM code_baselines").fetchone()[0]
    except Exception as e:
        print(f"[exptrack] warning: could not count code baselines: {e}", file=sys.stderr)
        n = 0
    if not n:
        print(dim("No code baselines stored.")); return
    print(f"Found {n} code baseline(s).")
    if dry_run:
        print(dim(f"Dry run: would clear {n} code baseline(s).")); return
    if confirm("Delete all code baselines? [y/N] ", assume_yes):
        conn.execute("DELETE FROM code_baselines")
        conn.commit()
        print(col(f"Cleared {n} code baseline(s).", G))


def _clean_failed(conn, dry_run, assume_yes):
    rows = conn.execute(
        "SELECT id, name FROM experiments WHERE status='failed' AND deleted_at IS NULL"
    ).fetchall()
    if not rows: print(dim("No failed experiments.")); return
    print(f"Found {len(rows)} failed:")
    for r in rows: print(f"  {r['id'][:6]}  {r['name']}")
    if dry_run:
        print(dim(f"Dry run: would delete {len(rows)} experiment(s).")); return
    if confirm("Delete all? [y/N] ", assume_yes):
        free_before = _free_bytes(conn)
        for r in rows:
            delete_experiment(conn, r["id"], reclaim_blobs=False)
        _sweep_blobs(conn)
        conn.commit()
        print(col(f"Cleaned {len(rows)} experiments (including output files).", G))
        _print_reclaimed(conn, free_before)


def _clean_reset(conn, dry_run: bool = False, assume_yes: bool = False):
    """Delete ALL experiments and data, VACUUM to shrink DB to minimum."""
    n_exp = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    n_params = conn.execute("SELECT COUNT(*) FROM params").fetchone()[0]
    n_metrics = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    n_artifacts = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    n_timeline = conn.execute("SELECT COUNT(*) FROM timeline").fetchone()[0]
    # Count every table --reset actually clears. Counting only the five
    # experiment tables meant a project whose runs were all deleted but whose
    # sessions/snapshots remained reported "Database is already empty" and
    # returned — re-introducing exactly the stranded-sessions state
    # _RESET_TABLES was written to prevent.
    other_counts = {}
    from ..core.db import _RESET_TABLES
    for table in _RESET_TABLES:
        # The four printed above are skipped here rather than filtered out of
        # the print loop below, so "which tables are reported separately" is
        # stated once.
        if table in ("params", "metrics", "artifacts", "timeline"):
            continue
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            continue
        if n:
            other_counts[table] = n

    # Count output files/dirs too
    n_output_items = 0
    try:
        root = cfg.project_root()
        conf = cfg.load()
        outputs_dir = root / conf.get("outputs_dir", "outputs")
        if outputs_dir.is_dir():
            n_output_items = sum(1 for _ in outputs_dir.iterdir())
    except Exception as e:
        print(f"[exptrack] warning: could not count output items: {e}",
              file=sys.stderr)

    total = (n_exp + n_params + n_metrics + n_artifacts + n_timeline
             + sum(other_counts.values()))
    if not total and not n_output_items:
        print(dim("Database is already empty.")); return

    print("This will delete ALL data:")
    print(f"  experiments: {n_exp}")
    print(f"  params:      {n_params}")
    print(f"  metrics:     {n_metrics}")
    print(f"  artifacts:   {n_artifacts}")
    print(f"  timeline:    {n_timeline}")
    for table, n in sorted(other_counts.items()):
        print(f"  {table + ':':<13}{n}")
    if n_output_items:
        print(f"  output dirs: {n_output_items}")

    if dry_run:
        print(dim(f"Dry run: would delete {total} row(s) + {n_output_items} output(s) and VACUUM.")); return

    if not confirm(col("Delete everything? This cannot be undone. [y/N] ", R), assume_yes):
        return

    # Delete experiment files first. No per-run blob reclaim — reset_all_tables
    # truncates both blob tables wholesale a moment later.
    rows = conn.execute("SELECT id FROM experiments").fetchall()
    for r in rows:
        delete_experiment(conn, r["id"], reclaim_blobs=False)

    # Clear remaining tables (one shared list, so this and the dashboard's
    # Reset button can't drift)
    from ..core.db import reset_all_tables
    reset_all_tables(conn)
    conn.commit()

    # Clean outputs directory and notebook_history
    try:
        root = cfg.project_root()
        conf = cfg.load()
        for dirname in (conf.get("outputs_dir", "outputs"),
                        conf.get("notebook_history_dir", ".exptrack/notebook_history")):
            target = root / dirname
            if target.is_dir():
                # OS Trash, not rmtree — a reset wipes the tracking data, but
                # the user's checkpoints stay recoverable.
                for child in sorted(target.iterdir()):
                    _trash_or_local(child, label="output")
    except Exception as e:
        print(f"[exptrack] warning: could not clean outputs directories: {e}",
              file=sys.stderr)

    # VACUUM to reclaim all space
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except Exception as e:
        # VACUUM fails if another process (e.g. dashboard) has the DB open
        print(dim(f"Note: could not VACUUM ({e}). "
                  "Close other connections and run `exptrack storage --checkpoint`."),
              file=sys.stderr)

    print(col("Database reset to empty state.", G))


def _clean_older_than(conn, age_str: str, all_statuses: bool,
                      dry_run: bool = False, assume_yes: bool = False):
    """Delete experiments older than the specified age (e.g. '30d')."""
    cutoff = datetime.now(timezone.utc) - parse_age_delta(age_str)

    status_filter = "" if all_statuses else "AND status='failed'"
    rows = conn.execute(f"""
        SELECT id, name, status, created_at FROM experiments
        WHERE created_at < ? AND deleted_at IS NULL {status_filter}
        ORDER BY created_at
    """, (cutoff.isoformat(),)).fetchall()

    if not rows:
        status_desc = "experiments" if all_statuses else "failed experiments"
        print(dim(f"No {status_desc} older than {age_str}.")); return

    print(f"Found {len(rows)} experiment(s) older than {age_str}:")
    for r in rows[:10]:
        print(f"  {r['id'][:6]}  {r['name'][:50]}  ({r['status']})")
    if len(rows) > 10:
        print(dim(f"  ... and {len(rows) - 10} more"))

    if dry_run:
        print(dim(f"Dry run: would delete {len(rows)} experiment(s).")); return
    if confirm(f"Delete {len(rows)} experiment(s)? [y/N] ", assume_yes):
        free_before = _free_bytes(conn)
        for r in rows:
            delete_experiment(conn, r["id"], reclaim_blobs=False)
        _sweep_blobs(conn)
        conn.commit()
        print(col(f"Cleaned {len(rows)} experiment(s).", G))
        _print_reclaimed(conn, free_before)


def _clean_vacuum(conn, dry_run: bool = False):
    """VACUUM the database — reclaim free pages, delete nothing.

    Space freed inside the file (a dropped index, a purged run) is reused as
    the database grows but is not returned to the filesystem until a VACUUM.
    The other paths here VACUUM only after deleting something, and `--reset`
    is destructive, so without this there was no way to shrink the file after
    e.g. the metrics session-node index became partial — only "delete
    everything".
    """
    p = cfg.project_root() / cfg.load().get("db", ".exptrack/experiments.db")
    before = p.stat().st_size if p.exists() else 0
    if dry_run:
        print(dim(f"Dry run: would VACUUM {fmt_bytes(before)} database at {p}."))
        return
    try:
        # Fold the WAL back into the main file first, or VACUUM can't shrink it.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        # …and again afterwards: in WAL mode the rebuilt pages land in the WAL,
        # so without this the main file is still its old size and this reports
        # "nothing to reclaim" for a VACUUM that did work.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        print(col(f"Could not VACUUM: {e}", Y), file=sys.stderr)
        print(dim("Another connection may have the database open — "
                  "stop the dashboard (exptrack ui) and retry."), file=sys.stderr)
        return
    after = p.stat().st_size if p.exists() else 0
    freed = before - after
    if freed > 0:
        print(col(f"Reclaimed {fmt_bytes(freed)} "
                  f"({fmt_bytes(before)} → {fmt_bytes(after)}).", G), file=sys.stderr)
    else:
        print(dim(f"Nothing to reclaim (database is {fmt_bytes(after)})."),
              file=sys.stderr)


def _clean_orphans(conn, dry_run: bool = False, assume_yes: bool = False):
    """Purge DB rows and files not linked to any existing experiment."""

    # Row counts come from the same specs the deletion uses (core.db), so the
    # preview, the --dry-run and the confirm can never describe a different set
    # of rows than the sweep removes.
    from ..core.db import count_orphans, sweep_orphans
    row_counts = count_orphans(conn)
    total = sum(row_counts.values())
    for table, n in row_counts.items():
        print(f"  {table}: {n} orphaned row(s)", file=sys.stderr)

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
                except Exception as e:
                    print(f"[exptrack] warning: could not read snapshot {fp}: {e}",
                          file=sys.stderr)
                    continue
            if n_snaps:
                print(f"  notebook_history: {n_snaps} orphaned snapshot(s)",
                      file=sys.stderr)
                total += n_snaps
    except Exception as e:
        print(f"[exptrack] warning: notebook_history scan failed: {e}",
              file=sys.stderr)

    # outputs: paths under outputs/ not linked to any existing experiment.
    # Shared with the dashboard's Clean button so the two never disagree about
    # what counts as an orphan.
    orphan_dirs = []
    try:
        from ..core.db import describe_orphan_output_paths
        # Annotated by the same helper the dashboard's confirm dialog uses, so
        # the two never report different sizes for the same path set.
        orphan_infos = describe_orphan_output_paths(conn)
        orphan_dirs = [Path(o["path"]) for o in orphan_infos]
        if orphan_infos:
            dir_size = sum(o["bytes"] for o in orphan_infos)
            print(f"  outputs: {len(orphan_infos)} orphaned path(s) "
                  f"({fmt_bytes(dir_size)})", file=sys.stderr)
            total += len(orphan_infos)
    except Exception as e:
        print(f"[exptrack] warning: outputs scan for orphans failed: {e}",
              file=sys.stderr)

    if not total:
        print(dim("No orphaned data found."), file=sys.stderr)
        return

    if dry_run:
        if orphan_dirs:
            for d in orphan_dirs:
                print(f"    {d.name}/", file=sys.stderr)
        print(dim(f"Dry run: would purge {total} orphaned item(s)."), file=sys.stderr)
        return

    if not confirm(f"Purge {total} orphaned item(s)? [y/N] ", assume_yes):
        return

    # One sweeper for every orphan-row table (including the refcounted blob
    # tables), driven by the same specs that produced the counts above.
    sweep_orphans(conn)
    if n_baselines:
        conn.execute("DELETE FROM code_baselines")
        conn.commit()

    # Files go to the OS Trash (local .exptrack/trash/ fallback), never
    # unlink/rmtree — an orphaned output dir is routinely model checkpoints,
    # and "orphaned" is a heuristic that also catches runs deleted with their
    # files deliberately kept.
    for fp in snap_files:
        _trash_or_local(fp, label="notebook snapshot")
    for d in orphan_dirs:
        _trash_or_local(d, label="orphaned output dir")
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
                        pass  # dir not empty — expected during partial cleanup
    except Exception as e:
        print(f"[exptrack] warning: notebook_history empty-dir sweep failed: {e}",
              file=sys.stderr)

    # VACUUM to reclaim space — checkpoint WAL first so VACUUM can shrink it
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except Exception:
        print(dim("Note: could not VACUUM (another connection may be open)."),
              file=sys.stderr)

    print(col(f"Purged {total} orphaned item(s).", G), file=sys.stderr)


def cmd_finish(args):
    """Manually mark a running experiment as done: exptrack finish <id>"""
    from ..core.queries import finish_experiment
    conn = get_db()
    result = finish_experiment(conn, args.id)
    if result.get("error"):
        die(f"Not found: {args.id}")
    if result.get("message") == "already done":
        print(dim(f"Experiment '{result['name']}' is already done."), file=sys.stderr); return
    conn.commit()

    duration = result["duration_s"]
    m, s = divmod(duration, 60)
    prev = result["prev_status"]
    print(col(f"Marked '{result['name']}' as done ({prev} -> done, {int(m)}m {s:.0f}s)", G))

    # Fire plugin hooks
    try:
        from .. import config as cfg
        from ..plugins import make_exp_proxy
        from ..plugins import registry as plugins
        plugins.load_from_config(cfg.load())
        proxy = make_exp_proxy(conn, result["id"], status="done",
                               duration_s=result["duration_s"])
        plugins.on_finish(proxy)
    except Exception as e:
        print(f"[exptrack] warning: plugin hooks failed: {e}", file=sys.stderr)


# ── Study commands ────────────────────────────────────────────────────────────

def cmd_study(args):
    """Add a run to a study: exptrack study <id> <study>"""
    from ..core.queries import add_to_study
    conn = get_db()
    studies = add_to_study(conn, args.id, args.study)
    if studies is None:
        die(f"Not found: {args.id}")
    conn.commit()
    print(col(f"Added to study '{args.study}'", G))


def cmd_unstudy(args):
    """Remove a run from a study: exptrack unstudy <id> <study>"""
    from ..core.queries import remove_from_study
    conn = get_db()
    studies = remove_from_study(conn, args.id, args.study)
    if studies is None:
        die(f"Not found: {args.id}")
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
        print(dim(f"Study '{args.name}' not found."), file=sys.stderr); return
    count = match[0]["count"]
    if not confirm(f"Remove study '{args.name}' from {count} experiment(s)? [y/N] ",
                   getattr(args, "yes", False)):
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
        die(f"Not found: {args.id}")
    update_experiment_stage(conn, exp["id"], args.number, args.name)
    conn.commit()
    label = f" ({args.name})" if args.name else ""
    print(col(f"Set stage {args.number}{label} on {exp['id'][:12]}", G))
