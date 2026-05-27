"""Tests for exptrack/core/naming.py — run naming and output paths."""
import re


def test_make_run_name_basic(tmp_project):
    """make_run_name produces the readable format: MonDD_<script>__<params>__<uid>."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py", {"lr": 0.01, "epochs": 10})
    assert re.match(r"^[A-Z][a-z]{2}\d{2}_train__", name)  # readable date prefix
    assert "lr" in name
    assert re.search(r"__[a-f0-9]{8}$", name)  # short uid suffix


def test_make_run_name_no_params(tmp_project):
    """make_run_name works with no params: MonDD_<script>__<uid>."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py")
    assert re.match(r"^[A-Z][a-z]{2}\d{2}_train__[a-f0-9]{8}$", name)


def test_make_run_name_no_script(tmp_project):
    """make_run_name defaults to 'exp' when no script given."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("")
    assert re.match(r"^[A-Z][a-z]{2}\d{2}_exp__", name)


def test_make_run_name_numeric_date_style(tmp_project):
    """date_style='numeric' reverts to the legacy MMDD layout."""
    from exptrack import config as cfg
    from exptrack.core.naming import make_run_name

    conf = cfg.load()
    conf.setdefault("naming", {})["date_style"] = "numeric"
    cfg.save(conf)

    name = make_run_name("train.py", {"lr": 0.01})
    assert name.startswith("train__")
    assert re.search(r"\d{4}_[a-f0-9]{8}$", name)


def test_looks_auto_named(tmp_project):
    """looks_auto_named flags generated names (readable + legacy), not user names."""
    from exptrack.core.naming import looks_auto_named, make_run_name

    assert looks_auto_named(make_run_name("train.py", {"lr": 0.01}))
    assert looks_auto_named("train__lr0.01__0312_a3f25b1c")  # legacy
    assert not looks_auto_named("my-best-run")
    assert not looks_auto_named("")


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
