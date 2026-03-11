"""
exptrack/cli/inspect_cmds.py — Read-only inspection commands

ls, show, timeline, diff, compare, history, export
"""
from __future__ import annotations
import json
from pathlib import Path

from ..core import get_db
from .. import config as cfg
from .formatting import G, R, Y, C, M, W, DIM, col, dim, bold, fmt_dt, fmt_dur, STATUS_C, STATUS_I


def cmd_ls(args):
    conn = get_db()
    rows = conn.execute("""
        SELECT id, project, name, status, created_at, duration_s, git_branch, tags
        FROM experiments ORDER BY created_at DESC LIMIT ?
    """, (args.n,)).fetchall()

    if not rows:
        print(dim("No experiments yet. Run one with:  exptrack run script.py")); return

    # Gather last metrics to build dynamic columns
    all_m = conn.execute("""
        SELECT exp_id, key, value FROM metrics m
        WHERE step=(SELECT MAX(step) FROM metrics m2
                    WHERE m2.exp_id=m.exp_id AND m2.key=m.key)
        GROUP BY exp_id, key
    """).fetchall()
    metrics_by_exp: dict[str, dict] = {}
    metric_keys: list[str] = []
    for r in all_m:
        metrics_by_exp.setdefault(r["exp_id"], {})[r["key"]] = r["value"]
        if r["key"] not in metric_keys:
            metric_keys.append(r["key"])
    shown_m = metric_keys[:3]

    # Header
    cols =  [(6,"ID"),(30,"NAME"),(8,"STATUS"),(12,"STARTED"),(7,"TIME"),(10,"BRANCH")]
    cols += [(11, k.upper()[:10]) for k in shown_m]
    hdr = "  ".join(bold(col(h.ljust(w), W)) for w, h in cols)
    print(); print(hdr); print(dim("-" * 100))

    for r in rows:
        sc = STATUS_C.get(r["status"], W)
        si = STATUS_I.get(r["status"], "?")
        tags = json.loads(r["tags"] or "[]")
        m = metrics_by_exp.get(r["id"], {})
        mvals = [f"{m[k]:.4g}" if k in m else dim("--") for k in shown_m]

        vals = [
            col(r["id"][:6], C),
            r["name"][:30],
            col(f"{si} {r['status']}", sc),
            fmt_dt(r["created_at"]),
            fmt_dur(r["duration_s"]),
            dim(r["git_branch"] or "--"),
        ] + mvals

        line = "  ".join(str(v).ljust(w) for v, (w, _) in zip(vals, cols))
        print(line)
        if tags:
            print("  " + dim("   tags: " + " ".join(f"#{t}" for t in tags)))
    print()


