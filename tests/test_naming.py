"""Tests for exptrack/core/naming.py — run naming and output paths."""
import re


def test_make_run_name_basic(tmp_project):
    """make_run_name produces <script>__<params>__<uid> — no date by default.

    Every run records when it started; a date in the name made a one-day sweep
    a column of identical `Oct01_` prefixes ahead of the part that differed.
    """
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py", {"lr": 0.01, "epochs": 10})
    assert name.startswith("train__lr0.01")
    assert re.search(r"__[a-f0-9]{8}$", name)  # short uid suffix


def test_make_run_name_no_params(tmp_project):
    """make_run_name works with no params: <script>__<uid>."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py")
    assert re.match(r"^train__[a-f0-9]{8}$", name)


def test_make_run_name_no_script(tmp_project):
    """make_run_name defaults to 'exp' when no script given."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("")
    assert name.startswith("exp__")


def test_make_run_name_readable_date_style(tmp_project):
    """date_style='readable' puts the MonDD_ prefix back."""
    from exptrack import config as cfg
    from exptrack.core.naming import make_run_name

    conf = cfg.load()
    conf.setdefault("naming", {})["date_style"] = "readable"
    cfg.save(conf)

    name = make_run_name("train.py", {"lr": 0.01})
    assert re.match(r"^[A-Z][a-z]{2}\d{2}_train__lr0.01__[a-f0-9]{8}$", name)


def test_make_run_name_unknown_date_style_degrades_to_no_date(tmp_project):
    """A hand-edited value that means nothing is the default, not a crash."""
    from exptrack import config as cfg
    from exptrack.core.naming import make_run_name

    conf = cfg.load()
    conf.setdefault("naming", {})["date_style"] = "fancy"
    cfg.save(conf)

    assert make_run_name("train.py", {"lr": 0.01}).startswith("train__lr0.01")


def test_multi_word_keys_shorten_to_initials(tmp_project):
    """`batch_size` is `bs`, not `batch_si` — the cut that made a sweep's names
    read `batch_si128_weight_d0`."""
    from exptrack.core.naming import make_run_name

    name = make_run_name("train.py", {"lr": 0.001, "batch_size": 128,
                                      "weight_decay": 0.0001, "dropout": 0.3})
    assert name.startswith("train__lr0.001_bs128_wd0.0001_dropout0.3__")


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
    """A long single-word key is truncated to key_max_len; a long multi-word
    key becomes its initials."""
    from exptrack.core.naming import make_run_name

    assert "regulari0.01" in make_run_name("train.py", {"regularization": 0.01})
    assert "lrw0.01" in make_run_name("train.py", {"learning_rate_warmup": 0.01})


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
