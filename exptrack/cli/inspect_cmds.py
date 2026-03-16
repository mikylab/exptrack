"""
exptrack/cli/inspect_cmds.py — Read-only inspection commands

ls, show, timeline, diff, compare, history, export, verify
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from ..core import get_db
from .. import config as cfg
from .formatting import G, R, Y, C, M, W, DIM, col, dim, bold, fmt_dt, fmt_dur, STATUS_C, STATUS_I


def cmd_ls(args):
    from ..core.queries import list_experiments
    conn = get_db()
    experiments = list_experiments(conn, limit=args.n)

    if not experiments:
        print(dim("No experiments yet. Run one with:  exptrack run script.py")); return

    # Build dynamic metric columns from returned data
    metric_keys: list[str] = []
    for exp in experiments:
        for k in exp.get("metrics", {}):
            if k not in metric_keys:
                metric_keys.append(k)
    shown_m = metric_keys[:3]

    # Header
    cols =  [(6,"ID"),(30,"NAME"),(8,"STATUS"),(12,"STARTED"),(7,"TIME"),(10,"BRANCH")]
    cols += [(11, k.upper()[:10]) for k in shown_m]
    hdr = "  ".join(bold(col(h.ljust(w), W)) for w, h in cols)
    print(); print(hdr); print(dim("-" * 100))

    for exp in experiments:
        sc = STATUS_C.get(exp["status"], W)
        si = STATUS_I.get(exp["status"], "?")
        tags = exp.get("tags", [])
        m = exp.get("metrics", {})
        mvals = [f"{m[k]:.4g}" if k in m else dim("--") for k in shown_m]

        vals = [
            col(exp["id"][:6], C),
            exp["name"][:30],
            col(f"{si} {exp['status']}", sc),
            fmt_dt(exp["created_at"]),
            fmt_dur(exp["duration_s"]),
            dim(exp["git_branch"] or "--"),
        ] + mvals

        line = "  ".join(str(v).ljust(w) for v, (w, _) in zip(vals, cols))
        print(line)
        if tags:
            print("  " + dim("   tags: " + " ".join(f"#{t}" for t in tags)))
    print()


def cmd_show(args):
    from ..core.queries import get_experiment_detail
    conn = get_db()
    exp = get_experiment_detail(conn, args.id)
    if not exp:
        print(col(f"Not found: {args.id}", R)); return

    print()
    print(bold(col(f"  {STATUS_I.get(exp['status'],'')} {exp['name']}", W)))
    print(dim(f"  id={exp['id']}  project={exp.get('project') or '--'}  status={exp['status']}"))
    print()

    def sec(t): print(bold(col(f"  -- {t} ", C)) + dim("-"*32))

    sec("Info")
    studies = exp.get("studies", [])
    stage_str = "--"
    if exp.get("stage") is not None:
        stage_str = str(exp["stage"])
        if exp.get("stage_name"):
            stage_str += f" ({exp['stage_name']})"
    for k, v in [("Created", fmt_dt(exp["created_at"])),
                 ("Duration", fmt_dur(exp["duration_s"])),
                 ("Script", exp.get("script") or "--"),
                 ("Command", exp.get("command") or "--"),
                 ("Branch", exp.get("git_branch") or "--"),
                 ("Commit", exp.get("git_commit") or "--"),
                 ("Diff lines", str(exp.get("diff_lines", 0)) + " lines"),
                 ("Host", exp.get("hostname") or "--"),
                 ("Python", exp.get("python_ver") or "--"),
                 ("Output dir", exp.get("output_dir") or "--"),
                 ("Notes", exp.get("notes") or "--"),
                 ("Tags", ", ".join(exp.get("tags", [])) or "--"),
                 ("Studies", ", ".join(studies) or "--"),
                 ("Stage", stage_str)]:
        print(f"    {col(k+':', Y):<22} {v}")
    print()

    params = exp.get("params", {})
    if params:
        sec("Params")
        for k, v in params.items():
            if not k.startswith("_"):
                print(f"    {col(k, M):<30} {v}")
        print()

    metrics = exp.get("metrics", [])
    if metrics:
        sec("Metrics")
        print(f"    {'KEY':<24} {'LAST':>10} {'MIN':>10} {'MAX':>10} {'STEPS':>6}")
        print(dim("    " + "-"*62))
        for m in metrics:
            print(f"    {col(m['key'], G):<32} {m['last']:>10.4g}"
                  f" {m['min']:>10.4g} {m['max']:>10.4g} {m['n']:>6}")
        print()

    artifacts = exp.get("artifacts", [])
    if artifacts:
        sec("Outputs")
        for a in artifacts:
            exists = "[ok]" if Path(a["path"]).exists() else dim("[missing]")
            seq_info = ""
            if a.get("timeline_seq"):
                seq_info = dim(f"  @seq={a['timeline_seq']}")
            print(f"    {col(a['label'] or 'file', Y):<30} {a['path']}  {exists}{seq_info}")
        print()

    # Show timeline summary if --timeline flag
    if getattr(args, "timeline", False):
        _print_timeline(conn, exp["id"])


def cmd_timeline(args):
    """Show the execution timeline for an experiment."""
    conn = get_db()
    exp = conn.execute("SELECT id, name FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp:
        print(col(f"Not found: {args.id}", R)); return
    print()
    print(bold(f"  Timeline: {exp['name']}"))
    _print_timeline(conn, exp["id"], verbose=not args.compact,
                    event_filter=args.type)


def _print_timeline(conn, exp_id, verbose=True, event_filter=None):
    """Print the execution timeline for an experiment."""
    where = "WHERE exp_id=?"
    params = [exp_id]
    if event_filter:
        where += " AND event_type=?"
        params.append(event_filter)

    rows = conn.execute(
        f"SELECT * FROM timeline {where} ORDER BY seq", params
    ).fetchall()

    if not rows:
        print(dim("  No timeline events recorded.")); return

    print(dim("  " + "-"*76))

    ICONS = {
        "cell_exec": col(">>", C),
        "var_set": col("=", M),
        "artifact": col("[]", G),
        "metric": col("#", Y),
        "observational": dim(".."),
    }

    # Track variable state as we walk the timeline
    var_state = {}

    for r in rows:
        seq = r["seq"]
        etype = r["event_type"]
        icon = ICONS.get(etype, " ")
        ts = fmt_dt(r["ts"])
        key = r["key"] or ""
        val_raw = r["value"]

        if etype == "cell_exec":
            try:
                info = json.loads(val_raw) if val_raw else {}
            except Exception:
                info = {}
            preview = info.get("source_preview", "")[:60]
            flags = []
            if info.get("code_is_new"): flags.append(col("NEW", G))
            if info.get("code_changed"): flags.append(col("EDITED", Y))
            if info.get("is_rerun"): flags.append(dim("rerun"))
            flag_str = " ".join(flags)
            print(f"\n  {icon} seq={seq:<4} {ts}  {col(key, C)}  {flag_str}")
            if verbose and preview:
                first_line = preview.splitlines()[0][:70] if preview else ""
                print(dim(f"             {first_line}"))
            if verbose and r["source_diff"]:
                try:
                    diff_data = json.loads(r["source_diff"])
                    for entry in diff_data[:10]:
                        op = entry.get("op", "=")
                        line = entry.get("line", "")
                        if op == "+":
                            print(col(f"             + {line[:70]}", G))
                        elif op == "-":
                            print(col(f"             - {line[:70]}", R))
                except (json.JSONDecodeError, TypeError):
                    pass

        elif etype == "observational":
            try:
                info = json.loads(val_raw) if val_raw else {}
            except Exception:
                info = {}
            preview = info.get("source_preview", "")[:60]
            first_line = preview.splitlines()[0][:70] if preview else ""
            print(dim(f"  {icon} seq={seq:<4} {ts}  {first_line}"))

        elif etype == "var_set":
            try:
                val = json.loads(val_raw) if val_raw else ""
            except Exception:
                val = val_raw
            prev_raw = r["prev_value"]
            var_state[key] = val

            val_str = str(val)[:50]
            if prev_raw:
                try:
                    prev = json.loads(prev_raw)
                except Exception:
                    prev = prev_raw
                print(f"  {icon} seq={seq:<4} {ts}  {col(key, M)} = {val_str}  {dim(f'(was: {str(prev)[:30]})')}")
            else:
                print(f"  {icon} seq={seq:<4} {ts}  {col(key, M)} = {val_str}")

        elif etype == "artifact":
            try:
                val = json.loads(val_raw) if val_raw else ""
            except Exception:
                val = val_raw
            print(f"  {icon} seq={seq:<4} {ts}  {col('artifact:', G)} {key}  -> {str(val)[:50]}")
            if verbose:
                ctx_vars = {k: v for k, v in var_state.items()
                            if not str(v).startswith("(") and k[0] != "_"}
                if ctx_vars:
                    ctx_str = ", ".join(f"{k}={str(v)[:15]}" for k, v in
                                        list(ctx_vars.items())[:6])
                    print(dim(f"             context: {ctx_str}"))

        elif etype == "metric":
            try:
                val = json.loads(val_raw) if val_raw else ""
            except Exception:
                val = val_raw
            print(f"  {icon} seq={seq:<4} {ts}  {col(key, Y)} = {val}")

    print()
    print(dim(f"  {len(rows)} events total"))
    print()


def cmd_diff(args):
    conn = get_db()
    exp = conn.execute("SELECT name, git_diff, git_commit, git_branch FROM experiments"
                       " WHERE id LIKE ?", (args.id + "%",)).fetchone()
    if not exp:
        print(col(f"Not found: {args.id}", R)); return
    diff = exp["git_diff"]
    if not diff:
        print(dim("No uncommitted diff was captured for this run.")); return
    print(bold(f"\n  Diff: {exp['name']}  [{exp['git_branch']}@{exp['git_commit']}]\n"))
    for line in diff.splitlines():
        if   line.startswith("+") and not line.startswith("+++"): print(col(line, G))
        elif line.startswith("-") and not line.startswith("---"): print(col(line, R))
        elif line.startswith("@@"):                               print(col(line, C))
        elif line.startswith(("diff ", "index ")):               print(dim(line))
        else:                                                      print(line)
    print()


def cmd_compare(args):
    from ..core.queries import get_experiment_detail, get_latest_metrics, get_vars_at_seq
    conn = get_db()

    seq1 = getattr(args, "seq1", None)
    seq2 = getattr(args, "seq2", None)

    if seq1 is not None and seq2 is not None:
        _compare_within(conn, args.id1, int(seq1), int(seq2))
        return

    e1 = get_experiment_detail(conn, args.id1)
    e2 = get_experiment_detail(conn, args.id2)
    if not e1: print(col(f"Not found: {args.id1}", R)); return
    if not e2: print(col(f"Not found: {args.id2}", R)); return

    p1, p2 = e1["params"], e2["params"]
    m1 = get_latest_metrics(conn, e1["id"])
    m2 = get_latest_metrics(conn, e2["id"])

    print()
    print(f"  {'':26} {bold(col(e1['name'][:26], C)):<36} {bold(col(e2['name'][:26], M))}")
    print(dim("  " + "-" * 82))

    if p1 or p2:
        print(bold(col("  Params", Y)))
        for k in sorted(set(p1) | set(p2)):
            if k.startswith("_"):
                continue
            v1 = str(p1.get(k, dim("--")))
            v2 = str(p2.get(k, dim("--")))
            marker = col("  < differs", Y) if p1.get(k) != p2.get(k) else ""
            print(f"  {k:<26} {v1:<30} {v2:<30}{marker}")
        print()

    v1 = get_vars_at_seq(conn, e1["id"])
    v2 = get_vars_at_seq(conn, e2["id"])
    if v1 or v2:
        print(bold(col("  Variables (final state)", M)))
        for k in sorted(set(v1) | set(v2)):
            sv1 = str(v1.get(k, dim("--")))[:30]
            sv2 = str(v2.get(k, dim("--")))[:30]
            marker = col("  < differs", Y) if v1.get(k) != v2.get(k) else ""
            print(f"  {k:<26} {sv1:<30} {sv2:<30}{marker}")
        print()

    if m1 or m2:
        print(bold(col("  Metrics (last)", G)))
        for k in sorted(set(m1) | set(m2)):
            sv1 = f"{m1[k]:.4g}" if k in m1 else dim("--")
            sv2 = f"{m2[k]:.4g}" if k in m2 else dim("--")
            marker = ""
            if k in m1 and k in m2:
                d = m1[k] - m2[k]
                marker = col(f"  {'>' if d>0 else '<'}{abs(d):.3g}", G if d < 0 else R)
            print(f"  {k:<26} {sv1:<30} {sv2:<30}{marker}")
        print()


def _compare_within(conn, exp_id_prefix, seq1, seq2):
    """Compare variable state, metrics, and artifacts at two timeline points."""
    from ..core.queries import find_experiment, get_vars_at_seq, get_timeline_events
    exp = find_experiment(conn, exp_id_prefix, "id, name")
    if not exp:
        print(col(f"Not found: {exp_id_prefix}", R)); return

    eid = exp["id"]
    lo, hi = min(seq1, seq2), max(seq1, seq2)
    v1 = get_vars_at_seq(conn, eid, seq=lo)
    v2 = get_vars_at_seq(conn, eid, seq=hi)

    print()
    print(bold(f"  Within-experiment comparison: {exp['name']}"))
    print(f"  {'':26} {bold(col(f'Point A (#' + str(lo) + ')', C)):<36} {bold(col(f'Point B (#' + str(hi) + ')', M))}")
    print(dim("  " + "-" * 82))

    for s, label in [(lo, C), (hi, M)]:
        row = conn.execute(
            "SELECT event_type, key, value FROM timeline WHERE exp_id=? AND seq=?",
            (eid, s)).fetchone()
        if row:
            try:
                info = json.loads(row["value"]) if row["value"] else {}
            except (json.JSONDecodeError, TypeError):
                info = {}
            if isinstance(info, dict):
                preview = info.get("source_preview", row["key"] or "")[:50]
            else:
                preview = str(info)[:50]
            print(f"  {col(f'#{s}', label)}: {row['event_type']} - {preview}")
    print()

    # Variables comparison
    all_keys = sorted(set(v1) | set(v2))
    changed_count = sum(1 for k in all_keys if v1.get(k) != v2.get(k))
    if all_keys:
        print(bold(col(f"  Variables", M)) + dim(f"  ({changed_count} changed / {len(all_keys)} total)"))
        for k in all_keys:
            sv1 = str(v1.get(k, dim("--")))[:30]
            sv2 = str(v2.get(k, dim("--")))[:30]
            if v1.get(k) != v2.get(k):
                # Show delta for numeric values
                delta = ""
                try:
                    n1, n2 = float(v1[k]), float(v2[k])
                    d = n2 - n1
                    delta = col(f"  {'+'if d>0 else ''}{d:.4g}", G if d < 0 else R)
                except (ValueError, TypeError, KeyError):
                    delta = col("  < changed", Y)
                print(f"  {col(k, Y):<34} {sv1:<30} {sv2:<30}{delta}")
            else:
                print(dim(f"  {k:<26} {sv1:<30} {sv2:<30}"))
        print()
    else:
        print(dim("  No variable state recorded at these points."))
        print()

    # Metrics between the two points
    events = get_timeline_events(conn, eid)
    metric_events = [e for e in events if e["event_type"] == "metric" and lo <= e["seq"] <= hi]
    if metric_events:
        print(bold(col(f"  Metrics between #{lo} and #{hi}", G)) + dim(f"  ({len(metric_events)} logged)"))
        for me in metric_events:
            val = me["value"]
            val_str = f"{val:.4g}" if isinstance(val, (int, float)) else str(val)[:30]
            print(f"  {me['key']:<26} {val_str:<30} " + dim(f"@#{me['seq']}"))
        print()

    # Artifacts between the two points
    artifact_events = [e for e in events if e["event_type"] == "artifact" and lo <= e["seq"] <= hi]
    if artifact_events:
        print(bold(col(f"  Artifacts between #{lo} and #{hi}", C)) + dim(f"  ({len(artifact_events)})"))
        for ae in artifact_events:
            print(f"  {ae['key']:<26} " + dim(f"@#{ae['seq']}"))
        print()


def cmd_history(args):
    """Show notebook cell snapshot history for an experiment."""
    root = cfg.project_root()
    conf = cfg.load()
    hist_root = root / conf.get("notebook_history_dir", ".exptrack/notebook_history")

    nb = args.notebook
    exp_id = args.id or ""

    nb_dir = hist_root / nb
    if not nb_dir.exists():
        print(col(f"No history found for notebook '{nb}'", R))
        print(dim(f"  Expected: {nb_dir}"))
        return

    files = sorted(nb_dir.glob("*.json"))
    if exp_id:
        files = [f for f in files if _snap_exp_id(f).startswith(exp_id)]

    if not files:
        print(dim("No snapshots found.")); return

    print()
    print(bold(f"  Notebook history: {nb}") + (f"  (exp {exp_id[:6]})" if exp_id else ""))
    print(dim("  " + "-"*70))

    for f in files:
        try:
            snap = json.loads(f.read_text())
        except Exception as e:
            print(f"[exptrack] warning: could not read snapshot {f}: {e}", file=sys.stderr)
            continue

        changed = bool(snap.get("source_diff")) or bool(snap.get("changed_vars"))
        icon = "*" if changed else "."
        ts   = fmt_dt(snap.get("ts", ""))
        ex   = snap.get("exec_num", "?")

        print(f"\n  {icon} exec #{ex:<4} {ts}  exp={snap.get('exp_id','?')[:6]}")

        cv = snap.get("changed_vars", {})
        nv = snap.get("new_vars", {})
        if nv:
            print(col("    New vars:", G))
            for k, v in list(nv.items())[:8]:
                print(f"      {k} = {v}")
        if cv:
            print(col("    Changed vars:", Y))
            for k, d in list(cv.items())[:8]:
                print(f"      {k}: {d.get('from')} -> {d.get('to')}")

        diff = snap.get("source_diff")
        if diff:
            print(col("    Cell diff:", C))
            for entry in diff[:20]:
                op, line = entry.get("op","="), entry.get("line","")
                if op == "+": print(col(f"      + {line}", G))
                elif op == "-": print(col(f"      - {line}", R))

        out = snap.get("output")
        if out and out.strip():
            lines = out.strip().splitlines()[:4]
            print(dim(f"    Output: {' | '.join(lines)[:120]}"))

    print()


def _snap_exp_id(f: Path) -> str:
    try:
        return json.loads(f.read_text()).get("exp_id", "")
    except Exception as e:
        print(f"[exptrack] warning: could not read snapshot {f}: {e}", file=sys.stderr)
        return ""


def cmd_export(args):
    """Export experiment data: exptrack export <id> [--format json|markdown|csv|tsv]"""
    from ..core.queries import (get_export_data, get_batch_export_data,
                                format_export_markdown, format_export_csv)
    conn = get_db()
    fmt = getattr(args, "format", "json")
    export_all = getattr(args, "export_all", False)

    if export_all or (fmt in ("csv", "tsv") and not args.id):
        _export_batch(conn, fmt, export_all, getattr(args, "id", None))
        return

    if not args.id:
        print(col("Error: experiment ID required (or use --all for batch export)", R))
        return

    data = get_export_data(conn, args.id)
    if not data:
        print(col(f"Not found: {args.id}", R)); return

    if fmt == "markdown":
        print(format_export_markdown(data))
    elif fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        print(format_export_csv([data], delimiter=delimiter), end="")
    else:
        print(json.dumps(data, indent=2, default=str))


def _export_batch(conn, fmt, export_all, exp_id_prefix):
    """Export one or all experiments in CSV/TSV/JSON/markdown batch format."""
    from ..core.queries import (get_batch_export_data, format_export_csv,
                                format_export_markdown)

    exp_ids = None
    if not export_all and exp_id_prefix:
        rows = conn.execute(
            "SELECT id FROM experiments WHERE id LIKE ? ORDER BY created_at DESC",
            (exp_id_prefix + "%",)
        ).fetchall()
        exp_ids = [r["id"] for r in rows]
    elif not export_all:
        print(col("Error: provide experiment ID or use --all", R), file=sys.stderr)
        return

    batch = get_batch_export_data(conn, exp_ids=exp_ids, export_all=export_all)
    if not batch:
        print(dim("No experiments found.")); return

    if fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        print(format_export_csv(batch, delimiter=delimiter), end="")
    elif fmt == "markdown":
        for i, data in enumerate(batch):
            if i > 0:
                print("\n---\n")
            print(format_export_markdown(data))
    else:
        print(json.dumps(batch, indent=2, default=str))


def cmd_verify(args):
    """Verify artifact file integrity against stored content hashes.

    Reports each artifact as: ok, missing, modified, or no-hash (legacy).
    With --backfill, computes hashes for legacy artifacts whose files exist.
    With --dry-run, lists artifacts and their status without computing hashes.
    """
    conn = get_db()

    where = ""
    params_q: list = []
    if getattr(args, "id", None):
        where = "AND a.exp_id LIKE ?"
        params_q.append(args.id + "%")

    rows = conn.execute(f"""
        SELECT a.id, a.exp_id, a.label, a.path, a.content_hash, a.size_bytes,
               e.name
        FROM artifacts a
        JOIN experiments e ON a.exp_id = e.id
        WHERE a.path IS NOT NULL {where}
        ORDER BY e.created_at DESC, a.id
    """, params_q).fetchall()

    if not rows:
        print(dim("No artifacts found.")); return

    dry_run = getattr(args, "dry_run", False)
    backfill = getattr(args, "backfill", False)

    if dry_run:
        _verify_dry_run(rows)
        return

    from ..core.hashing import file_hash
    from .. import config as _cfg
    conf = _cfg.load()
    max_bytes = int(conf.get("hash_max_mb", 500)) * 1024 * 1024

    counts = {"ok": 0, "missing": 0, "modified": 0, "no-hash": 0, "backfilled": 0}

    print()
    print(bold("  Artifact Integrity Report"))
    print(dim("  " + "-" * 60))

    cur_exp = None
    for r in rows:
        if r["name"] != cur_exp:
            cur_exp = r["name"]
            print(f"\n  {bold(cur_exp)}")

        p = Path(r["path"])
        label = r["label"] or p.name

        if not p.exists():
            status_str = col("[missing]", R)
            counts["missing"] += 1
        elif not r["content_hash"]:
            if backfill:
                try:
                    h, sz = file_hash(p, max_bytes=max_bytes)
                    conn.execute(
                        "UPDATE artifacts SET content_hash=?, size_bytes=? WHERE id=?",
                        (h, sz, r["id"])
                    )
                    status_str = col("[backfilled]", C)
                    counts["backfilled"] += 1
                except Exception as e:
                    print(f"[exptrack] warning: could not hash {p}: {e}", file=sys.stderr)
                    status_str = dim("[no-hash]")
                    counts["no-hash"] += 1
            else:
                status_str = dim("[no-hash]")
                counts["no-hash"] += 1
        else:
            try:
                h, sz = file_hash(p, max_bytes=max_bytes)
                if h == r["content_hash"]:
                    status_str = col("[ok]", G)
                    counts["ok"] += 1
                else:
                    status_str = col("[modified]", Y)
                    counts["modified"] += 1
            except Exception as e:
                print(f"[exptrack] warning: could not verify {p}: {e}", file=sys.stderr)
                status_str = col("[error]", R)
                counts["missing"] += 1

        print(f"    {label:<30} {status_str}")

    if backfill:
        conn.commit()

    print()
    print(dim("  Summary: ") +
          col(f"{counts['ok']} ok", G) + "  " +
          col(f"{counts['missing']} missing", R) + "  " +
          col(f"{counts['modified']} modified", Y) + "  " +
          dim(f"{counts['no-hash']} no-hash") +
          (f"  {col(str(counts['backfilled']) + ' backfilled', C)}" if backfill else ""))
    print()


def _verify_dry_run(rows):
    """List artifacts with their status, without computing any hashes."""
    counts = {"exists": 0, "missing": 0, "has-hash": 0, "no-hash": 0}

    print()
    print(bold("  Artifact Inventory (dry run — no hashing)"))
    print(dim("  " + "-" * 60))

    cur_exp = None
    for r in rows:
        if r["name"] != cur_exp:
            cur_exp = r["name"]
            print(f"\n  {bold(cur_exp)}")

        p = Path(r["path"])
        label = r["label"] or p.name
        exists = p.exists()
        has_hash = bool(r["content_hash"])

        if exists:
            counts["exists"] += 1
        else:
            counts["missing"] += 1
        if has_hash:
            counts["has-hash"] += 1
        else:
            counts["no-hash"] += 1

        file_status = col("[exists]", G) if exists else col("[missing]", R)
        hash_status = dim("hash:yes") if has_hash else dim("hash:no")
        size_str = ""
        if r["size_bytes"]:
            sz = r["size_bytes"]
            if sz < 1024:
                size_str = f" ({sz}B)"
            elif sz < 1024**2:
                size_str = f" ({sz/1024:.1f}KB)"
            else:
                size_str = f" ({sz/1024**2:.1f}MB)"

        print(f"    {label:<30} {file_status} {hash_status}{size_str}")

    print()
    print(dim("  Summary: ") +
          col(f"{counts['exists']} exist", G) + "  " +
          col(f"{counts['missing']} missing", R) + "  " +
          dim(f"{counts['has-hash']} with hash") + "  " +
          dim(f"{counts['no-hash']} without hash"))
    print()
