"""Tests for exptrack/capture/argparse_patch.py — argparse monkey-patching."""
import argparse
import sys


def test_patch_captures_parse_args(tmp_project):
    """Patching argparse captures params from parse_args()."""
    import exptrack.capture.argparse_patch as ap_mod
    from exptrack.capture.argparse_patch import patch_argparse
    from exptrack.core import Experiment

    # Reset patch state
    ap_mod._patched = False

    exp = Experiment(script="train.py")
    patch_argparse(exp)

    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--epochs", type=int, default=10)

    old_argv = sys.argv
    sys.argv = ["train.py", "--lr", "0.001", "--epochs", "50"]
    try:
        ns = parser.parse_args()
    finally:
        sys.argv = old_argv

    assert ns.lr == 0.001
    assert ns.epochs == 50
    assert exp._params.get("lr") == 0.001
    assert exp._params.get("epochs") == 50

    exp.finish()

    # Restore original argparse
    ap_mod._patched = False


def test_patch_captures_parse_known_args(tmp_project):
    """Patching argparse captures params from parse_known_args()."""
    import exptrack.capture.argparse_patch as ap_mod
    from exptrack.capture.argparse_patch import patch_argparse
    from exptrack.core import Experiment

    ap_mod._patched = False

    exp = Experiment(script="train.py")
    patch_argparse(exp)

    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", type=float, default=0.01)

    old_argv = sys.argv
    sys.argv = ["train.py", "--lr", "0.5", "--unknown", "foo"]
    try:
        ns, remaining = parser.parse_known_args()
    finally:
        sys.argv = old_argv

    assert ns.lr == 0.5
    assert exp._params.get("lr") == 0.5
    # Unknown args should also be captured
    assert "--unknown" in remaining

    exp.finish()
    ap_mod._patched = False


def test_capture_argv_fallback(tmp_project):
    """capture_argv() parses sys.argv for scripts that don't use argparse."""
    from exptrack.capture.argparse_patch import capture_argv
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")

    old_argv = sys.argv
    sys.argv = ["train.py", "--lr", "0.01", "--epochs", "100", "--verbose"]
    try:
        capture_argv(exp)
    finally:
        sys.argv = old_argv

    assert exp._params.get("lr") == 0.01
    assert exp._params.get("epochs") == 100
    assert exp._params.get("verbose") is True

    exp.finish()


def test_coerce_types(tmp_project):
    """_coerce() properly converts string values to typed values."""
    from exptrack.core.utils import coerce_scalar as _coerce

    assert _coerce("true") is True
    assert _coerce("false") is False
    assert _coerce("42") == 42
    assert isinstance(_coerce("42"), int)
    assert _coerce("3.14") == 3.14
    assert isinstance(_coerce("3.14"), float)
    assert _coerce("hello") == "hello"


def test_key_value_equals_syntax(tmp_project):
    """capture_argv handles --key=value syntax."""
    from exptrack.capture.argparse_patch import capture_argv
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")

    old_argv = sys.argv
    sys.argv = ["train.py", "--lr=0.01", "--data=train"]
    try:
        capture_argv(exp)
    finally:
        sys.argv = old_argv

    assert exp._params.get("lr") == 0.01
    assert exp._params.get("data") == "train"

    exp.finish()


def test_single_dash_flags(tmp_project):
    """capture_argv handles -k value single-dash flags."""
    from exptrack.capture.argparse_patch import capture_argv
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")

    old_argv = sys.argv
    sys.argv = ["train.py", "-l", "0.01", "-e", "50"]
    try:
        capture_argv(exp)
    finally:
        sys.argv = old_argv

    assert exp._params.get("l") == 0.01
    assert exp._params.get("e") == 50

    exp.finish()


def test_dashed_long_flags_normalize_to_underscores(tmp_project):
    """capture_argv normalizes --batch-size to batch_size to match argparse's convention.

    Without this, a script that uses argparse (producing batch_size from --batch-size)
    and also goes through the raw argv fallback ends up with both keys in its params.
    """
    import exptrack.capture.argparse_patch as ap_mod
    from exptrack.capture.argparse_patch import capture_argv
    from exptrack.core import Experiment

    ap_mod._patched = False
    exp = Experiment(script="train.py")

    old_argv = sys.argv
    sys.argv = ["train.py", "--batch-size", "32", "--learning-rate=0.01", "--use-amp"]
    try:
        capture_argv(exp)
    finally:
        sys.argv = old_argv

    assert exp._params.get("batch_size") == 32
    assert exp._params.get("learning_rate") == 0.01
    assert exp._params.get("use_amp") is True
    assert "batch-size" not in exp._params
    assert "learning-rate" not in exp._params
    assert "use-amp" not in exp._params

    exp.finish()