def cmd_show(args):
    conn = get_db()
    exp = conn.execute("SELECT * FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp:
        print(col(f"Not found: {args.id}", R)); return

    print()
    print(bold(col(f"  {STATUS_I.get(exp['status'],'')} {exp['name']}", W)))
    print(dim(f"  id={exp['id']}  project={exp['project'] or '--'}  status={exp['status']}"))
    print()

    def sec(t): print(bold(col(f"  -- {t} ", C)) + dim("-"*32))

    sec("Info")
    for k, v in [("Created", fmt_dt(exp["created_at"])),
                 ("Duration", fmt_dur(exp["duration_s"])),
                 ("Script", exp["script"] or "--"),
                 ("Command", exp["command"] or "--"),
                 ("Branch", exp["git_branch"] or "--"),
                 ("Commit", exp["git_commit"] or "--"),
                 ("Diff lines", str(len((exp["git_diff"] or "").splitlines())) + " lines"),
                 ("Host", exp["hostname"] or "--"),
                 ("Python", exp["python_ver"] or "--"),
                 ("Notes", exp["notes"] or "--"),
                 ("Tags", ", ".join(json.loads(exp["tags"] or "[]")) or "--")]:
        print(f"    {col(k+':', Y):<22} {v}")
    print()

    params = conn.execute("SELECT key, value FROM params WHERE exp_id=? ORDER BY key",
                          (exp["id"],)).fetchall()
    if params:
        sec("Params")
        for p in params:
            if not p["key"].startswith("_"):
                print(f"    {col(p['key'], M):<30} {json.loads(p['value'])}")
        print()

    metrics = conn.execute("""
        SELECT key,
               (SELECT value FROM metrics m2 WHERE m2.exp_id=metrics.exp_id
                AND m2.key=metrics.key ORDER BY COALESCE(step,0) DESC LIMIT 1) as last_v,
               MIN(value) as min_v, MAX(value) as max_v, COUNT(*) as n
        FROM metrics WHERE exp_id=? GROUP BY key ORDER BY key
    """, (exp["id"],)).fetchall()
    if metrics:
        sec("Metrics")
        print(f"    {'KEY':<24} {'LAST':>10} {'MIN':>10} {'MAX':>10} {'STEPS':>6}")
        print(dim("    " + "-"*62))
        for m in metrics:
            print(f"    {col(m['key'], G):<32} {m['last_v']:>10.4g}"
                  f" {m['min_v']:>10.4g} {m['max_v']:>10.4g} {m['n']:>6}")
        print()

    arts = conn.execute("SELECT label, path, timeline_seq FROM artifacts WHERE exp_id=?",
                        (exp["id"],)).fetchall()
    if arts:
        sec("Outputs")
        for a in arts:
            exists = "[ok]" if Path(a["path"]).exists() else dim("[missing]")
            seq_info = ""
            if a["timeline_seq"]:
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
    conn = get_db()

    seq1 = getattr(args, "seq1", None)
    seq2 = getattr(args, "seq2", None)

    if seq1 is not None and seq2 is not None:
        _compare_within(conn, args.id1, int(seq1), int(seq2))
        return

    exps = []
    for eid in [args.id1, args.id2]:
        e = conn.execute("SELECT * FROM experiments WHERE id LIKE ?",
                         (eid + "%",)).fetchone()
        if not e: print(col(f"Not found: {eid}", R)); return
        exps.append(e)
    e1, e2 = exps

    def get_params(eid):
        rows = conn.execute("SELECT key, value FROM params WHERE exp_id=?", (eid,)).fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def get_metrics(eid):
        rows = conn.execute("""
            SELECT key, value FROM metrics m WHERE exp_id=?
            GROUP BY key HAVING MAX(COALESCE(step, 0))
        """, (eid,)).fetchall()
        return {r["key"]: r["value"] for r in rows}

    p1, p2 = get_params(e1["id"]), get_params(e2["id"])
    m1, m2 = get_metrics(e1["id"]), get_metrics(e2["id"])

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

    def get_final_vars(eid):
        rows = conn.execute("""
            SELECT key, value FROM timeline
            WHERE exp_id=? AND event_type='var_set'
            ORDER BY seq DESC
        """, (eid,)).fetchall()
        ctx = {}
        for r in rows:
            if r["key"] not in ctx:
                try:
                    ctx[r["key"]] = json.loads(r["value"]) if r["value"] else None
                except Exception:
                    ctx[r["key"]] = r["value"]
        return ctx

    v1, v2 = get_final_vars(e1["id"]), get_final_vars(e2["id"])
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
    """Compare variable state at two timeline points within the same experiment."""
    exp = conn.execute("SELECT id, name FROM experiments WHERE id LIKE ?",
                       (exp_id_prefix + "%",)).fetchone()
    if not exp:
        print(col(f"Not found: {exp_id_prefix}", R)); return

    eid = exp["id"]

    def vars_at_seq(s):
        rows = conn.execute("""
            SELECT key, value FROM timeline
            WHERE exp_id=? AND event_type='var_set' AND seq <= ?
            ORDER BY seq DESC
        """, (eid, s)).fetchall()
        ctx = {}
        for r in rows:
            if r["key"] not in ctx:
                try:
                    ctx[r["key"]] = json.loads(r["value"]) if r["value"] else None
                except Exception:
                    ctx[r["key"]] = r["value"]
        return ctx

    v1, v2 = vars_at_seq(seq1), vars_at_seq(seq2)

    print()
    print(bold(f"  Within-experiment comparison: {exp['name']}"))
    print(f"  {'':26} {bold(col(f'@seq={seq1}', C)):<36} {bold(col(f'@seq={seq2}', M))}")
    print(dim("  " + "-" * 82))

    for s, label in [(seq1, C), (seq2, M)]:
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
            print(f"  {col(f'@seq={s}', label)}: {row['event_type']} - {preview}")
    print()

    all_keys = sorted(set(v1) | set(v2))
    if all_keys:
        print(bold(col("  Variables", M)))
        for k in all_keys:
            sv1 = str(v1.get(k, dim("--")))[:30]
            sv2 = str(v2.get(k, dim("--")))[:30]
            marker = col("  < changed", Y) if v1.get(k) != v2.get(k) else ""
            if v1.get(k) != v2.get(k):
                print(f"  {col(k, Y):<34} {sv1:<30} {sv2:<30}{marker}")
            else:
                print(dim(f"  {k:<26} {sv1:<30} {sv2:<30}"))
    else:
        print(dim("  No variable state recorded at these points."))
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
        except Exception:
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
    except Exception:
        return ""


def cmd_export(args):
    """Export experiment data: exptrack export <id> [--format json|markdown]"""
    conn = get_db()
    exp = conn.execute("SELECT * FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp: print(col(f"Not found: {args.id}", R)); return

    eid = exp["id"]
    params = {r["key"]: json.loads(r["value"]) for r in
              conn.execute("SELECT key, value FROM params WHERE exp_id=?", (eid,)).fetchall()}
    metrics = [dict(r) for r in
               conn.execute("SELECT key, value, step, ts FROM metrics WHERE exp_id=? ORDER BY ts",
                            (eid,)).fetchall()]
    artifacts = [dict(r) for r in
                 conn.execute("SELECT label, path, created_at FROM artifacts WHERE exp_id=?",
                              (eid,)).fetchall()]

    fmt = getattr(args, "format", "json")
    if fmt == "markdown":
        tags = json.loads(exp["tags"] or "[]")
        print(f"# {exp['name']}")
        print(f"\n**ID:** {eid}  ")
        print(f"**Status:** {exp['status']}  ")
        print(f"**Created:** {exp['created_at']}  ")
        if exp["duration_s"]:
            m, s = divmod(exp["duration_s"], 60)
            print(f"**Duration:** {int(m)}m {s:.0f}s  ")
        if exp["git_branch"]:
            print(f"**Git:** {exp['git_branch']} @ {exp['git_commit']}  ")
        if tags:
            print(f"**Tags:** {', '.join(tags)}  ")
        if exp["notes"]:
            print(f"\n## Notes\n{exp['notes']}")
        if params:
            print("\n## Parameters")
            for k, v in params.items():
                if not k.startswith("_"):
                    print(f"- **{k}:** {v}")
        if metrics:
            print("\n## Metrics")
            seen = {}
            for m_row in metrics:
                seen[m_row["key"]] = m_row["value"]
            for k, v in seen.items():
                print(f"- **{k}:** {v}")
        if artifacts:
            print("\n## Artifacts")
            for a in artifacts:
                print(f"- {a['label']}: `{a['path']}`")
    else:
        data = {
            "id": eid,
            "name": exp["name"],
            "status": exp["status"],
            "created_at": exp["created_at"],
            "duration_s": exp["duration_s"],
            "script": exp["script"],
            "git_branch": exp["git_branch"],
            "git_commit": exp["git_commit"],
            "hostname": exp["hostname"],
            "tags": json.loads(exp["tags"] or "[]"),
            "notes": exp["notes"],
            "params": params,
            "metrics": metrics,
            "artifacts": artifacts,
        }
        print(json.dumps(data, indent=2, default=str))
