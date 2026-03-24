"""Tests for exptrack/capture/variables.py — variable capture, summaries, fingerprinting."""
import json
import types

from exptrack.capture.variables import (
    _find_comment,
    extract_assignments,
    is_observational,
    var_fingerprint,
    var_summary,
)


# ---------------------------------------------------------------------------
# is_observational
# ---------------------------------------------------------------------------

def test_is_obs_print():
    """A cell with only print() is observational."""
    assert is_observational("print(x)") is True


def test_is_obs_assignment():
    """A cell with a plain assignment is NOT observational."""
    assert is_observational("x = 1") is False


def test_is_obs_mixed():
    """A cell with both an assignment and print is NOT observational."""
    assert is_observational("x = 1\nprint(x)") is False


def test_is_obs_empty():
    """An empty cell is NOT observational (no lines to inspect)."""
    assert is_observational("") is False


def test_is_obs_display():
    """A cell with only display() is observational."""
    assert is_observational("display(df)") is True


def test_is_obs_comments_only():
    """A cell with only comments has no non-comment lines, returns False (like empty)."""
    assert is_observational("# comment\n# another") is False


# ---------------------------------------------------------------------------
# var_summary
# ---------------------------------------------------------------------------

def test_summary_int():
    assert var_summary(42) == "42"


def test_summary_float():
    assert var_summary(3.14) == repr(3.14)


def test_summary_bool():
    assert var_summary(True) == "True"


def test_summary_str():
    assert var_summary("hello") == "'hello'"


def test_summary_long_str():
    """Strings longer than 200 chars are skipped."""
    assert var_summary("a" * 201) is None


def test_summary_function():
    """Function-like objects are skipped."""
    fn = types.FunctionType(compile("0", "<test>", "eval"), {}, "myfunc")
    assert var_summary(fn) is None


def test_summary_list():
    assert var_summary([1, 2, 3]) == "list(len=3)"


def test_summary_dict():
    assert var_summary({"a": 1}) == "dict(len=1, keys=['a'])"


# ---------------------------------------------------------------------------
# var_fingerprint
# ---------------------------------------------------------------------------

def test_fp_scalar():
    assert var_fingerprint(42) == "42"


def test_fp_string():
    assert var_fingerprint("hello") == "'hello'"


def test_fp_small_list():
    """Small lists are fingerprinted via JSON."""
    result = var_fingerprint([1, 2])
    assert result == json.dumps([1, 2], default=str, sort_keys=True)


def test_fp_large_collection():
    """Collections exceeding 10000 items use id-based fingerprint."""
    big = list(range(10001))
    result = var_fingerprint(big)
    assert "list:" in result
    assert str(id(big)) in result


# ---------------------------------------------------------------------------
# extract_assignments
# ---------------------------------------------------------------------------

def test_extract_simple():
    assert extract_assignments("x = 1") == {"x": "1"}


def test_extract_tuple():
    result = extract_assignments("a, b = 1, 2")
    assert "a" in result
    assert "b" in result
    assert result["a"] == "1, 2"
    assert result["b"] == "1, 2"


def test_extract_augmented_skip():
    """Augmented assignments (+=) are NOT captured."""
    assert extract_assignments("x += 1") == {}


def test_extract_comparison_skip():
    """Comparisons (==) are NOT captured."""
    assert extract_assignments("x == 1") == {}


def test_extract_magic_skip():
    """IPython magic lines are skipped."""
    assert extract_assignments("%magic") == {}


def test_extract_comment_strip():
    """Trailing comments are stripped from the RHS."""
    result = extract_assignments("x = 1 # note")
    assert result == {"x": "1"}


# ---------------------------------------------------------------------------
# _find_comment
# ---------------------------------------------------------------------------

def test_find_comment_simple():
    assert _find_comment("# comment") == 0


def test_find_comment_inline():
    assert _find_comment("x = 1 # note") == 6


def test_find_comment_in_string():
    """Hash inside a quoted string is NOT a comment."""
    assert _find_comment('x = "has # inside"') == -1


def test_find_comment_none():
    assert _find_comment("x = 1") == -1
