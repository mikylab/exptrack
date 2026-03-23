"""
exptrack/cli/main.py — Entry point and argument parser

exptrack init [name]          init project (writes config + .gitignore)
exptrack run script.py [args] run a script with tracking
exptrack ls [-n N]            list experiments
exptrack show <id>            full details
exptrack diff <id>            print captured git diff
exptrack compare <id1> <id2>  side-by-side param+metric comparison
exptrack history <nb> [id]    show notebook cell history for an experiment
exptrack tag <id> <tag>       add tag
exptrack note <id> <text>     add note
exptrack rm <id>              delete experiment
exptrack clean                remove all failed runs
exptrack compact              strip git diffs to reclaim space (keeps results)
exptrack stale --hours N      mark killed runs as failed
exptrack upgrade              run schema migrations
exptrack ui                   launch web dashboard
"""
from __future__ import annotations

import argparse
import sys

from .admin_cmds import cmd_backup, cmd_compact, cmd_init, cmd_restore, cmd_run, cmd_stale, cmd_storage, cmd_ui, cmd_upgrade
from .inspect_cmds import (
    cmd_compare,
    cmd_diff,
    cmd_export,
    cmd_history,
    cmd_ls,
    cmd_show,
    cmd_timeline,
    cmd_verify,
    cmd_watch,
)
from .mutate_cmds import (
    cmd_clean,
    cmd_delete_study,
    cmd_delete_tag,
    cmd_edit_note,
    cmd_finish,
    cmd_note,
    cmd_rm,
    cmd_stage,
    cmd_studies,
    cmd_study,
    cmd_tag,
    cmd_unstudy,
    cmd_untag,
)
from .pipeline_cmds import (
    cmd_create,
    cmd_link_dir,
    cmd_log_artifact,
    cmd_log_metric,
    cmd_log_output,
    cmd_log_result,
    cmd_run_fail,
    cmd_run_finish,
    cmd_run_start,
)


