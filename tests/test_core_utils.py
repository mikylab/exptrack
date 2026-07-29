"""Tests for exptrack/core/utils.py — debug gating, safe_call, json_dumps."""
from __future__ import annotations

import json

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


# ── json_dumps: output every JSON parser accepts ────────────────────────────
#
# json.dumps renders inf as the bare token `Infinity`. Python's json.loads
# reads it back (a non-standard extension), so a server-side round-trip test
# would never catch it — but JSON.parse rejects the whole document, which is
# how one non-finite metric made the dashboard report "Experiment not found".
# These assert against a *strict* parse, not Python's lenient default.

def _strict_loads(text):
    """json.loads with the NaN/Infinity extension disabled, like JSON.parse."""
    def _reject(token):
        raise ValueError(f"non-standard JSON token: {token}")
    return json.loads(text, parse_constant=_reject)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_json_dumps_renders_non_finite_as_null(bad):
    out = utils.json_dumps({"value": bad})
    assert _strict_loads(out) == {"value": None}


def test_json_dumps_output_is_strictly_parseable_when_nested():
    payload = {"series": [{"v": float("inf")}, {"v": 1.5}],
               "summary": {"max": float("-inf"), "n": 2}}
    parsed = _strict_loads(utils.json_dumps(payload))
    assert parsed["series"] == [{"v": None}, {"v": 1.5}]
    assert parsed["summary"] == {"max": None, "n": 2}


def test_json_dumps_leaves_a_clean_payload_untouched():
    payload = {"a": [1, 2.5, None], "b": {"c": "x"}, "d": True}
    assert utils.json_dumps(payload) == json.dumps(payload)


def test_json_dumps_forwards_kwargs():
    out = utils.json_dumps({"a": 1}, indent=2)
    assert "\n" in out and _strict_loads(out) == {"a": 1}


def test_json_dumps_still_uses_default_for_unserializable_objects():
    class Thing:
        def __str__(self):
            return "thing"

    assert _strict_loads(utils.json_dumps({"t": Thing()}, default=str)) == {"t": "thing"}


def test_json_dumps_reraises_a_non_finite_unrelated_value_error():
    """A circular reference must still fail, not be swallowed by the retry."""
    d = {}
    d["self"] = d
    with pytest.raises(ValueError):
        utils.json_dumps(d)
