"""`exptrack ui` opens the dashboard in a browser, the way `jupyter lab` does.

Three rules the tests pin:

* The token never reaches a command line. `webbrowser.open(url)` spawns the
  browser with the URL as an argument, and a process's arguments are readable
  by every user on the machine (`ps`), so a tokened URL is opened through a
  0600 redirect file in `~/.exptrack/` instead — the file's path is what the
  browser is handed.
* Where there is nowhere to show a browser — over SSH, or on Linux with no
  display — nothing is opened. `webbrowser` would otherwise pick a text-mode
  browser (lynx, w3m) and take over the terminal the server is printing to.
* A failure to open is never a failure to serve: the URL is still printed.
"""
from __future__ import annotations

import sys

import pytest

from exptrack import config as cfg
from exptrack.dashboard import app as dash_app


@pytest.fixture()
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(dash_app.webbrowser, "open",
                        lambda url, *a, **k: calls.append(url) or True)
    for var in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    return calls


def test_a_tokened_url_is_opened_through_a_private_redirect_file(opened, tmp_path):
    url = "http://127.0.0.1:7331/?token=s3cret"
    assert dash_app.open_in_browser(url) is True
    assert len(opened) == 1
    assert "s3cret" not in opened[0], "the token reached the browser's command line"
    assert opened[0].startswith("file:")
    page = cfg.user_dir() / "dashboard_open.html"
    assert url in page.read_text(encoding="utf-8")
    if sys.platform != "win32":
        assert oct(page.stat().st_mode)[-3:] == "600"


def test_a_url_without_a_token_is_opened_directly(opened):
    assert dash_app.open_in_browser("http://127.0.0.1:7331/") is True
    assert opened == ["http://127.0.0.1:7331/"]


def test_nothing_is_opened_over_ssh(opened, monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 5000 10.0.0.2 22")
    assert dash_app.open_in_browser("http://127.0.0.1:7331/") is False
    assert opened == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux display rule")
def test_nothing_is_opened_on_linux_without_a_display(opened, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert dash_app.open_in_browser("http://127.0.0.1:7331/") is False
    assert opened == []


def test_a_browser_that_will_not_start_does_not_raise(monkeypatch):
    for var in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")

    def boom(*a, **k):
        raise OSError("no browser")
    monkeypatch.setattr(dash_app.webbrowser, "open", boom)
    assert dash_app.open_in_browser("http://127.0.0.1:7331/") is False


def test_a_wildcard_bind_opens_on_loopback():
    """http://0.0.0.0:7331 is not a reachable address on Windows."""
    assert dash_app.browser_url("0.0.0.0", 7331, "") == "http://127.0.0.1:7331/"
    assert dash_app.browser_url("::", 7331, "t") == "http://127.0.0.1:7331/?token=t"
    assert dash_app.browser_url("127.0.0.1", 8000, "") == "http://127.0.0.1:8000/"


def test_the_cli_flag_exists_and_defaults_to_opening():
    from exptrack.cli.main import _build_parser
    p = _build_parser()
    assert p.parse_args(["ui"]).no_browser is False
    assert p.parse_args(["ui", "--no-browser"]).no_browser is True
    assert p.parse_args(["ui", "start", "--no-browser"]).no_browser is True
