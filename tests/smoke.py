#!/usr/bin/env python
"""End-to-end smoke test — the 30-second "does the whole thing still work?" check.

This is deliberately NOT a pytest test. It exercises the real console commands
in a throwaway git repo, the same way a user would: init a project, run a script
that uses argparse (so auto-capture fires), then read it back with `ls` and
`show`. If this passes, the core promise of the tool is intact.

Run it with `python tests/smoke.py`. It prints a clear PASS/FAIL and leaves
nothing behind.

stdlib only, on purpose — it must run anywhere the package installs.
"""
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _isolation import isolate_home

# Every child process runs against a throwaway HOME: `exptrack init` registers
# the project in the user-global ~/.exptrack/projects.json, and a smoke test
# must not leave its temp directory in the developer's project switcher. Set
# on this process, so every child inherits it without a per-call env=.
_HOME = isolate_home("exptrack-smoke-home-")

# A tiny bootstrap so we invoke exptrack's CLI regardless of whether the
# `exptrack` console script is on PATH — we drive exptrack.cli.main directly
# with an injected argv, in a fresh subprocess per command (real isolation).
_BOOTSTRAP = (
    "import sys; sys.argv = sys.argv[1:]; "
    "from exptrack.cli import main; sys.exit(main() or 0)"
)


def run(cwd, *args, expect_ok=True):
    """Run one exptrack command in `cwd`; return CompletedProcess."""
    cmd = [sys.executable, "-c", _BOOTSTRAP, "exptrack", *args]
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=120
    )
    label = "exptrack " + " ".join(args)
    if expect_ok and proc.returncode != 0:
        print(f"  FAIL: `{label}` exited {proc.returncode}")
        print(textwrap.indent(proc.stdout + proc.stderr, "    | "))
        raise SystemExit(1)
    print(f"  ok: {label}")
    return proc


def main():
    print("exptrack smoke test")
    with tempfile.TemporaryDirectory(prefix="exptrack-smoke-") as tmp:
        proj = Path(tmp)
        # A real git repo so git-state capture has something to read.
        subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
        subprocess.run(
            ["git", "config", "user.email", "smoke@example.com"], cwd=proj,
            check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "smoke"], cwd=proj, check=True
        )

        # A minimal training script that uses argparse — exercises the headline
        # auto-capture path.
        (proj / "train.py").write_text(textwrap.dedent("""
            import argparse
            p = argparse.ArgumentParser()
            p.add_argument("--lr", type=float, default=0.01)
            p.add_argument("--epochs", type=int, default=5)
            a = p.parse_args()
            print(f"trained lr={a.lr} epochs={a.epochs}")
        """))

        run(proj, "init", "smoke_proj")
        run(proj, "run", "train.py", "--lr", "0.05", "--epochs", "3")
        ls = run(proj, "ls")

        # The run must actually show up, with its captured param reflected in
        # the generated name.
        if "lr0.05" not in ls.stdout:
            print("  FAIL: `ls` did not show the run we just created (lr0.05).")
            print(textwrap.indent(ls.stdout, "    | "))
            raise SystemExit(1)
        print("  ok: run is listed with its captured params")

        # A second run so run-vs-run comparison has a baseline to work against.
        run(proj, "run", "train.py", "--lr", "0.1", "--epochs", "3")
        ls2 = run(proj, "ls").stdout
        if ls2.count("done") < 2:
            print("  FAIL: expected two completed runs after a second run.")
            print(textwrap.indent(ls2, "    | "))
            raise SystemExit(1)
        print("  ok: second run captured; run-vs-run baseline exists")

        # The shell/SLURM pipeline, driven the way a job script drives it:
        # run-start emits shell assignments, run-finish ingests the results.
        # This leg exists because `run-finish` once dispatched to nothing and
        # exited 0 — every direct-call test passed while the documented
        # pipeline could not finish a run.
        start = run(proj, "run-start", "--script", "pipeline.sh", "--lr", "0.2")
        exp_id = ""
        for line in start.stdout.splitlines():
            if "EXP_ID=" in line:
                exp_id = line.split("EXP_ID=", 1)[1].strip().strip('";')
        if not exp_id:
            print("  FAIL: run-start did not emit an EXP_ID assignment.")
            print(textwrap.indent(start.stdout + start.stderr, "    | "))
            raise SystemExit(1)
        print(f"  ok: run-start emitted EXP_ID={exp_id}")

        (proj / "results.json").write_text('{"val_acc": 0.91}')
        run(proj, "run-finish", exp_id, "--metrics", "results.json")

        show = run(proj, "show", exp_id).stdout
        if "running" in show or "val_acc" not in show:
            print("  FAIL: run-finish did not complete the run or ingest metrics.")
            print(textwrap.indent(show, "    | "))
            raise SystemExit(1)
        print("  ok: pipeline run finished and its metrics were ingested")

    print("\nSMOKE PASSED — init, auto-capture, run, pipeline, and read-back all work.")


if __name__ == "__main__":
    main()
