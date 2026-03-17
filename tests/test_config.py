"""Tests for exptrack/config.py — project configuration."""
import json


def test_init_creates_config(tmp_path, monkeypatch):
    """exptrack init creates .exptrack/ and config.json."""
    monkeypatch.chdir(tmp_path)
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None

    cfg.init("my-project")

    config_file = tmp_path / ".exptrack" / "config.json"
    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert data["project"] == "my-project"

    cfg._root_cache = None
    cfg._cache = None


def test_init_patches_gitignore(tmp_path, monkeypatch):
    """exptrack init adds gitignore rules."""
    monkeypatch.chdir(tmp_path)
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None

    cfg.init()

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert ".exptrack/experiments.db" in content
    assert "outputs/" in content

    cfg._root_cache = None
    cfg._cache = None


def test_load_returns_defaults(tmp_path, monkeypatch):
    """load() returns defaults when no config file exists."""
    monkeypatch.chdir(tmp_path)
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None

    conf = cfg.load()
    assert conf["db"] == ".exptrack/experiments.db"
    assert conf["outputs_dir"] == "outputs"
    assert conf["auto_capture"]["argparse"] is True

    cfg._root_cache = None
    cfg._cache = None


def test_load_merges_user_config(tmp_project):
    """load() merges user config with defaults."""
    from exptrack import config as cfg

    # Modify config
    conf = cfg.load()
    conf["max_git_diff_kb"] = 128
    cfg.save(conf)

    # Reload
    cfg._cache = None
    conf2 = cfg.load()
    assert conf2["max_git_diff_kb"] == 128
    # Defaults still present
    assert conf2["outputs_dir"] == "outputs"


def test_deep_merge():
    """_deep_merge recursively merges nested dicts."""
    from exptrack.config import _deep_merge

    base = {"a": 1, "nested": {"x": 10, "y": 20}}
    override = {"a": 2, "nested": {"y": 30, "z": 40}}
    result = _deep_merge(base, override)

    assert result["a"] == 2
    assert result["nested"]["x"] == 10
    assert result["nested"]["y"] == 30
    assert result["nested"]["z"] == 40


def test_project_root_detection(tmp_path, monkeypatch):
    """project_root() finds directory containing .git or .exptrack."""
    # Create a nested directory with .git at the top
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)

    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None

    root = cfg.project_root()
    assert root == tmp_path

    cfg._root_cache = None
    cfg._cache = None


def test_reload_clears_cache(tmp_project):
    """reload() forces re-reading config from disk."""
    from exptrack import config as cfg

    conf = cfg.load()
    conf["max_git_diff_kb"] = 999
    cfg.save(conf)

    reloaded = cfg.reload()
    assert reloaded["max_git_diff_kb"] == 999
