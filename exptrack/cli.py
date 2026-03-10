"""
exptrack/cli.py — Terminal interface

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
exptrack stale --hours N      mark killed runs as failed
exptrack upgrade              run schema migrations
exptrack ui                   launch web dashboard
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .core import get_db
from . import config as cfg

# ── ANSI ──────────────────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"
M = "\033[95m"; W = "\033[97m"; DIM = "\033[2m"; B = "\033[1m"; RST = "\033[0m"
STATUS_C = {"done": G, "running": Y, "failed": R}
STATUS_I = {"done": "+", "running": "~", "failed": "x"}
def col(t, c): return f"{c}{t}{RST}"
def dim(t): return f"{DIM}{t}{RST}"
def bold(t): return f"{B}{t}{RST}"


def fmt_dt(iso):
    if not iso: return dim("--")
    try: return datetime.fromisoformat(iso).strftime("%m/%d %H:%M")
    except Exception: return iso

def fmt_dur(s):
    if s is None: return dim("--")
    return f"{int(s//60)}m{int(s%60)}s" if s >= 60 else f"{s:.1f}s"


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_init(args):
    cfg.init(project_name=args.name or "")


def cmd_run(args):
    """Hand off to __main__.py logic inline."""
    script = args.script
    # Rebuild sys.argv so the wrapped script sees its own args
    sys.argv = [script] + args.script_args
    from . import __main__ as m
    m.main()


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

    arts = conn.execute("SELECT label, path FROM artifacts WHERE exp_id=?",
                        (exp["id"],)).fetchall()
    if arts:
        sec("Outputs")
        for a in arts:
            exists = "[ok]" if Path(a["path"]).exists() else dim("[missing]")
            print(f"    {col(a['label'] or 'file', Y):<30} {a['path']}  {exists}")
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
            v1 = str(p1.get(k, dim("--")))
            v2 = str(p2.get(k, dim("--")))
            marker = col("  < differs", Y) if p1.get(k) != p2.get(k) else ""
            print(f"  {k:<26} {v1:<30} {v2:<30}{marker}")
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

        # Changed variables
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

        # Source diff
        diff = snap.get("source_diff")
        if diff:
            print(col("    Cell diff:", C))
            for entry in diff[:20]:
                op, line = entry.get("op","="), entry.get("line","")
                if op == "+": print(col(f"      + {line}", G))
                elif op == "-": print(col(f"      - {line}", R))

        # Output snippet
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


def cmd_rm(args):
    conn = get_db()
    exp = conn.execute("SELECT id, name FROM experiments WHERE id LIKE ?",
                       (args.id + "%",)).fetchone()
    if not exp: print(col(f"Not found: {args.id}", R)); return
    confirm = input(f"Delete '{exp['name']}' ({exp['id'][:6]})? [y/N] ")
    if confirm.lower() == "y":
        for t in ("metrics", "params", "artifacts"):
            conn.execute(f"DELETE FROM {t} WHERE exp_id=?", (exp["id"],))
        conn.execute("DELETE FROM experiments WHERE id=?", (exp["id"],))
        conn.commit()
        print(col("Deleted.", G))


def cmd_clean(args):
    conn = get_db()
    rows = conn.execute("SELECT id, name FROM experiments WHERE status='failed'").fetchall()
    if not rows: print(dim("No failed experiments.")); return
    print(f"Found {len(rows)} failed:")
    for r in rows: print(f"  {r['id'][:6]}  {r['name']}")
    if input("Delete all? [y/N] ").lower() == "y":
        for r in rows:
            for t in ("metrics", "params", "artifacts"):
                conn.execute(f"DELETE FROM {t} WHERE exp_id=?", (r["id"],))
            conn.execute("DELETE FROM experiments WHERE id=?", (r["id"],))
        conn.commit()
        print(col(f"Cleaned {len(rows)} experiments.", G))


def cmd_ui(args):
    dashboard = Path(__file__).parent / "dashboard" / "app.py"
    if not dashboard.exists():
        print(col(f"Dashboard not found at {dashboard}", R))
        return
    port = args.port if hasattr(args, "port") else 7331
    print(col(f"Launching dashboard -> http://localhost:{port}", C))
    os.execvp(sys.executable, [sys.executable, str(dashboard), str(port)])


# ── Shell pipeline commands ───────────────────────────────────────────────────
# These are designed to be called FROM .sh / SLURM scripts.
# All output to stderr so stdout can be captured cleanly by eval $(...).

def cmd_run_start(args):
    """
    Start an experiment from a shell script. Prints shell-sourceable env vars
    to stdout so the caller can do:

        eval $(exptrack run-start --lr 0.01 --epochs 50)
        # Now $EXP_ID, $EXP_NAME, $EXP_OUT are set

    Any --key value pairs become experiment params.
    """
    from .core import Experiment

    # Parse free-form --key value pairs from remaining args
    params = {}
    raw = args.params  # list of strings like ["--lr", "0.01", "--epochs", "50"]
    i = 0
    while i < len(raw):
        a = raw[i]
        if a.startswith("--"):
            key = a[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                params[k] = _coerce_str(v)
            elif i + 1 < len(raw) and not raw[i+1].startswith("--"):
                params[key] = _coerce_str(raw[i+1])
                i += 1
            else:
                params[key] = True
        i += 1

    # Add SLURM context if present
    slurm_vars = {
        "SLURM_JOB_ID":       os.environ.get("SLURM_JOB_ID"),
        "SLURM_JOB_NAME":     os.environ.get("SLURM_JOB_NAME"),
        "SLURM_NODELIST":     os.environ.get("SLURM_NODELIST"),
        "SLURM_CPUS_ON_NODE": os.environ.get("SLURM_CPUS_ON_NODE"),
        "SLURM_MEM_PER_NODE": os.environ.get("SLURM_MEM_PER_NODE"),
        "SLURM_GPUS":         os.environ.get("SLURM_GPUS"),
    }
    slurm = {k: v for k, v in slurm_vars.items() if v}
    if slurm:
        params["_slurm"] = slurm

    # Tags and notes from flags
    tags  = args.tags or []
    notes = args.notes or ""
    name  = args.name or ""

    exp = Experiment(
        name=name,
        params=params,
        tags=tags,
        notes=notes,
        script=args.script or os.environ.get("SLURM_JOB_NAME", "pipeline"),
        _caller_depth=0,
    )

    # The output directory — all steps of the pipeline write here
    conf = cfg.load()
    out_dir = cfg.project_root() / conf.get("outputs_dir", "outputs") / exp.name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Register the output dir as an artifact placeholder
    exp.log_artifact(str(out_dir), label="output_dir")

    # Print shell-sourceable export statements to stdout
    # stderr goes to terminal, stdout is captured by eval $()
    print(f'export EXP_ID="{exp.id}"')
    print(f'export EXP_NAME="{exp.name}"')
    print(f'export EXP_OUT="{out_dir}"')

    # Also write a .env file inside the output dir for reference
    env_file = out_dir / ".exptrack_run.env"
    env_file.write_text(
        f"EXP_ID={exp.id}\n"
        f"EXP_NAME={exp.name}\n"
        f"EXP_OUT={out_dir}\n"
        f"EXP_CREATED={exp.created_at}\n"
    )


def _coerce_str(v: str):
    if v.lower() == "true":  return True
    if v.lower() == "false": return False
    try:    return int(v)
    except Exception: pass
    try:    return float(v)
    except Exception: pass
    return v


def cmd_run_finish(args):
    """
    Mark an experiment as done from a shell script.

        exptrack run-finish $EXP_ID
        exptrack run-finish $EXP_ID --metrics results.json
    """
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id, name FROM experiments WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] run-finish: experiment '{args.id}' not found", file=sys.stderr)
        sys.exit(1)

    exp_id = exp_row["id"]
    step   = args.step

    # Load and log metrics from JSON file
    if args.metrics:
        mpath = Path(args.metrics)
        if mpath.exists():
            try:
                raw = json.loads(mpath.read_text())
                flat = _flatten_dict(raw)
                numeric = {k: float(v) for k, v in flat.items()
                           if isinstance(v, (int, float)) and not isinstance(v, bool)}
                if numeric:
                    ts = datetime.utcnow().isoformat()
                    with conn:
                        conn.executemany(
                            "INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)",
                            [(exp_id, k, v, step, ts) for k, v in numeric.items()]
                        )
                    print(f"[exptrack] Logged {len(numeric)} metrics from {mpath.name}",
                          file=sys.stderr)
            except Exception as e:
                print(f"[exptrack] Warning: could not parse metrics file: {e}", file=sys.stderr)
        else:
            print(f"[exptrack] Warning: metrics file not found: {mpath}", file=sys.stderr)

    # Log any --param key=value pairs
    if args.params:
        params = {}
        for pair in args.params:
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = _coerce_str(v)
        if params:
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO params (exp_id, key, value) VALUES (?,?,?)",
                    [(exp_id, k, json.dumps(v)) for k, v in params.items()]
                )

    # Mark done and compute duration
    now = datetime.utcnow().isoformat()
    created = conn.execute(
        "SELECT created_at FROM experiments WHERE id=?", (exp_id,)
    ).fetchone()["created_at"]
    duration = (datetime.fromisoformat(now) - datetime.fromisoformat(created)).total_seconds()

    with conn:
        conn.execute("""
            UPDATE experiments SET status='done', updated_at=?, duration_s=? WHERE id=?
        """, (now, duration, exp_id))

    m, s = divmod(duration, 60)
    print(f"[exptrack] done: {exp_row['name']}  ({int(m)}m {s:.0f}s)", file=sys.stderr)

    # Fire finish plugins
    from .plugins import registry as plugin_reg
    plugin_reg.load_from_config(cfg.load())

    # Build a minimal Experiment-like object for plugins
    class _FakeExp:
        pass
    fake = _FakeExp()
    row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
    for k in row.keys():
        setattr(fake, k, row[k])
    fake._params = {r["key"]: json.loads(r["value"]) for r in
                    conn.execute("SELECT key, value FROM params WHERE exp_id=?",
                                 (exp_id,)).fetchall()}
    fake.status = "done"
    fake.duration_s = duration
    fake.last_metrics = lambda: {r["key"]: r["value"] for r in conn.execute("""
        SELECT key, value FROM metrics m WHERE exp_id=?
        GROUP BY key HAVING MAX(COALESCE(step,0))
    """, (exp_id,)).fetchall()}
    plugin_reg.on_finish(fake)


def cmd_run_fail(args):
    """Mark an experiment as failed: exptrack run-fail $EXP_ID "reason" """
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id, name, created_at FROM experiments WHERE id LIKE ?",
        (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] run-fail: not found: {args.id}", file=sys.stderr); sys.exit(1)

    now = datetime.utcnow().isoformat()
    duration = (datetime.fromisoformat(now) -
                datetime.fromisoformat(exp_row["created_at"])).total_seconds()
    reason = args.reason or "shell script exited non-zero"
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO params (exp_id, key, value) VALUES (?,?,?)",
            (exp_row["id"], "error", json.dumps(reason))
        )
        conn.execute("""
            UPDATE experiments SET status='failed', updated_at=?, duration_s=? WHERE id=?
        """, (now, duration, exp_row["id"]))
    print(f"[exptrack] FAILED: {exp_row['name']}  -- {reason}", file=sys.stderr)


def cmd_log_metric(args):
    """
    Log a metric from shell: exptrack log-metric $EXP_ID loss 0.234 --step 10
    Can also accept a JSON file:  exptrack log-metric $EXP_ID --file results.json
    """
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id FROM experiments WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] log-metric: not found: {args.id}", file=sys.stderr); sys.exit(1)

    exp_id = exp_row["id"]
    ts = datetime.utcnow().isoformat()

    if args.file:
        fpath = Path(args.file)
        if not fpath.exists():
            print(f"[exptrack] log-metric: file not found: {fpath}", file=sys.stderr); sys.exit(1)
        raw = json.loads(fpath.read_text())
        flat = _flatten_dict(raw)
        rows = [(exp_id, k, float(v), args.step, ts)
                for k, v in flat.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    else:
        if args.key is None or args.value is None:
            print("[exptrack] log-metric: provide KEY VALUE or --file FILE", file=sys.stderr)
            sys.exit(1)
        rows = [(exp_id, args.key, float(args.value), args.step, ts)]

    with conn:
        conn.executemany(
            "INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)", rows
        )
    for _, k, v, step, _ in rows:
        step_str = f" step={step}" if step is not None else ""
        print(f"[exptrack] metric: {k}={v}{step_str}", file=sys.stderr)


def cmd_log_artifact(args):
    """Register an output file: exptrack log-artifact $EXP_ID path/to/file.pt --label model"""
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id FROM experiments WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] log-artifact: not found: {args.id}", file=sys.stderr); sys.exit(1)
    ts = datetime.utcnow().isoformat()
    label = args.label or Path(args.path).name
    with conn:
        conn.execute(
            "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
            (exp_row["id"], label, args.path, ts)
        )
    print(f"[exptrack] Artifact: {label} -> {args.path}", file=sys.stderr)


def cmd_stale(args):
    """
    Mark experiments that have been 'running' longer than --hours as timed-out.
    Useful as a SLURM epilog or cron job to clean up killed runs.
    """
    from datetime import timedelta
    conn = get_db()
    cutoff = datetime.utcnow() - timedelta(hours=args.hours)
    rows = conn.execute("""
        SELECT id, name, created_at FROM experiments
        WHERE status='running' AND created_at < ?
    """, (cutoff.isoformat(),)).fetchall()
    if not rows:
        print(dim(f"No stale experiments (running > {args.hours}h).")); return
    print(f"Marking {len(rows)} stale experiment(s) as timed-out:")
    now = datetime.utcnow().isoformat()
    for r in rows:
        duration = (datetime.fromisoformat(now) -
                    datetime.fromisoformat(r["created_at"])).total_seconds()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO params (exp_id, key, value) VALUES (?,?,?)",
                (r["id"], "error", json.dumps(f"timed-out after {args.hours}h"))
            )
            conn.execute("""
                UPDATE experiments SET status='failed', updated_at=?, duration_s=? WHERE id=?
            """, (now, duration, r["id"]))
        print(f"  {col(r['id'][:6], C)}  {r['name'][:50]}")


def cmd_upgrade(args):
    """Run schema migrations and optionally reinstall the package."""
    conn = get_db()

    # Get current columns
    cols = {row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()}

    migrations = []

    # Add columns that may be missing from older schemas
    new_cols = {
        "hostname":   "TEXT",
        "python_ver": "TEXT",
        "duration_s": "REAL",
        "notes":      "TEXT",
        "tags":       "TEXT",
        "command":    "TEXT",
    }
    for col_name, col_type in new_cols.items():
        if col_name not in cols:
            conn.execute(f"ALTER TABLE experiments ADD COLUMN {col_name} {col_type}")
            migrations.append(col_name)

    conn.commit()

    if migrations:
        print(col(f"Added columns: {', '.join(migrations)}", G))
    else:
        print(dim("Schema is up to date."))

    # Reinstall if requested
    if args.reinstall:
        root = cfg.project_root()
        print("Reinstalling package...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(root)],
                       check=True)
        print(col("Reinstalled.", G))


def _flatten_dict(d: dict, prefix: str = "") -> dict:
    """Flatten nested dict: {"val": {"loss": 0.3}} -> {"val/loss": 0.3}"""
    out = {}
    for k, v in d.items():
        key = f"{prefix}/{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten_dict(v, key))
        else:
            out[key] = v
    return out


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # run-start accepts arbitrary --key value user params — handle before argparse
    # consumes them as unknown flags.
    if len(sys.argv) > 1 and sys.argv[1] == "run-start":
        p_rs = argparse.ArgumentParser(prog="exptrack run-start")
        p_rs.add_argument("--name",   default="")
        p_rs.add_argument("--script", default="")
        p_rs.add_argument("--tags",   nargs="*")
        p_rs.add_argument("--notes",  default="")
        known, unknown = p_rs.parse_known_args(sys.argv[2:])
        known.params = unknown
        cmd_run_start(known)
        return

    p = argparse.ArgumentParser(
        prog="exptrack",
        description="Experiment tracker -- scripts, notebooks, and SLURM pipelines",
    )
    sub = p.add_subparsers(dest="cmd")

    # ── Project setup ─────────────────────────────────────────────────────────
    sub.add_parser("init").add_argument("name", nargs="?", default="")

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
    p_la.add_argument("path")
    p_la.add_argument("--label", default="")

    p_stale = sub.add_parser("stale", help="Mark killed/timed-out runs as failed")
    p_stale.add_argument("--hours", type=float, default=24,
                         help="Mark as timed-out if running longer than this (default: 24)")

    # ── Schema management ────────────────────────────────────────────────────
    p_up = sub.add_parser("upgrade", help="Run schema migrations")
    p_up.add_argument("--reinstall", action="store_true",
                      help="Also pip install -e . after migration")

    # ── Inspection ────────────────────────────────────────────────────────────
    p_ls = sub.add_parser("ls")
    p_ls.add_argument("-n", type=int, default=20)

    sub.add_parser("show").add_argument("id")
    sub.add_parser("diff").add_argument("id")

    p_cmp = sub.add_parser("compare")
    p_cmp.add_argument("id1"); p_cmp.add_argument("id2")

    p_hist = sub.add_parser("history")
    p_hist.add_argument("notebook")
    p_hist.add_argument("id", nargs="?", default="")

    p_tag = sub.add_parser("tag")
    p_tag.add_argument("id"); p_tag.add_argument("tag")

    p_note = sub.add_parser("note")
    p_note.add_argument("id"); p_note.add_argument("text")

    sub.add_parser("rm").add_argument("id")
    sub.add_parser("clean")

    p_ui = sub.add_parser("ui")
    p_ui.add_argument("--port", type=int, default=7331)

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
        "stale":        cmd_stale,
        "upgrade":      cmd_upgrade,
        "ls":           cmd_ls,
        "show":         cmd_show,
        "diff":         cmd_diff,
        "compare":      cmd_compare,
        "history":      cmd_history,
        "tag":          cmd_tag,
        "note":         cmd_note,
        "rm":           cmd_rm,
        "clean":        cmd_clean,
        "ui":           cmd_ui,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
