"""
exptrack/cli/help_cmds.py — self-documenting commands: `examples` and `docs`.

These make a plain `pip install exptrack` self-sufficient: the runnable examples
ship inside the package (see exptrack/examples/) so they can be listed, printed,
or copied out without the source tree, and `docs` opens the project's docs in a
browser. Neither touches the database.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..core.utils import safe_call
from .formatting import C, G, bold, col, die, dim

# name → (bundled filename, one-line description, how to run it)
_EXAMPLES = {
    "basic": (
        "basic_script.py",
        "argparse auto-capture — zero exptrack code in your training script",
        "exptrack run basic_script.py --lr 0.01 --epochs 10",
    ),
    "manual": (
        "manual_tracking.py",
        "explicit Python API (Experiment as a context manager)",
        "python manual_tracking.py",
    ),
    "resume": (
        "resume_training.py",
        "auto-detected --resume aggregates a continued run into one experiment",
        "exptrack run resume_training.py --output_dir /tmp/exp --epochs 5",
    ),
    "pipeline": (
        "pipeline_example.sh",
        "shell/SLURM pipeline via run-start / log-metric / run-finish",
        "bash pipeline_example.sh",
    ),
}

# friendly topic → docs/<file>, used for both the printed list and the URL
_DOCS_TOPICS = {
    "cli": "cli-reference.md",
    "dashboard": "dashboard.md",
    "python-api": "python-api.md",
    "config": "configuration.md",
    "how-it-works": "how-it-works.md",
    "monkey-patching": "monkey-patching.md",
    "sessions": "session-trees.md",
    "plugins": "plugins.md",
    "faq": "faq.md",
    "troubleshooting": "troubleshooting.md",
    "contributing": "contributing.md",
}

_DOCS_FALLBACK = "https://github.com/mikylab/exptrack/tree/main/docs"


def _bundled_text(filename: str) -> str:
    """Read a bundled example's source, working from an installed wheel too."""
    import importlib.resources as ir
    return ir.files("exptrack.examples").joinpath(filename).read_text(encoding="utf-8")


def cmd_examples(args):
    name = args.name
    if not name:
        print(bold("Bundled examples") + dim("  (ship with the installed package)"))
        print()
        for key, (_fn, desc, run) in _EXAMPLES.items():
            print(f"  {col(key, C)}  {desc}")
            print(dim(f"      {run}"))
        print()
        print(dim("Print one:            exptrack examples <name>"))
        print(dim("Copy into this dir:   exptrack examples <name> --copy"))
        return

    if name not in _EXAMPLES:
        die(f"unknown example '{name}'. Available: {', '.join(_EXAMPLES)}")
    fn, _desc, run = _EXAMPLES[name]
    try:
        text = _bundled_text(fn)
    except Exception as e:  # pragma: no cover - defensive
        die(f"could not read bundled example '{fn}': {e}")

    if args.copy:
        dest = Path.cwd() / fn
        if dest.exists() and not args.force:
            die(f"{fn} already exists in this directory — pass --force to overwrite")
        try:
            dest.write_text(text, encoding="utf-8")
        except OSError as e:
            die(f"could not write {fn}: {e}")
        print(col(f"Wrote {fn}", G))
        print(dim(f"  run: {run}"))
    else:
        # Print the source so it can be read or piped. The run hint goes to
        # stderr so `exptrack examples basic > train.py` stays clean.
        print(dim(f"# {fn} — run: {run}"), file=sys.stderr)
        sys.stdout.write(text)


def cmd_docs(args):
    base = _docs_base_url()
    topic = args.topic
    if topic:
        if topic not in _DOCS_TOPICS:
            die(f"unknown topic '{topic}'. Available: {', '.join(_DOCS_TOPICS)}")
        url = f"{base}/{_DOCS_TOPICS[topic]}"
        _open_url(url)
        print(f"{topic}: {url}")
        return

    print(bold("Documentation:"), base)
    print()
    for t in _DOCS_TOPICS:
        print(f"  {col(t, C)}")
    print()
    print(dim("Open a topic in your browser:  exptrack docs <topic>"))
    _open_url(base)


def _docs_base_url() -> str:
    """The project's documentation URL, read from package metadata when present
    (so it follows pyproject's [project.urls] Documentation), else a fallback."""
    try:
        from importlib.metadata import metadata
        for entry in metadata("exptrack").get_all("Project-URL") or []:
            label, _, link = entry.partition(",")
            if label.strip().lower() == "documentation" and link.strip():
                return link.strip().rstrip("/")
    except Exception:
        pass
    return _DOCS_FALLBACK


def _open_url(url: str):
    """Best-effort browser open; the printed URL is the fallback when headless."""
    import webbrowser
    safe_call(webbrowser.open, url, context="docs open")
