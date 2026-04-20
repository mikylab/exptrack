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
    from exptrack.capture.argparse_patch import _coerce

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
    from exptrack.capture.argparse_patch import capture_argv, patch_argparse
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
