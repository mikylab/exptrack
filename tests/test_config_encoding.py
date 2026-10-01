"""Encoding correctness for config.py's text file I/O.

Runs on every platform, unlike tests/test_dashboard_perms.py which skips on
Windows for POSIX-mode reasons unrelated to this bug.
"""
from __future__ import annotations

import locale

from exptrack import config as cfg


def test_gitignore_round_trips_em_dash(tmp_path, monkeypatch):
    """Windows regression: ensure_gitignore_rules() used to open .gitignore
    with no explicit encoding, so on Windows Python fell back to the system
    ANSI codepage and the em-dash in GITIGNORE_RULES[0] came out as mojibake.
    Reading the written file back as UTF-8 must reproduce it exactly.
    """
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    cfg.ensure_gitignore_rules()
    gitignore = tmp_path / ".gitignore"
    text = gitignore.read_text(encoding="utf-8")
    assert cfg.GITIGNORE_RULES[0] in text
    assert "—" in cfg.GITIGNORE_RULES[0]  # sanity: the rule really has an em-dash


def test_ensure_gitignore_rules_survives_non_utf8_gitignore(tmp_path, monkeypatch):
    """Every Windows user who ever ran `exptrack init` before the writer-side
    fix (test_gitignore_round_trips_em_dash's regression) has a .gitignore
    containing mojibake bytes from the em-dash written in the system ANSI
    codepage. ensure_gitignore_rules() used strict encoding="utf-8" to *read*
    that file back — a UnicodeDecodeError raised uncaught, which took down
    config.init(), write_token() (so `ui --token` and the first dashboard
    start), and daemon.write_state/spawn_detached (both call this on every
    start). The read is only ever used for a substring membership test, so a
    lossy decode is correct and must never raise.
    """
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    gitignore = tmp_path / ".gitignore"
    # The exact mojibake the pre-fix Windows bug used to write: an em-dash
    # encoded as cp1252's 0x97, which is not valid UTF-8 on its own.
    gitignore.write_bytes(b"# exptrack \x97 local only (db + snapshots)\n")

    added = cfg.ensure_gitignore_rules()

    assert added is True
    text = gitignore.read_text(encoding="utf-8", errors="replace")
    for rule in cfg.GITIGNORE_RULES[1:]:
        assert rule in text


def test_load_falls_back_to_locale_encoding_for_legacy_config(tmp_path, monkeypatch, capsys):
    """A hand-edited config.json containing non-ASCII, saved in the OS locale
    encoding (e.g. cp1252 on a Windows box), used to read back fine under the
    old locale-default read_text(). Switching load() to encoding="utf-8" made
    such a file raise UnicodeDecodeError, which the outer except caught and
    silently dropped every setting to DEFAULTS — primary_metric,
    metric_aliases, reference_run, custom paths, all gone with only a stderr
    line nobody watches on a detached dashboard. load() must instead retry
    with the locale's preferred encoding before giving up, and say so.

    locale.getpreferredencoding() is pinned to cp1252 here (rather than used
    as-is) so this test exercises the fallback branch — and therefore proves
    something — on every platform, including ones whose real locale is
    already UTF-8, where the un-pinned encoding would round-trip on the first
    try and never reach the branch under test.
    """
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    monkeypatch.setattr(cfg, "_cache", None)
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "cp1252")
    exptrack_dir = tmp_path / ".exptrack"
    exptrack_dir.mkdir()
    # cp1252's 0x92 (curly apostrophe) is outside ASCII and, decoded as
    # UTF-8, is an invalid continuation byte — exactly the failure mode
    # under test.
    payload = '{"primary_metric": "acc’"}'
    (exptrack_dir / "config.json").write_bytes(payload.encode("cp1252"))

    loaded = cfg.load()

    assert loaded["primary_metric"] == "acc’"
    err = capsys.readouterr().err
    assert "cp1252" in err
    cfg._cache = None