def test_no_duplicate_with_argparse_plus_argv(tmp_project):
    """When both argparse and the argv fallback capture the same dashed flag,
    the resulting params have a single underscored key, not both variants."""
    import exptrack.capture.argparse_patch as ap_mod
    from exptrack.capture.argparse_patch import capture_argv, patch_argparse
    from exptrack.core import Experiment

    ap_mod._patched = False
    exp = Experiment(script="train.py")
    patch_argparse(exp)

    old_argv = sys.argv
    sys.argv = ["train.py", "--batch-size", "64"]
    try:
        # Raw argv fallback runs first (mirrors __main__.py)
        capture_argv(exp)
        # Then the script calls parse_args, which the patch intercepts
        parser = argparse.ArgumentParser()
        parser.add_argument("--batch-size", type=int)
        parser.parse_args()
    finally:
        sys.argv = old_argv

    assert exp._params.get("batch_size") == 64
    assert "batch-size" not in exp._params

    exp.finish()
    ap_mod._patched = False


def test_second_experiment_retargets_capture(tmp_project):
    """A second experiment created in the same process (without resetting the
    patch flag) must receive its own params — the hooks are installed once but
    retarget to the currently active experiment on each patch_argparse() call.

    Regression for M4: the old code closed over the first Experiment, so every
    later run leaked its params onto exp1.
    """
    import exptrack.capture.argparse_patch as ap_mod
    from exptrack.capture.argparse_patch import patch_argparse
    from exptrack.core import Experiment

    ap_mod._patched = False

    # First run patches argparse and captures its own params.
    exp1 = Experiment(script="train.py")
    patch_argparse(exp1)
    p1 = argparse.ArgumentParser()
    p1.add_argument("--lr", type=float)
    old_argv = sys.argv
    sys.argv = ["train.py", "--lr", "0.1"]
    try:
        p1.parse_args()
    finally:
        sys.argv = old_argv
    assert exp1._params.get("lr") == 0.1
    exp1.finish()

    # Second run: the class is ALREADY patched (do NOT reset _patched), yet its
    # params must land on exp2, not exp1.
    exp2 = Experiment(script="train.py")
    patch_argparse(exp2)  # retargets without re-patching
    p2 = argparse.ArgumentParser()
    p2.add_argument("--lr", type=float)
    sys.argv = ["train.py", "--lr", "0.9"]
    try:
        p2.parse_args()
    finally:
        sys.argv = old_argv

    assert exp2._params.get("lr") == 0.9, "params must go to the active experiment"
    assert exp1._params.get("lr") == 0.1, "earlier experiment must be untouched"

    exp2.finish()
    ap_mod._patched = False


# ── Negative numeric values (raw-argv capture) ────────────────────────────────

def test_capture_argv_keeps_negative_values(tmp_project):
    """`--lr -0.5` etc. must capture the value, not a boolean True."""
    from exptrack.capture.argparse_patch import capture_argv
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")

    old_argv = sys.argv
    sys.argv = ["train.py", "--lr", "-0.5", "--offset", "-3",
                "--eps", "-1e-4", "-o", "-2.5"]
    try:
        capture_argv(exp)
    finally:
        sys.argv = old_argv

    assert exp._params.get("lr") == -0.5
    assert exp._params.get("offset") == -3
    assert exp._params.get("eps") == -1e-4
    assert exp._params.get("o") == -2.5

    exp.finish()


def test_capture_argv_following_flag_stays_boolean(tmp_project):
    """A genuine following flag is still a boolean, not a value."""
    from exptrack.capture.argparse_patch import capture_argv
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")

    old_argv = sys.argv
    sys.argv = ["train.py", "--a", "--b", "-x", "-y", "--c", "--not-a-number"]
    try:
        capture_argv(exp)
    finally:
        sys.argv = old_argv

    assert exp._params.get("a") is True
    assert exp._params.get("b") is True
    assert exp._params.get("x") is True
    assert exp._params.get("y") is True
    assert exp._params.get("c") is True

    exp.finish()


