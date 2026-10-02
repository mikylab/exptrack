"""Thread-scoped project resolution.

The dashboard serves many projects from one process, so `project_root()` has
to answer differently per thread. The failure mode that matters is silent: a
pooled thread that keeps a project bound serves the NEXT request from the
wrong database, with no error anywhere. These tests exist for that.
"""
from __future__ import annotations

import threading

from exptrack import config as cfg


def test_activate_overrides_the_cwd_walk(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_root_cache", tmp_path / "from_cwd")
    other = tmp_path / "other"
    other.mkdir()
    cfg.activate_project(other)
    try:
        assert cfg.project_root() == other
        assert cfg.active_project() == other
    finally:
        cfg.reset_project()


def test_reset_returns_to_the_previous_behaviour(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    cfg.activate_project(tmp_path / "other")
    cfg.reset_project()
    assert cfg.project_root() == tmp_path
    assert cfg.active_project() is None


def test_nothing_activated_uses_the_module_global(tmp_path, monkeypatch):
    """The 46 existing `monkeypatch.setattr(cfg, '_root_cache', ...)` call
    sites in the suite depend on this staying true."""
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    assert cfg.active_project() is None
    assert cfg.project_root() == tmp_path


def test_two_threads_see_different_projects(tmp_path, monkeypatch):
    """The core claim of the whole release."""
    monkeypatch.setattr(cfg, "_root_cache", tmp_path / "default")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    seen = {}
    barrier = threading.Barrier(2)

    def worker(name, root):
        cfg.activate_project(root)
        try:
            barrier.wait(timeout=5)      # both activated before either reads
            seen[name] = cfg.project_root()
        finally:
            cfg.reset_project()

    t1 = threading.Thread(target=worker, args=("a", a))
    t2 = threading.Thread(target=worker, args=("b", b))
    t1.start()
    t2.start()
    t1.join(5)
    t2.join(5)

    assert seen == {"a": a, "b": b}


def test_an_activation_does_not_leak_to_another_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_root_cache", tmp_path / "default")
    cfg.activate_project(tmp_path / "a")
    try:
        seen = []
        t = threading.Thread(target=lambda: seen.append(cfg.active_project()))
        t.start()
        t.join(5)
        assert seen == [None], "a thread inherited another thread's project"
    finally:
        cfg.reset_project()


def test_project_scope_restores_on_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    try:
        with cfg.project_scope(tmp_path / "a"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert cfg.active_project() is None


def test_load_is_scoped_to_the_active_project(tmp_path):
    """Config is per-project; a thread on B must not read A's config.json."""
    import json
    a, b = tmp_path / "a", tmp_path / "b"
    for d, metric in ((a, "acc_a"), (b, "acc_b")):
        (d / ".exptrack").mkdir(parents=True)
        (d / ".exptrack" / "config.json").write_text(
            json.dumps({"primary_metric": metric}), encoding="utf-8")

    with cfg.project_scope(a):
        assert cfg.load()["primary_metric"] == "acc_a"
    with cfg.project_scope(b):
        assert cfg.load()["primary_metric"] == "acc_b"


def test_save_under_an_override_does_not_touch_the_module_cache(tmp_path, monkeypatch):
    """A dashboard thread saving project B must not hand B's config to a
    cwd-resolving caller, nor leave its own thread cache stale."""
    monkeypatch.setattr(cfg, "_root_cache", tmp_path / "default")
    monkeypatch.setattr(cfg, "_cache", None)
    b = tmp_path / "b"
    (b / ".exptrack").mkdir(parents=True)

    with cfg.project_scope(b):
        conf = dict(cfg.DEFAULTS)
        conf["primary_metric"] = "acc_b"
        cfg.save(conf)
        assert cfg.load()["primary_metric"] == "acc_b"

    assert cfg._cache is None, "a bound save wrote the module-global cache"


def test_reload_under_an_override_rereads_that_project(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(cfg, "_root_cache", tmp_path / "default")
    b = tmp_path / "b"
    (b / ".exptrack").mkdir(parents=True)
    path = b / ".exptrack" / "config.json"
    path.write_text(json.dumps({"primary_metric": "first"}), encoding="utf-8")

    with cfg.project_scope(b):
        assert cfg.load()["primary_metric"] == "first"
        path.write_text(json.dumps({"primary_metric": "second"}), encoding="utf-8")
        assert cfg.reload()["primary_metric"] == "second"


def test_switching_projects_closes_the_previous_connection(tmp_path):
    """A leaked connection per switch is a descriptor leak for the life of
    the dashboard. get_db only closed on *unusable*, never on path change."""
    import sqlite3

    from exptrack.core.db import get_db

    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / ".exptrack").mkdir(parents=True)

    with cfg.project_scope(a):
        conn_a = get_db()
    with cfg.project_scope(b):
        get_db()

    # conn_a must be closed, not merely dropped from the cache.
    try:
        conn_a.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return                      # closed, as required
    raise AssertionError("the previous project's connection was left open")
