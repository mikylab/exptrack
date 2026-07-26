"""Tests for exptrack/core/utils.py — debug gating and safe_call."""
from __future__ import annotations

import pytest

from exptrack.core import utils

# ---------------------------------------------------------------------------
# debug_enabled / debug_log
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", "debug"])
def test_debug_enabled_truthy(monkeypatch, val):
    monkeypatch.setenv("EXPTRACK_DEBUG", val)
    assert utils.debug_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "  "])
def test_debug_enabled_falsy(monkeypatch, val):
    monkeypatch.setenv("EXPTRACK_DEBUG", val)
    assert utils.debug_enabled() is False


def test_debug_enabled_unset(monkeypatch):
    monkeypatch.delenv("EXPTRACK_DEBUG", raising=False)
    assert utils.debug_enabled() is False


def test_debug_log_silent_when_disabled(monkeypatch, capsys):
    monkeypatch.delenv("EXPTRACK_DEBUG", raising=False)
    utils.debug_log("should not appear")
    assert capsys.readouterr().err == ""


def test_debug_log_prints_when_enabled(monkeypatch, capsys):
    monkeypatch.setenv("EXPTRACK_DEBUG", "1")
    utils.debug_log("hello world")
    err = capsys.readouterr().err
    assert "hello world" in err
    assert "exptrack:debug" in err


# ---------------------------------------------------------------------------
# safe_call
# ---------------------------------------------------------------------------

def test_safe_call_returns_value():
    assert utils.safe_call(lambda x: x + 1, 41) == 42


def test_safe_call_passes_kwargs():
    assert utils.safe_call(lambda *, a, b: a * b, a=3, b=4) == 12


def test_safe_call_returns_default_on_exception():
    def boom():
        raise ValueError("nope")

    assert utils.safe_call(boom, default="fallback") == "fallback"


def test_safe_call_default_is_none():
    def boom():
        raise RuntimeError("x")

    assert utils.safe_call(boom) is None


def test_safe_call_logs_with_context_when_debug(monkeypatch, capsys):
    monkeypatch.setenv("EXPTRACK_DEBUG", "1")

    def boom():
        raise ValueError("kaboom")

    assert utils.safe_call(boom, default=0, context="my.op") == 0
    err = capsys.readouterr().err
    assert "my.op" in err
    assert "ValueError" in err


def test_safe_call_silent_failure_without_debug(monkeypatch, capsys):
    monkeypatch.delenv("EXPTRACK_DEBUG", raising=False)

    def boom():
        raise ValueError("kaboom")

    assert utils.safe_call(boom, default=0) == 0
    assert capsys.readouterr().err == ""
