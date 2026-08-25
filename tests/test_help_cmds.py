"""Tests for the self-documenting commands: exptrack examples / docs."""
import argparse

import pytest

from exptrack.cli.help_cmds import (
    _DOCS_TOPICS,
    _EXAMPLES,
    _bundled_text,
    _docs_base_url,
    cmd_docs,
    cmd_examples,
)


def _args(**kw):
    ns = argparse.Namespace(name=None, topic=None, copy=False, force=False)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_every_catalog_example_is_actually_bundled():
    """The catalog and the shipped files must not drift — each named example's
    file must be readable from the package (this is what makes it work from a
    wheel, not just the source tree)."""
    for name, (fn, _desc, _run) in _EXAMPLES.items():
        text = _bundled_text(fn)
        assert text.strip(), f"bundled example {name} ({fn}) is empty/missing"


def test_every_docs_topic_resolves_to_a_real_file():
    """Each _DOCS_TOPICS target must exist under docs/ — otherwise `exptrack docs
    <topic>` opens a browser to a 404. Same drift guard the examples get."""
    from pathlib import Path
    docs_dir = Path(__file__).resolve().parent.parent / "docs"
    for topic, fname in _DOCS_TOPICS.items():
        assert (docs_dir / fname).is_file(), f"docs topic {topic} -> {fname} missing"


def test_examples_list_runs(capsys):
    cmd_examples(_args())
    out = capsys.readouterr().out
    for name in _EXAMPLES:
        assert name in out


def test_examples_print_writes_source_to_stdout(capsys):
    cmd_examples(_args(name="basic"))
    captured = capsys.readouterr()
    # Source on stdout, the run hint on stderr (so redirection stays clean).
    assert "argparse" in captured.out
    assert "run:" in captured.err


def test_examples_unknown_name_exits(capsys):
    with pytest.raises(SystemExit) as e:
        cmd_examples(_args(name="does-not-exist"))
    assert e.value.code != 0


def test_examples_copy_writes_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cmd_examples(_args(name="manual", copy=True))
    dest = tmp_path / "manual_tracking.py"
    assert dest.exists() and dest.read_text().strip()

    # A second copy without --force must refuse rather than clobber.
    with pytest.raises(SystemExit):
        cmd_examples(_args(name="manual", copy=True))

    # With --force it overwrites cleanly.
    cmd_examples(_args(name="manual", copy=True, force=True))
    assert dest.exists()


def test_docs_list_runs(capsys, monkeypatch):
    # Don't actually open a browser in the test environment.
    monkeypatch.setattr("exptrack.cli.help_cmds._open_url", lambda url: None)
    cmd_docs(_args())
    out = capsys.readouterr().out
    assert "Documentation:" in out
    for topic in _DOCS_TOPICS:
        assert topic in out


def test_docs_topic_prints_url(capsys, monkeypatch):
    opened = {}
    monkeypatch.setattr("exptrack.cli.help_cmds._open_url",
                        lambda url: opened.setdefault("url", url))
    cmd_docs(_args(topic="cli"))
    out = capsys.readouterr().out
    assert _DOCS_TOPICS["cli"] in out
    assert opened.get("url", "").endswith(_DOCS_TOPICS["cli"])


def test_docs_unknown_topic_exits():
    with pytest.raises(SystemExit):
        cmd_docs(_args(topic="not-a-topic"))


def test_docs_base_url_is_a_url():
    base = _docs_base_url()
    assert base.startswith("http")
    assert "docs" in base
