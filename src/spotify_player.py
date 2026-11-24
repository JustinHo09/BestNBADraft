import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from flask  import Blueprint, jsonify, redirect, request, send_from_directory, session

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads a .env file next to your app if python-dotenv is installed
except ImportError:
    pass

HERE = Path(__file__).parent

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET") # Must match a Redirect URI saved in your Spotify dashboard EXACTLY.
REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5001/auth/callback")

SCOPE = "streaming user-read-email user-read-private"

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

spotify_bp = Blueprint("spotify", __name__)

def _save_tokens(body, fallback_refresh_token=None):
    """Store Spotify's token response in the user's session."""
    session["spotify_access_token"] = body["access_token"]
    # A refresh response doesn't always include a new refresh token; keep the old one then.
    session["spotify_refresh_token"] = body.get("refresh_token") or fallback_refresh_token
    session["spotify_expires_at"] = time.time() + body.get("expires_in", 3600)

    @spotify_bp.get("/player")
    def player_page():
        return send_from_directory(HERE, "player.html")

    @spotify_bp.get("/auth/login")
    def login():
        if not CLIENT_ID or not CLIENT_SECRET:
            return "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET before starting the app.", 500

        # "state" protects against cross-site request forgery: we check it comes back unchanged.
        state = secrets.token_urlsafe(16)
        session["spotify_state"] = state

        params = urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "redirect_uri": REDIRECT_URI,
            "state": state,
        })
        return redirect(f"{AUTH_URL}?{params}")

    @spotify_bp.get("/auth/callback")
    def callback():
        if request.args.get("error"):
            return f"Spotify login was cancelled or failed: {request.args['error']}", 400

        expected_state = session.pop("spotify_state", None)
        if not expected_state or request.args.get("state") != expected_state:
            return "Login check failed (state mismatch). Go back and try logging in again.", 400

        code = request.args.get("code")
        if not code:
            return "Spotify didn't send a login code.", 400

        try:
            resp = requests.post(
                TOKEN_URL,
                data = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
                auth = (CLIENT_ID, CLIENT_SECRET),  # sends the Basic base64(client_id:client_secret) header
                timeout=10,
            )
            resp.raise_for_status()
            _save_tokens(resp.json())
        except requests.RequestException as e:
            return f"Couldn't get a token from Spotify: {type(e).__name__}", 502

        return redirect("/player")

    @spotify_bp.get("/auth/token")
    def token():
        """Give the browser a valid access token, refreshing it first if it's about to expire."""
        access_token = session.get("spotify_access_token")
        if not access_token:
            return jsonify(ok = False, message="Not logged in to Spotify."), 401

        if time.time() > session.get("spotify_expires_at", 0) - 60:
            refresh_token = session.get("spotify_refresh_token")
            if not refresh_token:
                session.clear()
                return jsonify(ok=False, message="Spotify session expired. Log in again."), 401
            try:
                resp = requests.post(
                    TOKEN_URL,
                    data = {"grant_type": "refresh_token", "refresh_token": refresh_token},
                    auth = (CLIENT_ID, CLIENT_SECRET),
                    timeout=10,
                )
                resp.raise_for_status()
                _save_tokens(resp.json(), fallback_refresh_token=refresh_token)
            except requests.RequestException:
                return jsonify(ok=False, message = "Couldn't refresh the Spotify token."), 502
            access_token = session["spotify_access_token"]

        return jsonify(ok=True, access_token=access_token)
