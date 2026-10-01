"""Dashboard authentication — token persistence and the CSRF invariant.

The dashboard authenticates with an Authorization: Bearer header and nothing
else. That is *why* it is immune to cross-site request forgery: a hostile page
cannot set that header cross-origin and cannot read the token out of
localStorage, so a forged request arrives with no credential.

A signed-cookie design was drafted for this release and rejected, because a
cookie is attached by the browser automatically — including on requests a
hostile page triggers — and the problem it was solving (staying logged in
across a restart) was already solved by persisting the token. The last two
tests here are the executable form of that decision.
"""
from __future__ import annotations

import sys

import pytest

from exptrack import config as cfg
from exptrack.dashboard import app as dash_app
from exptrack.dashboard import handler as dash_handler


@pytest.fixture(autouse=True)
def _reset_session_token():
    """Clear the module-level session token between tests."""
    dash_handler.set_session_token("")
    dash_handler.set_auth_disabled(False)
    yield
    dash_handler.set_session_token("")
    dash_handler.set_auth_disabled(False)


def test_generated_token_is_persisted(tmp_project):
    token = dash_app.resolve_startup_token(no_auth=False)
    assert token
    assert cfg.token_file_path().is_file()
    assert cfg.token_file_path().read_text().strip() == token


def test_restart_reuses_the_same_token(tmp_project):
    """The actual complaint: a restart must not invalidate the open tab."""
    first = dash_app.resolve_startup_token(no_auth=False)
    dash_handler.set_session_token("")
    second = dash_app.resolve_startup_token(no_auth=False)
    assert second == first


def test_existing_token_is_never_overwritten(tmp_project):
    cfg.write_token("chosen-by-the-user")
    token = dash_app.resolve_startup_token(no_auth=False)
    assert token == "chosen-by-the-user"


def test_env_var_wins_and_is_not_persisted(tmp_project, monkeypatch):
    monkeypatch.setenv("EXPTRACK_DASHBOARD_TOKEN", "from-env")
    token = dash_app.resolve_startup_token(no_auth=False)
    assert token == "from-env"
    assert not cfg.token_file_path().is_file()


def test_no_auth_generates_nothing(tmp_project):
    assert dash_app.resolve_startup_token(no_auth=True) == ""
    assert not cfg.token_file_path().is_file()


def test_no_auth_serves_without_a_token_even_when_one_is_saved(live_server_with_token):
    """--no-auth used to only skip *generating* a token: the handler still read
    .exptrack/dashboard_token on every request, so any project that had ever
    run the dashboard with auth 401'd every request and the page showed the
    login overlay under a banner that said auth was disabled."""
    import urllib.request
    base, _token = live_server_with_token
    assert dash_app.resolve_startup_token(no_auth=True) == ""
    with urllib.request.urlopen(base + "/api/stats", timeout=5) as resp:
        assert resp.status == 200
    # The saved token is ignored, not removed: the next start with auth uses it.
    assert cfg.token_file_path().is_file()


def test_starting_with_auth_turns_it_back_on(live_server_with_token):
    import urllib.error
    import urllib.request
    base, token = live_server_with_token
    dash_app.resolve_startup_token(no_auth=True)
    assert dash_app.resolve_startup_token(no_auth=False) == token
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(base + "/api/stats", timeout=5)
    assert exc.value.code == 401


def test_token_is_long_enough_to_resist_guessing(tmp_project):
    """Loopback is shared by every user on the machine, so the token is the
    control. secrets.token_urlsafe(32) is 256 bits."""
    token = dash_app.resolve_startup_token(no_auth=False)
    assert len(token) >= 40


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes are inert on Windows")
def test_persisted_token_is_private(tmp_project):
    dash_app.resolve_startup_token(no_auth=False)
    assert oct(cfg.token_file_path().stat().st_mode)[-3:] == "600"


def test_no_endpoint_sets_a_cookie(live_server_with_token):
    """CSRF invariant: no response may carry Set-Cookie."""
    base, token = live_server_with_token
    import urllib.request
    req = urllib.request.Request(base + "/api/stats",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.headers.get("Set-Cookie") is None


def test_a_cookie_does_not_authenticate(live_server_with_token):
    """CSRF invariant: a credential the browser attaches by itself is not
    accepted. This fails the moment anyone reintroduces cookie auth."""
    import urllib.error
    import urllib.request
    base, token = live_server_with_token
    req = urllib.request.Request(base + "/api/stats",
                                 headers={"Cookie": f"exptrack_auth={token}"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 401


def test_non_loopback_bind_warns_even_with_auth(tmp_project, capsys):
    """Accidentally binding 0.0.0.0 is a far more realistic exposure than any
    attack on the token, and used to warn only under --no-auth."""
    dash_app.warn_if_exposed(host="0.0.0.0", no_auth=False)
    err = capsys.readouterr().err
    assert "0.0.0.0" in err
    assert "network" in err.lower()


def test_loopback_bind_is_silent(tmp_project, capsys):
    dash_app.warn_if_exposed(host="127.0.0.1", no_auth=False)
    assert capsys.readouterr().err == ""
