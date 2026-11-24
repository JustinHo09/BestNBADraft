"""Tests for spotify_player.py (login, callback, and token routes).

Run from the project folder with:  pytest -v

Spotify itself is never contacted: requests.post is replaced with a fake, and the
client ID, secret, and redirect URI are set by the tests, so no .env file is needed.
"""

import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from flask import Flask

import spotify_player

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "http://127.0.0.1:5001/auth/callback"
TOKEN_URL = "https://accounts.spotify.com/api/token"


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload if payload is not None else {}
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")

    def json(self):
        return self.payload


class FakeSpotifyApi:
    """Records every request our code makes to Spotify and replies with a canned answer."""

    def __init__(self):
        self.calls = []
        self.response = FakeResponse(
            {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
        )
        self.error = None   # set to an exception to simulate Spotify being unreachable

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture(autouse=True)
def spotify_config(monkeypatch):
    monkeypatch.setattr(spotify_player, "CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(spotify_player, "CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setattr(spotify_player, "REDIRECT_URI", REDIRECT_URI)


@pytest.fixture
def api(monkeypatch):
    fake = FakeSpotifyApi()
    monkeypatch.setattr(spotify_player.requests, "post", fake.post)
    return fake


@pytest.fixture
def client():
    app = Flask(__name__)
    app.secret_key = "test-secret-key"
    app.config["TESTING"] = True
    app.register_blueprint(spotify_player.spotify_bp)
    return app.test_client()


def start_login(client):
    """Hit /auth/login and return (response, the query parameters it sent to Spotify)."""
    resp = client.get("/auth/login")
    query = parse_qs(urlparse(resp.headers["Location"]).query)
    return resp, query


def log_in(client):
    """Run the whole login + callback flow so the session holds Spotify tokens."""
    _, query = start_login(client)
    client.get(f"/auth/callback?code=abc&state={query['state'][0]}")


def set_tokens(client, access="access-1", refresh="refresh-1", expires_in=3600):
    """Put tokens straight into the session. A negative expires_in means already expired."""
    with client.session_transaction() as sess:
        sess["spotify_access_token"] = access
        sess["spotify_expires_at"] = time.time() + expires_in
        if refresh is not None:
            sess["spotify_refresh_token"] = refresh


# ---------------------------------------------------------------- /auth/login


class TestLogin:
    def test_redirects_to_spotify_with_the_right_parameters(self, client):
        resp, query = start_login(client)
        target = urlparse(resp.headers["Location"])

        assert resp.status_code == 302
        assert target.netloc == "accounts.spotify.com"
        assert target.path == "/authorize"
        assert query["response_type"] == ["code"]
        assert query["client_id"] == [CLIENT_ID]
        assert query["redirect_uri"] == [REDIRECT_URI]

    def test_requests_the_scopes_the_web_player_needs(self, client):
        _, query = start_login(client)
        scopes = query["scope"][0].split()
        for needed in ("streaming", "user-read-email", "user-read-private"):
            assert needed in scopes

    def test_state_is_saved_in_the_session(self, client):
        _, query = start_login(client)
        with client.session_transaction() as sess:
            assert sess["spotify_state"] == query["state"][0]
        assert len(query["state"][0]) >= 16

    def test_every_login_gets_a_different_state(self, client):
        _, first = start_login(client)
        _, second = start_login(client)
        assert first["state"] != second["state"]

    def test_client_secret_never_appears_in_the_redirect(self, client):
        resp, _ = start_login(client)
        assert CLIENT_SECRET not in resp.headers["Location"]

    def test_missing_credentials_gives_a_clear_error(self, client, monkeypatch):
        monkeypatch.setattr(spotify_player, "CLIENT_SECRET", None)
        resp = client.get("/auth/login")
        assert resp.status_code == 500
        assert b"SPOTIFY_CLIENT_ID" in resp.data


# ---------------------------------------------------------------- /auth/callback


class TestCallback:
    def test_success_exchanges_code_and_redirects_to_player(self, client, api):
        _, query = start_login(client)
        resp = client.get(f"/auth/callback?code=abc&state={query['state'][0]}")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/player")

        assert len(api.calls) == 1
        call = api.calls[0]
        assert call["url"] == TOKEN_URL
        assert call["data"] == {
            "grant_type": "authorization_code",
            "code": "abc",
            "redirect_uri": REDIRECT_URI,
        }
        assert call["auth"] == (CLIENT_ID, CLIENT_SECRET)

    def test_success_stores_tokens_in_the_session(self, client, api):
        log_in(client)
        with client.session_transaction() as sess:
            assert sess["spotify_access_token"] == "access-1"
            assert sess["spotify_refresh_token"] == "refresh-1"
            assert sess["spotify_expires_at"] > time.time()

    def test_state_can_only_be_used_once(self, client, api):
        _, query = start_login(client)
        url = f"/auth/callback?code=abc&state={query['state'][0]}"
        assert client.get(url).status_code == 302
        assert client.get(url).status_code == 400   # replaying the same callback fails

    def test_wrong_state_is_rejected_without_calling_spotify(self, client, api):
        start_login(client)
        resp = client.get("/auth/callback?code=abc&state=not-the-real-state")
        assert resp.status_code == 400
        assert api.calls == []

    def test_callback_without_starting_login_is_rejected(self, client, api):
        resp = client.get("/auth/callback?code=abc&state=anything")
        assert resp.status_code == 400
        assert api.calls == []

    def test_missing_code_is_rejected(self, client, api):
        _, query = start_login(client)
        resp = client.get(f"/auth/callback?state={query['state'][0]}")
        assert resp.status_code == 400
        assert api.calls == []

    def test_user_cancelling_on_spotify_is_handled(self, client, api):
        start_login(client)
        resp = client.get("/auth/callback?error=access_denied")
        assert resp.status_code == 400
        assert api.calls == []

    def test_spotify_unreachable_gives_502_and_stores_nothing(self, client, api):
        api.error = requests.ConnectionError("network down")
        _, query = start_login(client)
        resp = client.get(f"/auth/callback?code=abc&state={query['state'][0]}")

        assert resp.status_code == 502
        assert CLIENT_SECRET not in resp.get_data(as_text=True)
        with client.session_transaction() as sess:
            assert "spotify_access_token" not in sess

    def test_spotify_rejecting_the_code_gives_502(self, client, api):
        api.response = FakeResponse({"error": "invalid_grant"}, status=400)
        _, query = start_login(client)
        resp = client.get(f"/auth/callback?code=expired&state={query['state'][0]}")
        assert resp.status_code == 502


# ---------------------------------------------------------------- /auth/token


class TestToken:
    def test_not_logged_in_returns_401(self, client, api):
        resp = client.get("/auth/token")
        assert resp.status_code == 401
        assert resp.get_json()["ok"] is False
        assert api.calls == []

    def test_valid_token_is_returned_without_contacting_spotify(self, client, api):
        set_tokens(client, access="access-1", expires_in=1800)
        resp = client.get("/auth/token")

        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True, "access_token": "access-1"}
        assert api.calls == []

    def test_response_never_leaks_the_refresh_token_or_secret(self, client, api):
        set_tokens(client, expires_in=1800)
        body = client.get("/auth/token").get_data(as_text=True)
        assert "refresh-1" not in body
        assert CLIENT_SECRET not in body

    def test_expired_token_is_refreshed(self, client, api):
        api.response = FakeResponse({"access_token": "access-2", "expires_in": 3600})
        set_tokens(client, access="access-1", refresh="refresh-1", expires_in=-10)

        resp = client.get("/auth/token")

        assert resp.status_code == 200
        assert resp.get_json()["access_token"] == "access-2"
        assert len(api.calls) == 1
        assert api.calls[0]["url"] == TOKEN_URL
        assert api.calls[0]["data"] == {"grant_type": "refresh_token", "refresh_token": "refresh-1"}
        assert api.calls[0]["auth"] == (CLIENT_ID, CLIENT_SECRET)

    def test_token_about_to_expire_is_refreshed_early(self, client, api):
        api.response = FakeResponse({"access_token": "access-2", "expires_in": 3600})
        set_tokens(client, expires_in=30)    # still valid, but inside the 60-second safety margin

        resp = client.get("/auth/token")
        assert resp.get_json()["access_token"] == "access-2"
        assert len(api.calls) == 1

    def test_old_refresh_token_is_kept_when_spotify_sends_no_new_one(self, client, api):
        api.response = FakeResponse({"access_token": "access-2", "expires_in": 3600})
        set_tokens(client, refresh="refresh-1", expires_in=-10)
        client.get("/auth/token")

        with client.session_transaction() as sess:
            assert sess["spotify_refresh_token"] == "refresh-1"
            assert sess["spotify_access_token"] == "access-2"

    def test_new_refresh_token_replaces_the_old_one(self, client, api):
        api.response = FakeResponse(
            {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 3600}
        )
        set_tokens(client, refresh="refresh-1", expires_in=-10)
        client.get("/auth/token")

        with client.session_transaction() as sess:
            assert sess["spotify_refresh_token"] == "refresh-2"

    def test_refreshed_token_is_reused_on_the_next_call(self, client, api):
        api.response = FakeResponse({"access_token": "access-2", "expires_in": 3600})
        set_tokens(client, expires_in=-10)
        client.get("/auth/token")
        second = client.get("/auth/token")

        assert second.get_json()["access_token"] == "access-2"
        assert len(api.calls) == 1           # no second refresh

    def test_expired_with_no_refresh_token_asks_to_log_in_again(self, client, api):
        set_tokens(client, refresh=None, expires_in=-10)
        resp = client.get("/auth/token")

        assert resp.status_code == 401
        assert api.calls == []
        with client.session_transaction() as sess:
            assert "spotify_access_token" not in sess

    def test_refresh_failing_because_spotify_is_unreachable_gives_502(self, client, api):
        api.error = requests.ConnectionError("network down")
        set_tokens(client, expires_in=-10)
        resp = client.get("/auth/token")
        assert resp.status_code == 502
        assert resp.get_json()["ok"] is False

    def test_refresh_rejected_by_spotify_gives_502(self, client, api):
        api.response = FakeResponse({"error": "invalid_grant"}, status=400)
        set_tokens(client, expires_in=-10)
        assert client.get("/auth/token").status_code == 502


# ---------------------------------------------------------------- /player


class TestPlayerPage:
    def test_player_page_is_served(self, client):
        resp = client.get("/player")
        try:
            assert resp.status_code == 200
            assert b"Spotify" in resp.data
        finally:
            resp.close()