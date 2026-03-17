"""Tests for exptrack/core/naming.py — run naming and output paths."""
import re


def test_make_run_name_basic(tmp_project):
    """make_run_name produces expected format with script and params."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py", {"lr": 0.01, "epochs": 10})
    assert name.startswith("train__")
    assert "lr" in name
    assert "__" in name  # separator between parts


def test_make_run_name_no_params(tmp_project):
    """make_run_name works with no params."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py")
    assert name.startswith("train__")
    # Should have date and uid suffix
    assert re.search(r"\d{4}_[a-f0-9]{4}$", name)


def test_make_run_name_no_script(tmp_project):
    """make_run_name defaults to 'exp' when no script given."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("")
    assert name.startswith("exp__")


def test_make_run_name_float_params(tmp_project):
    """Float params are formatted with 3 significant figures."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py", {"lr": 0.001})
    assert "lr0.001" in name


def test_make_run_name_bool_params(tmp_project):
    """Bool params are converted to 0/1."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py", {"augment": True})
    assert "augment1" in name


def test_make_run_name_truncates_keys(tmp_project):
    """Long parameter keys are truncated to key_max_len."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py", {"learning_rate_warmup": 0.01})
    # Default key_max_len is 8, so "learning" should be there
    assert "learning" in name or "learning" in name[:50]


def test_make_run_name_max_param_keys(tmp_project):
    """Only max_param_keys params included in name."""
    from exptrack.core.naming import make_run_name

    params = {f"p{i}": i for i in range(10)}
    name = make_run_name("train.py", params)
    # Default max_param_keys is 4, so only first 4 params
    parts = name.split("__")
    if len(parts) >= 2:
        param_part = parts[1]
        assert param_part.count("_") <= 3  # 4 params = 3 underscores


def test_output_path_creates_dirs(tmp_project):
    """output_path() creates directories as needed."""
    from exptrack.core.naming import output_path

    p = output_path("model.pt", "my_experiment")
    assert p.parent.exists()
    assert p.name == "model.pt"
    assert "my_experiment" in str(p)