def test_capture_remaining_keeps_negative_values(tmp_project):
    """The parse_known_args residual parser follows the same rule."""
    from exptrack.capture.argparse_patch import _capture_remaining
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")
    _capture_remaining(exp, ["--lr", "-0.5", "--flag", "--eps", "-1e-4"])

    assert exp._params.get("lr") == -0.5
    assert exp._params.get("flag") is True
    assert exp._params.get("eps") == -1e-4

    exp.finish()


def test_is_value_token_rule():
    from exptrack.core.utils import is_value_token as _is_value_token

    assert _is_value_token("0.5")
    assert _is_value_token("-0.5")
    assert _is_value_token("-3")
    assert _is_value_token("-1e-4")
    assert not _is_value_token("--lr")
    assert not _is_value_token("-x")
    assert not _is_value_token("--3")


def test_non_serializable_value_does_not_crash_parse_args(tmp_project):
    """A capture failure must never abort the user's parse_args().

    Regression test: if an argparse argument produces a value that isn't
    JSON-serializable (a custom ``type=`` callable returning an object,
    ``type=pathlib.Path``, an enum, ...), logging it used to raise TypeError
    *synchronously inside* the user's parse_args() and abort the training run.
    The capture hooks must swallow that and let parsing return normally, exactly
    as the matplotlib and tensorboard patches do.
    """
    import exptrack.capture.argparse_patch as ap_mod
    from exptrack.capture.argparse_patch import patch_argparse
    from exptrack.core import Experiment

    ap_mod._patched = False

    exp = Experiment(script="train.py")
    patch_argparse(exp)

    class _Weird:  # not JSON-serializable
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--obj", type=lambda s: _Weird())
    parser.add_argument("--lr", type=float, default=0.01)

    old_argv = sys.argv
    sys.argv = ["train.py", "--obj", "anything", "--lr", "0.5"]
    try:
        # The whole point: this line must NOT raise.
        ns = parser.parse_args()
    finally:
        sys.argv = old_argv
        ap_mod._patched = False

    # Parsing still returns the real, correct namespace to the user's script.
    assert isinstance(ns.obj, _Weird)
    assert ns.lr == 0.5
    # And the experiment is still usable afterwards (the run continues).
    exp.finish()


def test_capture_argv_does_not_crash_on_bad_experiment(tmp_project):
    """capture_argv runs at launch, before the user's script; it must not raise
    even if the underlying log_params fails."""
    from exptrack.capture.argparse_patch import capture_argv

    class _Boom:
        _params = {}

        def log_params(self, params):
            raise RuntimeError("simulated DB failure")

    old_argv = sys.argv
    sys.argv = ["train.py", "--lr", "0.1"]
    try:
        # Must swallow the failure rather than propagate it into launch.
        capture_argv(_Boom())
    finally:
        sys.argv = old_argv


def test_coerce_never_produces_non_finite_floats():
    """"inf"/"nan"/overflow parse as float but aren't valid JSON — keep as str.

    Regression: _coerce turned a literal string arg like `--stage inf` into
    float('inf'), which both mangles the value and injects a non-finite float
    that core/utils.json_dumps exists to keep out of our JSON (server.md)."""
    from exptrack.core.utils import coerce_scalar as _coerce

    for token in ["inf", "-inf", "nan", "Infinity", "infinity", "1e999"]:
        assert _coerce(token) == token, f"{token!r} should stay a string"

    # Real numbers are still coerced as before.
    assert _coerce("0.01") == 0.01
    assert _coerce("42") == 42
    assert _coerce("1e3") == 1000.0
    assert _coerce("true") is True


def test_coerce_only_coerces_clean_decimal_literals():
    """Only an unambiguous ASCII decimal literal coerces to a number; anything
    else keeps its original string so a param round-trips to what was typed.

    Regression: bare int()/float() accept "007" (padding lost), "1_000"
    (underscores), Arabic-Indic digits, and " 5 " (whitespace) — each silently
    stored a value different from the literal the user passed."""
    from exptrack.core.utils import coerce_scalar as c

    # These used to coerce to a *different* value; now kept as-is.
    for s in ["007", "08", "1_000", "555_1234", "3.14_15", "١٢٣", " 5 ", "0x10", "1,000"]:
        assert c(s) == s, f"{s!r} should stay a string"

    # Clean literals still coerce.
    assert c("42") == 42 and isinstance(c("42"), int)
    assert c("-7") == -7
    assert c("0") == 0
    assert c("3.14") == 3.14
    assert c(".5") == 0.5
    assert c("5.") == 5.0
    assert c("1e-4") == 0.0001
