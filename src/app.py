"""
Bare-minimum web server for the "import player's dataset" story.

    python src/app.py        then open http://127.0.0.1:5001

GET  /         -> upload.html (drop a .csv/.xlsx file)
POST /upload   -> runs processInput.process_file on it, answers with JSON
GET  /players  -> first few loaded players, just to prove the data is in Postgres

Xavier can restyle upload.html or move the form into the real front end. The only
contract is: POST the file to /upload as form field "file", read back the JSON.
"""

import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from processInput import SUPPORTED_EXTENSIONS, get_connection, process_file

HERE = Path(__file__).parent

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB. Master.xlsx is about 90 KB.


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


@app.errorhandler(413)
def too_big(_error):
    return jsonify(ok=False, message="File is too big (5 MB max).", warnings=[]), 413


if __name__ == "__main__":
    # Not Flask's default 5000: on newer Macs, AirPlay Receiver already listens on 5000.
    # Debug mode is off unless FLASK_DEBUG=1. Its in-browser debugger can run any Python code,
    # so it should never be on by accident (for example on a hosted server).
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001)
