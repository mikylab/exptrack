"""
exptrack/cli/pipeline_cmds.py — Shell / SLURM pipeline commands

run-start, run-finish, run-fail, log-metric, log-artifact

All output to stderr so stdout can be captured cleanly by eval $(...).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import config as cfg
from ..core import get_db


def _coerce_str(v: str):
    if v.lower() == "true":  return True
    if v.lower() == "false": return False
    try:    return int(v)
    except Exception: pass  # not an int, try float
    try:    return float(v)
    except Exception: pass  # not a float, return as string
    return v


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


def cmd_run_start(args):
    """
    Start an experiment from a shell script. Prints shell-sourceable env vars
    to stdout so the caller can do:

        eval $(exptrack run-start --lr 0.01 --epochs 50)
    """
    from ..core import Experiment

    # Parse free-form --key value pairs from remaining args
    params = {}
    raw = args.params
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

    conf = cfg.load()
    out_dir = cfg.project_root() / conf.get("outputs_dir", "outputs") / exp.name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Track the output directory in both the experiments table and as an artifact
    from ..core import get_db as _get_db
    conn = _get_db()
    conn.execute("UPDATE experiments SET output_dir=? WHERE id=?",
                 (str(out_dir), exp.id))
    conn.commit()

    exp.log_artifact(str(out_dir), label="output_dir")

    print(f'export EXP_ID="{exp.id}"')
    print(f'export EXP_NAME="{exp.name}"')
    print(f'export EXP_OUT="{out_dir}"')

    env_file = out_dir / ".exptrack_run.env"
    env_file.write_text(
        f"EXP_ID={exp.id}\n"
        f"EXP_NAME={exp.name}\n"
        f"EXP_OUT={out_dir}\n"
        f"EXP_CREATED={exp.created_at}\n"
    )


def cmd_run_finish(args):
    """Mark an experiment as done from a shell script."""
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id, name FROM experiments WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] run-finish: experiment '{args.id}' not found", file=sys.stderr)
        sys.exit(1)

    exp_id = exp_row["id"]
    step   = args.step

    if args.metrics:
        mpath = Path(args.metrics)
        if mpath.exists():
            try:
                raw = json.loads(mpath.read_text())
                flat = _flatten_dict(raw)
                numeric = {k: float(v) for k, v in flat.items()
                           if isinstance(v, (int, float)) and not isinstance(v, bool)}
                if numeric:
                    ts = datetime.now(timezone.utc).isoformat()
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

    # Scan output_dir for artifacts before closing
    out_row = conn.execute(
        "SELECT output_dir FROM experiments WHERE id=?", (exp_id,)
    ).fetchone()
    out_dir = out_row["output_dir"] if out_row else None
    if out_dir:
        out_path = Path(out_dir)
        if out_path.is_dir():
            hidden = {'.exptrack_run.env', '.DS_Store'}
            new_files = [p for p in out_path.rglob('*')
                         if p.is_file() and not p.name.startswith('.') and p.name not in hidden]
            ts = datetime.now(timezone.utc).isoformat()
            for p in new_files:
                try:
                    resolved = str(p.resolve())
                    existing = conn.execute(
                        "SELECT 1 FROM artifacts WHERE exp_id=? AND path=?",
                        (exp_id, resolved)
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
                            (exp_id, p.name, resolved, ts)
                        )
                except Exception as e:
                    print(f"[exptrack] warning: could not register artifact: {e}", file=sys.stderr)
            if new_files:
                conn.commit()
                if len(new_files) <= 5:
                    for p in new_files:
                        print(f"[exptrack] artifact: {p}", file=sys.stderr)
                else:
                    print(f"[exptrack] {len(new_files)} artifacts in {out_dir}/", file=sys.stderr)

    now = datetime.now(timezone.utc).isoformat()
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
    from ..plugins import registry as plugin_reg
    plugin_reg.load_from_config(cfg.load())

    class _FakeExp:
        pass
    fake = _FakeExp()
    row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
    for k in row:
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

    now = datetime.now(timezone.utc).isoformat()
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
    """Log a metric from shell: exptrack log-metric $EXP_ID loss 0.234 --step 10"""
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id FROM experiments WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] log-metric: not found: {args.id}", file=sys.stderr); sys.exit(1)

    exp_id = exp_row["id"]
    ts = datetime.now(timezone.utc).isoformat()

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

    # Support piped content via --stdin or path='-'
    if getattr(args, 'stdin', False) or args.path == '-':
        content = sys.stdin.buffer.read()
        from .. import config as _cfg
        out_dir = _cfg.project_root() / '.exptrack' / 'outputs'
        out_dir.mkdir(parents=True, exist_ok=True)
        label = args.label or 'stdin_capture'
        out_path = out_dir / f"{exp_row['id'][:8]}_{label}"
        out_path.write_bytes(content)
        args.path = str(out_path)

    ts = datetime.now(timezone.utc).isoformat()
    label = args.label or Path(args.path).name
    with conn:
        conn.execute(
            "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
            (exp_row["id"], label, args.path, ts)
        )
    print(f"[exptrack] Artifact: {label} -> {args.path}", file=sys.stderr)


def cmd_log_output(args):
    """Capture piped stdout as a log: some_command | exptrack log-output $EXP_ID --label training"""
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id, name, output_dir FROM experiments WHERE id LIKE ?",
        (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] log-output: not found: {args.id}", file=sys.stderr); sys.exit(1)

    # Determine output path
    out_dir = exp_row["output_dir"]
    if not out_dir:
        from .. import config as _cfg
        out_dir = str(_cfg.project_root() / '.exptrack' / 'outputs')
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    label = args.label or "output"
    log_path = Path(out_dir) / f"{label}.log"

    # Read from stdin and write to log file, echoing to stderr
    try:
        with open(log_path, "w") as f:
            for line in sys.stdin:
                f.write(line)
                if not args.quiet:
                    sys.stderr.write(line)
    except KeyboardInterrupt:
        pass

    # Register as artifact
    ts = datetime.now(timezone.utc).isoformat()
    resolved = str(log_path.resolve())
    with conn:
        existing = conn.execute(
            "SELECT 1 FROM artifacts WHERE exp_id=? AND path=?",
            (exp_row["id"], resolved)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
                (exp_row["id"], f"[log] {label}", resolved, ts)
            )
    print(f"[exptrack] Output captured: {log_path}", file=sys.stderr)


def cmd_log_result(args):
    """Manually log a result (key=value) to an experiment.

    Unlike log-metric which is for time-series data, log-result is for
    final outcomes like accuracy, F1 score, etc. Results are stored as
    metrics with source=manual to distinguish them.

    Usage:
        exptrack log-result $EXP_ID accuracy 0.95
        exptrack log-result $EXP_ID --file results.json
        echo '{"accuracy": 0.95}' | exptrack log-result $EXP_ID --file -
    """
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id FROM experiments WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] log-result: not found: {args.id}", file=sys.stderr); sys.exit(1)

    exp_id = exp_row["id"]
    ts = datetime.now(timezone.utc).isoformat()
    source = getattr(args, 'source', 'manual')

    results = {}  # key -> float
    if args.file:
        # Read from file or stdin
        if args.file == '-':
            raw = json.loads(sys.stdin.read())
        else:
            fpath = Path(args.file)
            if not fpath.exists():
                print(f"[exptrack] log-result: file not found: {fpath}", file=sys.stderr)
                sys.exit(1)
            raw = json.loads(fpath.read_text())
        flat = _flatten_dict(raw)
        for k, v in flat.items():
            if isinstance(v, bool):
                continue
            try:
                results[k] = float(v)
            except (ValueError, TypeError):
                print(f"[exptrack] log-result: skipping non-numeric value: {k}={v}", file=sys.stderr)
    else:
        if args.key is None or args.value is None:
            print("[exptrack] log-result: provide KEY VALUE or --file FILE", file=sys.stderr)
            sys.exit(1)
        try:
            results[args.key] = float(args.value)
        except ValueError:
            print(f"[exptrack] log-result: value must be a number, got: {args.value}", file=sys.stderr)
            sys.exit(1)

    if not results:
        return

    with conn:
        for k, v in results.items():
            # Remove any legacy _result:* param entry
            conn.execute(
                "DELETE FROM params WHERE exp_id=? AND key=?",
                (exp_id, f"_result:{k}")
            )
            # Store in metrics table with source tag
            conn.execute(
                "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
                "VALUES (?,?,?,NULL,?,?)",
                (exp_id, k, v, ts, source)
            )
    conn.commit()
    for k, v in results.items():
        print(f"[exptrack] result: {k}={v} (source: {source})", file=sys.stderr)


def cmd_link_dir(args):
    """Link a log/tensorboard/output directory to an experiment.

    Usage:
        exptrack link-dir $EXP_ID ./logs/run_42 --label tensorboard
        exptrack link-dir $EXP_ID ./checkpoints --label checkpoints
    """
    conn = get_db()
    exp_row = conn.execute(
        "SELECT id FROM experiments WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not exp_row:
        print(f"[exptrack] link-dir: not found: {args.id}", file=sys.stderr); sys.exit(1)

    dir_path = Path(args.path).resolve()
    if not dir_path.exists():
        print(f"[exptrack] link-dir: path not found: {dir_path}", file=sys.stderr)
        sys.exit(1)

    label = args.label or dir_path.name
    ts = datetime.now(timezone.utc).isoformat()

    # Register the directory itself as an artifact
    with conn:
        existing = conn.execute(
            "SELECT 1 FROM artifacts WHERE exp_id=? AND path=?",
            (exp_row["id"], str(dir_path))
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
                (exp_row["id"], f"[dir] {label}", str(dir_path), ts)
            )

    # Scan files in directory and register them too
    if dir_path.is_dir():
        file_count = 0
        for p in dir_path.rglob('*'):
            if not p.is_file():
                continue
            resolved = str(p.resolve())
            existing = conn.execute(
                "SELECT 1 FROM artifacts WHERE exp_id=? AND path=?",
                (exp_row["id"], resolved)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
                    (exp_row["id"], p.name, resolved, ts)
                )
                file_count += 1
        if file_count:
            conn.commit()
            print(f"[exptrack] Linked directory: {dir_path} ({file_count} files)", file=sys.stderr)
        else:
            conn.commit()
            print(f"[exptrack] Linked directory: {dir_path} (empty)", file=sys.stderr)
    else:
        conn.commit()
        print(f"[exptrack] Linked file: {dir_path}", file=sys.stderr)


def cmd_create(args):
    """Create a manual experiment entry for runs done outside exptrack."""
    import uuid

    conn = get_db()
    exp_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    created_at = args.date.strip() if args.date else now
    name = args.name.strip()

    conf = cfg.load()
    project = conf.get("project", "")

    tags = args.tags or []
    tags_json = json.dumps(tags) if tags else "[]"
    notes = args.notes.strip() if args.notes else None
    script = args.script.strip() if args.script else None
    command = args.command.strip() if args.command else None

    conn.execute(
        """INSERT INTO experiments
           (id, project, name, status, created_at, updated_at,
            script, command, hostname, python_ver, notes, tags, studies)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (exp_id, project, name, args.status, created_at, now,
         script, command, None, None, notes, tags_json, "[]")
    )

    # Parse and insert params
    if args.params:
        try:
            params = json.loads(args.params)
            if isinstance(params, dict):
                for k, v in params.items():
                    conn.execute(
                        "INSERT INTO params (exp_id, key, value) VALUES (?,?,?)",
                        (exp_id, k, json.dumps(v))
                    )
        except json.JSONDecodeError:
            print("[exptrack] Warning: could not parse --params as JSON", file=sys.stderr)

    # Parse and insert metrics
    if args.metrics:
        try:
            metrics = json.loads(args.metrics)
            if isinstance(metrics, dict):
                for k, v in metrics.items():
                    try:
                        num_val = float(v)
                    except (ValueError, TypeError):
                        continue
                    conn.execute(
                        "INSERT INTO metrics (exp_id, key, value, step, ts, source) VALUES (?,?,?,0,?,?)",
                        (exp_id, k, num_val, now, "manual")
                    )
        except json.JSONDecodeError:
            print("[exptrack] Warning: could not parse --metrics as JSON", file=sys.stderr)

    conn.commit()
    print(f"[exptrack] Created experiment: {name} ({exp_id})", file=sys.stderr)
