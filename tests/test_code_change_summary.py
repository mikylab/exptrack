"""Guards for the `_code_changes` summary.

The cap used to be a bare `[:1000]` slice. A working tree that had drifted from
HEAD spent that whole budget on unrelated lines, so the edit the run was
actually testing (`if i >= 1000` → `if i == -1`, a warm-up constant) was cut off
with nothing marking the cut — indistinguishable from "no code changed".
"""
from exptrack.core.utils import CODE_CHANGE_MAX_CHARS, summarize_changed_lines


def _frag(i):
    return f"- # filler comment line {i} pushing the real edit down the diff"


def test_late_change_survives_a_long_drift():
    """The last fragment must be kept when the whole summary fits the cap."""
    frags = [_frag(i) for i in range(80)] + ["- if i >= 1000:", "+ if i == -1:"]
    out = summarize_changed_lines(frags)
    assert "+ if i == -1:" in out
    assert "- if i >= 1000:" in out
    # Sanity: this is exactly the case the old 1000-char slice dropped.
    assert len("; ".join(frags)) > 1000


def test_truncation_is_stated_and_cuts_on_a_boundary():
    frags = [f"+ {'x' * 40}" for _ in range(10)]
    out = summarize_changed_lines(frags, max_chars=200)
    assert "truncated" in out
    assert "of 10 changed lines shown" in out
    # Never ends mid-fragment.
    body = out.split("; … [truncated")[0]
    assert all(p == "+ " + "x" * 40 for p in body.split("; "))


def test_untruncated_summary_carries_no_marker():
    assert summarize_changed_lines(["+ a", "- b"]) == "+ a; - b"
    assert summarize_changed_lines([]) == ""


def test_unusable_cap_never_swallows_the_summary():
    """A hand-edited config must not be why a run records no code changes."""
    for bad in (0, -3, "abc", None, 2.5):
        assert summarize_changed_lines(["+ real edit"], max_chars=bad) == "+ real edit"


def test_default_cap_is_large_enough_for_a_real_drifted_diff():
    assert CODE_CHANGE_MAX_CHARS >= 10000


def test_a_single_fragment_longer_than_the_cap_still_survives():
    """One giant changed line (minified code, a long literal) must not yield
    a content-free summary — dropping the change entirely is the exact
    failure this function exists to prevent."""
    from exptrack.core.utils import summarize_changed_lines
    giant = "+ x = " + "1" * 500
    out = summarize_changed_lines([giant], max_chars=100)
    assert out.startswith("+ x = 111")          # the change is visible
    assert "[truncated" in out                   # and the cut is stated
    assert not out.startswith("; ")              # no malformed leading join