def main():
    # run-start accepts arbitrary --key value user params — handle before argparse
    # consumes them as unknown flags.
    if len(sys.argv) > 1 and sys.argv[1] == "run-start":
        p_rs = argparse.ArgumentParser(prog="exptrack run-start")
        p_rs.add_argument("--name",       default="")
        p_rs.add_argument("--script",     default="")
        p_rs.add_argument("--tags",       nargs="*")
        p_rs.add_argument("--study",      default="")
        p_rs.add_argument("--stage",      type=int, default=None)
        p_rs.add_argument("--stage-name", default=None)
        p_rs.add_argument("--notes",      default="")
        known, unknown = p_rs.parse_known_args(sys.argv[2:])
        known.params = unknown
        try:
            cmd_run_start(known)
        finally:
            from ..core.db import close_db
            close_db()
        return

    p = argparse.ArgumentParser(
        prog="exptrack",
        description="Experiment tracker -- scripts, notebooks, and SLURM pipelines",
    )
    from importlib.metadata import version as _pkg_version
    try:
        _ver = _pkg_version("exptrack")
    except Exception:
        _ver = "unknown"
    p.add_argument("--version", "-V", action="version", version=f"exptrack {_ver}")
    p.add_argument("--no-color", action="store_true",
                    help="Disable colored output (also auto-detected for non-TTY)")
    sub = p.add_subparsers(dest="cmd")

    # ── Project setup ─────────────────────────────────────────────────────────
    p_init = sub.add_parser("init", help="Initialize exptrack in project directory")
    p_init.add_argument("name", nargs="?", default="")
    p_init.add_argument("--here", action="store_true",
                        help="Create .exptrack/ in the current directory instead of the git root")

    # ── Python script wrapping ────────────────────────────────────────────────
    p_run = sub.add_parser("run", help="Run a Python script with tracking")
    p_run.add_argument("script")
    p_run.add_argument("script_args", nargs=argparse.REMAINDER)

    # ── Shell / SLURM pipeline commands ──────────────────────────────────────
    p_rs = sub.add_parser(
        "run-start",
        help="Start experiment from shell. Use: eval $(exptrack run-start --lr 0.01)"
    )
    p_rs.add_argument("--name",   default="", help="Override run name")
    p_rs.add_argument("--script", default="", help="Script/pipeline name for naming")
    p_rs.add_argument("--tags",   nargs="*",  help="Tags")
    p_rs.add_argument("--study",  default="", help="Add to study (groups related pipeline steps)")
    p_rs.add_argument("--stage",  type=int, default=None, help="Stage number (e.g. 1, 2, 3)")
    p_rs.add_argument("--stage-name", default=None, help="Stage label (e.g. preprocess, train, eval)")
    p_rs.add_argument("--notes",  default="", help="Notes")
    p_rs.add_argument("params",   nargs=argparse.REMAINDER,
                      help="Params as --key value pairs, e.g. --lr 0.01 --epochs 50")

    p_rf = sub.add_parser("run-finish", help="Finish experiment from shell")
    p_rf.add_argument("id",        help="EXP_ID from run-start")
    p_rf.add_argument("--metrics", help="Path to JSON file with final metrics")
    p_rf.add_argument("--step",    type=int, default=None)
    p_rf.add_argument("--params",  nargs="*", metavar="KEY=VALUE",
                      help="Extra params to log e.g. best_epoch=42")

    p_rfail = sub.add_parser("run-fail", help="Mark experiment as failed")
    p_rfail.add_argument("id")
    p_rfail.add_argument("reason", nargs="?", default="")

    p_lm = sub.add_parser("log-metric", help="Log a metric from shell mid-pipeline")
    p_lm.add_argument("id",           help="EXP_ID")
    p_lm.add_argument("key",          nargs="?", help="Metric name")
    p_lm.add_argument("value",        nargs="?", type=float, help="Metric value")
    p_lm.add_argument("--step",       type=int, default=None)
    p_lm.add_argument("--file",       help="JSON file to bulk-import metrics from")

    p_la = sub.add_parser("log-artifact", help="Register an output file")
    p_la.add_argument("id")
    p_la.add_argument("path", nargs="?", default="-")
    p_la.add_argument("--label", default="")
    p_la.add_argument("--stdin", action="store_true",
                       help="Read content from stdin and save as artifact")

    p_lo = sub.add_parser("log-output",
        help="Capture piped stdout as a log file: cmd | exptrack log-output $EXP_ID")
    p_lo.add_argument("id", help="EXP_ID")
    p_lo.add_argument("--label", default="output",
                       help="Label for the log file (default: output)")
    p_lo.add_argument("--quiet", "-q", action="store_true",
                       help="Don't echo captured output to stderr")

    p_ld = sub.add_parser("link-dir",
        help="Link a log/tensorboard/checkpoint directory to an experiment")
    p_ld.add_argument("id", help="EXP_ID")
    p_ld.add_argument("path", help="Directory path to link")
    p_ld.add_argument("--label", default="",
                       help="Label for the linked directory")

    p_lr = sub.add_parser("log-result",
        help="Manually log a result (key=value pair) to an experiment")
    p_lr.add_argument("id", help="EXP_ID")
    p_lr.add_argument("key", nargs="?", help="Result name (e.g. accuracy)")
    p_lr.add_argument("value", nargs="?", help="Result value")
    p_lr.add_argument("--file", help="JSON file with results")
    p_lr.add_argument("--source", default="manual",
                       help="Source label (default: manual)")

    p_create = sub.add_parser("create",
        help="Create a manual experiment entry (for runs done outside exptrack)")
    p_create.add_argument("--name", required=True, help="Experiment name")
    p_create.add_argument("--params", default="",
                          help="JSON string of params, e.g. '{\"lr\": 0.01}'")
    p_create.add_argument("--metrics", default="",
                          help="JSON string of metrics, e.g. '{\"accuracy\": 0.95}'")
    p_create.add_argument("--tags", nargs="*", default=[],
                          help="Tags for the experiment")
    p_create.add_argument("--notes", default="", help="Notes text")
    p_create.add_argument("--script", default="", help="Script/notebook path")
    p_create.add_argument("--command", default="", help="Reproduce command")
    p_create.add_argument("--status", default="done",
                          choices=["done", "failed", "running"],
                          help="Experiment status (default: done)")
    p_create.add_argument("--date", default="",
                          help="Created date (ISO format, default: now)")

    p_stale = sub.add_parser("stale", help="Mark killed/timed-out runs as failed")
    p_stale.add_argument("--hours", type=float, default=24,
                         help="Mark as timed-out if running longer than this (default: 24)")

    # ── Schema management ────────────────────────────────────────────────────
    p_up = sub.add_parser("upgrade", help="Run schema migrations")
    p_up.add_argument("--reinstall", action="store_true",
                      help="Also pip install -e . after migration")

    # ── Inspection ────────────────────────────────────────────────────────────
    p_ls = sub.add_parser("ls", help="List experiments (default: most recent 20)")
    p_ls.add_argument("-n", type=int, default=20, help="Number of experiments to show")
    p_ls.add_argument("--tag", help="Filter by tag")
    p_ls.add_argument("--status", choices=["done", "failed", "running"],
                       help="Filter by status")
    p_ls.add_argument("--study", help="Filter by study")
    p_ls.add_argument("--json", action="store_true", dest="json_output",
                       help="Output as JSON (for scripting)")

    p_show = sub.add_parser("show", help="Show full experiment details")
    p_show.add_argument("id")
    p_show.add_argument("--timeline", "-t", action="store_true",
                        help="Show execution timeline")
    p_show.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")

    p_diff = sub.add_parser("diff", help="Print captured git diff for an experiment")
    p_diff.add_argument("id")

    p_cmp = sub.add_parser("compare",
        help="Compare two experiments, or compare within one experiment at two timeline points")
    p_cmp.add_argument("id1", help="First experiment ID (or sole ID for within-exp compare)")
    p_cmp.add_argument("id2", nargs="?", default="",
                       help="Second experiment ID (omit for within-exp compare)")
    p_cmp.add_argument("--seq1", type=int, default=None,
                       help="Timeline seq point 1 (within-experiment comparison)")
    p_cmp.add_argument("--seq2", type=int, default=None,
                       help="Timeline seq point 2 (within-experiment comparison)")

    p_tl = sub.add_parser("timeline", help="Show execution timeline for an experiment")
    p_tl.add_argument("id")
    p_tl.add_argument("--compact", "-c", action="store_true",
                      help="Compact output (no code previews)")
    p_tl.add_argument("--type", choices=["cell_exec", "var_set", "artifact",
                                          "metric", "observational"],
                      help="Filter by event type")

    p_hist = sub.add_parser("history", help="Show notebook cell snapshot history")
    p_hist.add_argument("notebook")
    p_hist.add_argument("id", nargs="?", default="")

    p_tag = sub.add_parser("tag", help="Add a tag to one or more experiments")
    p_tag.add_argument("id", nargs="+",
                        help="Experiment ID(s) followed by the tag name (last argument is the tag)")
    # The last element of 'id' list is the tag name — parsed in cmd_tag

    p_untag = sub.add_parser("untag", help="Remove a tag from one or more experiments")
    p_untag.add_argument("id", nargs="+",
                          help="Experiment ID(s) followed by the tag name (last argument is the tag)")

    p_deltag = sub.add_parser("delete-tag",
        help="Remove a tag from ALL experiments globally")
    p_deltag.add_argument("tag", help="Tag name to delete everywhere")
    p_deltag.add_argument("--yes", "-y", action="store_true",
                          help="Skip confirmation prompt")

    p_note = sub.add_parser("note", help="Append a note to an experiment")
    p_note.add_argument("id"); p_note.add_argument("text")

    p_edit_note = sub.add_parser("edit-note", help="Replace an experiment's notes")
    p_edit_note.add_argument("id"); p_edit_note.add_argument("text")

    p_study = sub.add_parser("study", help="Add a run to a study")
    p_study.add_argument("id"); p_study.add_argument("study")

    p_unstudy = sub.add_parser("unstudy", help="Remove a run from a study")
    p_unstudy.add_argument("id"); p_unstudy.add_argument("study")

    sub.add_parser("studies", help="List all studies")

    p_delstudy = sub.add_parser("delete-study",
        help="Remove a study from ALL runs globally")
    p_delstudy.add_argument("name", help="Study name to delete everywhere")
    p_delstudy.add_argument("--yes", "-y", action="store_true",
                             help="Skip confirmation prompt")

    p_stage = sub.add_parser("stage", help="Set stage number and optional label on a run")
    p_stage.add_argument("id")
    p_stage.add_argument("number", type=int, help="Stage number (e.g. 1, 2, 3)")
    p_stage.add_argument("--name", default=None, help="Stage label (e.g. preprocess, train, eval)")

    p_export = sub.add_parser("export", help="Export experiment data (JSON, markdown, or CSV)")
    p_export.add_argument("id", nargs="?", default=None)
    p_export.add_argument("--format", choices=["json", "markdown", "csv", "tsv"], default="json")
    p_export.add_argument("--all", action="store_true", dest="export_all",
                          help="Export all experiments (batch export)")

    p_rm = sub.add_parser("rm", help="Delete one or more experiments and their output files")
    p_rm.add_argument("id", nargs="+", help="Experiment ID(s) to delete")
    p_clean = sub.add_parser("clean", help="Remove failed or old experiments")
    p_clean.add_argument("--baselines", action="store_true",
                         help="Delete code baselines (next run re-records full code)")
    p_clean.add_argument("--older-than", dest="older_than", default=None,
                         help="Delete experiments older than N days (e.g. 30d, 7d)")
    p_clean.add_argument("--all-statuses", action="store_true",
                         help="Include done experiments (default: only failed)")
    p_clean.add_argument("--orphans", action="store_true",
                         help="Purge orphaned rows (params, metrics, timeline, "
                              "cell_lineage, code_baselines, notebook_history) "
                              "not linked to any existing experiment")
    p_clean.add_argument("--reset", action="store_true",
                         help="Delete ALL experiments and data, reset DB to empty state")
    p_clean.add_argument("--dry-run", action="store_true", dest="dry_run",
                         help="List what would be deleted without deleting")

    p_ui = sub.add_parser("ui", help="Launch the web dashboard")
    p_ui.add_argument("--port", type=int, default=7331)
    p_ui.add_argument("--host", type=str, default="127.0.0.1")
    p_ui.add_argument("--token", type=str, default=None,
                       help="Set a dashboard auth token (saved to .exptrack/config.json)")
    p_ui.add_argument("--clear-token", action="store_true",
                       help="Remove the saved dashboard auth token")

    p_storage = sub.add_parser("storage", help="Show data storage breakdown and tips")
    p_storage.add_argument("--checkpoint", action="store_true",
                           help="Force WAL checkpoint to reclaim space")

    p_backup = sub.add_parser("backup", help="Create a backup of the experiment database")
    p_backup.add_argument("path", nargs="?", default="",
                          help="Destination path (default: .exptrack/backups/<timestamp>.db)")
    p_backup.add_argument("--force", "-f", action="store_true",
                          help="Overwrite existing backup file")

    p_restore = sub.add_parser("restore", help="Restore the experiment database from a backup")
    p_restore.add_argument("path", help="Path to backup file")
    p_restore.add_argument("--yes", "-y", action="store_true",
                           help="Skip confirmation prompt")

    p_compact = sub.add_parser("compact",
        help="Strip git diffs and/or cell data to reclaim space (keeps all results)")
    p_compact.add_argument("ids", nargs="*", default=[],
                           help="Experiment ID(s) to compact (prefix match). "
                                "Default: all done experiments")
    p_compact.add_argument("--older-than", dest="older_than", default=None,
                           help="Only compact experiments older than N days (e.g. 7d)")
    p_compact.add_argument("--all", action="store_true",
                           help="Compact all experiments regardless of status")
    p_compact.add_argument("--dry-run", action="store_true", dest="dry_run",
                           help="Show what would be compacted without changing anything")
    p_compact.add_argument("--export", metavar="DIR",
                           help="Save diffs as markdown files to DIR before stripping "
                                "(useful for lab notebooks)")
    p_compact.add_argument("--cells", action="store_true",
                           help="NULL out cell_lineage.source (lineage graph preserved)")
    p_compact.add_argument("--timeline", action="store_true",
                           help="NULL out timeline.source_diff")
    p_compact.add_argument("--snapshots", action="store_true",
                           help="Delete notebook_history/ JSON snapshot files")
    p_compact.add_argument("--deep", action="store_true",
                           help="All of the above: git_diff + cells + timeline + snapshots")
    p_compact.add_argument("--dedup", action="store_true",
                           help="Deduplicate existing raw git diffs into shared storage")

    p_watch = sub.add_parser("watch", help="Watch a running experiment for live metric updates")
    p_watch.add_argument("id", help="Experiment ID (prefix match)")
    p_watch.add_argument("--interval", type=int, default=5,
                          help="Refresh interval in seconds (default: 5)")

    p_verify = sub.add_parser("verify", help="Verify artifact file integrity")
    p_verify.add_argument("id", nargs="?", default=None,
                          help="Experiment ID (prefix match), or omit for all")
    p_verify.add_argument("--backfill", action="store_true",
                          help="Compute hashes for legacy artifacts missing them")
    p_verify.add_argument("--dry-run", action="store_true", dest="dry_run",
                          help="List artifacts and their status without hashing")

    p_finish = sub.add_parser("finish", help="Manually mark a running experiment as done")
    p_finish.add_argument("id")

    args = p.parse_args()
    if not args.cmd:
        p.print_help(); return

    dispatch = {
        "init":         cmd_init,
        "run":          cmd_run,
        "run-start":    cmd_run_start,
        "run-finish":   cmd_run_finish,
        "run-fail":     cmd_run_fail,
        "log-metric":   cmd_log_metric,
        "log-artifact": cmd_log_artifact,
        "log-output":   cmd_log_output,
        "link-dir":     cmd_link_dir,
        "log-result":   cmd_log_result,
        "create":       cmd_create,
        "stale":        cmd_stale,
        "upgrade":      cmd_upgrade,
        "storage":      cmd_storage,
        "backup":       cmd_backup,
        "restore":      cmd_restore,
        "compact":      cmd_compact,
        "finish":       cmd_finish,
        "ls":           cmd_ls,
        "show":         cmd_show,
        "diff":         cmd_diff,
        "compare":      cmd_compare,
        "timeline":     cmd_timeline,
        "history":      cmd_history,
        "tag":          cmd_tag,
        "untag":        cmd_untag,
        "delete-tag":   cmd_delete_tag,
        "note":         cmd_note,
        "edit-note":    cmd_edit_note,
        "study":        cmd_study,
        "unstudy":      cmd_unstudy,
        "studies":      cmd_studies,
        "delete-study": cmd_delete_study,
        "stage":        cmd_stage,
        "export":       cmd_export,
        "watch":        cmd_watch,
        "verify":       cmd_verify,
        "rm":           cmd_rm,
        "clean":        cmd_clean,
        "ui":           cmd_ui,
    }
    try:
        dispatch[args.cmd](args)
    finally:
        # Checkpoint WAL and close the DB so the WAL file doesn't bloat
        from ..core.db import close_db
        close_db()


if __name__ == "__main__":
    main()
