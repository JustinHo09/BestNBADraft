"""
Bare-minimum web server for the "import player's dataset" story.

    python src/app.py        then open http://127.0.0.1:5001

GET  /                  -> upload.html (drop a .csv/.xlsx file)
POST /upload            -> runs processInput.process_file on it, answers with JSON
GET  /players           -> first few loaded players, just to prove the data is in Postgres
POST /players/<id>/lock -> lock a player once he's drafted (409 if already taken)

Xavier can restyle upload.html or move the form into the real front end. The only
contract is: POST the file to /upload as form field "file", read back the JSON.
"""

import os
import tempfile
from pathlib import Path

from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import FlaskSessionChacheHandler

import psycopg
from flask import Flask, jsonify, request, send_from_directory,redirect, session, url_for
from werkzeug.utils import secure_filename

from draft import PlayerAlreadyLockedError, PlayerNotFoundError, lock_player
from processInput import SUPPORTED_EXTENSIONS, get_connection, process_file

HERE = Path(__file__).parent

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB. Master.xlsx is about 90 KB.\

#remember to make secret key a fixed string and stored safely
app.config['Secret_Key'] = os.urandom(64)

#store these in a safer location later
client_id = 'ce8e48cc4fa34b7983e63f7daa1fed8e'
client_secret = '3f4bd4c2bf6d455ea0f72fe6000a1579'
redirect_uri = 'http://127.0.0.1:5001'
scope = 'playlist-read-private,stream'

chache_handler = FlaskSessionChacheHandler(session)
sp_oauth = SpotifyOAuth(
    client_id = client_id,
    client_secret = client_secret,
    redirect_uri = redirect_uri,
    scope = scope,
    cache_handler = chache_handler,
    show_dialog = True
)

sp = Spotify(auth_manager = sp_oauth)


@app.get("/")
def upload_page():
    return send_from_directory(HERE, "upload.html")


@app.post("/upload")
def upload():
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify(ok=False, message="No file was chosen.", warnings=[]), 400

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return jsonify(ok=False, message="Must be a .csv or .xlsx file.", warnings=[]), 400

    # Save to a temp folder that gets deleted right after, then reuse the same code the CLI uses.
    # secure_filename strips things like "../" so a weird file name can't write outside the temp folder.
    with tempfile.TemporaryDirectory() as tmp:
        saved = Path(tmp) / f"{secure_filename(Path(file.filename).stem) or 'upload'}{suffix}"
        file.save(saved)
        result = process_file(saved)

    return jsonify(result), (200 if result["ok"] else 400)


@app.get("/players")
def players():
    try:
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
            rows = conn.execute(
                "SELECT p.id, p.name, s.team, s.position, s.salary "
                "FROM players p JOIN stats s ON s.id = p.id ORDER BY p.id LIMIT 10"
            ).fetchall()
        return jsonify(ok=True, total_players=total, first_10=[
            {"id": r[0], "name": r[1], "team": r[2], "position": r[3], "salary": r[4]} for r in rows
        ])
    except Exception as e:  # tables not created yet, DB down, etc.
        return jsonify(ok=False, message=f"Couldn't read players: {type(e).__name__}"), 500


@app.post("/players/<int:player_id>/lock")
def lock(player_id):
    try:
        with get_connection() as conn:
            lock_player(conn, player_id)
    except PlayerNotFoundError as e:
        return jsonify(ok=False, message=str(e)), 404
    except PlayerAlreadyLockedError as e:
        return jsonify(ok=False, message=str(e)), 409
    except psycopg.Error as e:
        return jsonify(ok=False, message=f"Database error, player not locked: {type(e).__name__}"), 500
    return jsonify(ok=True, message=f"Player {player_id} is locked.")


@app.errorhandler(413)
def too_big(_error):
    return jsonify(ok=False, message="File is too big (5 MB max).", warnings=[]), 413

@app.route('/')
def home():
    if not sp_oauth.validate_token(chache_handler.get_cached_token()):
        auth_url = sp_oauth.get_authorize_url()
        return redirect(auth_url)
    return redirect(url_for('get_playlists'))

@app.route('/callback')
def callback():
    sp_oauth.getaccess_token(request.args['code'])
    return redirect(url_for('get_playlists'))

@app.route('/get_playlists')
def get_playlists():
    if not sp_oauth.validate_token(chache_handler.get_cached_token()):
        auth_url = sp_oauth.get_authorize_url()
        return redirect(auth_url)

    playlists = sp.current_user_playlists()
    playlists_info = [(pl['name'], pl['external_urls']['spotify']) for pl in playlists['items']]
    playlists_html = '<br>'.join([f'{name}: {url}' for name, url in playlists_info])

    return playlists_html

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


if __name__ == "__main__":
    # Not Flask's default 5000: on newer Macs, AirPlay Receiver already listens on 5000.
    # Debug mode is off unless FLASK_DEBUG=1. Its in-browser debugger can run any Python code,
    # so it should never be on by accident (for example on a hosted server).
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001)
    app.run(debug=True)