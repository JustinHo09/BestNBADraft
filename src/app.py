"""
Bare-minimum web server for the "import player's dataset" story.

    python src/app.py        then open http://127.0.0.1:5001

GET  /                  -> upload.html (drop a .csv/.xlsx file)
POST /upload            -> runs processInput.process_file on it, answers with JSON


Xavier can restyle upload.html or move the form into the real front end. The only
necessity is: POST the file to /upload as form field "file", read back the JSON.
"""

# routes added for the draft board (the /api/draft ones send back the whole board as "draft")
# GET  /draft                    the draft board (draft.html)
# GET  /api/players              every player as name, position and team (no IDs) for the upload page
# GET  /api/draft                the board: teams, picks, who's on the clock
# POST /api/draft/new            {"group_names": [3 to 5 names], "salary_cap": 110000000}
# POST /api/draft/pick           {"player_id": 13070} for whoever is on the clock
# POST /api/draft/next           next turn (only after a pick)
# POST /api/draft/undo           takes back the last pick (even if Next turn wasn't hit yit)
# GET  /api/players/available    undrafted players with no names since it's a blind draft
# picks show as "Pick locked in" until every team has picked that round (see hide_current_round)

import os
import tempfile
from pathlib import Path

import psycopg
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from draft import (
    GameOverError,
    NoDraftError,
    NoPickError,
    NoSalaryError,
    OverBudgetError,
    PickAlreadyMadeError,
    PlayerAlreadyLockedError,
    PlayerNotFoundError,
    continue_turn,
    get_available_players,
    get_draft_data,
    make_pick,
    new_draft,
    set_up_draft,
    undo
)
from processInput import SUPPORTED_EXTENSIONS, get_connection, loaded_players, process_file

HERE = Path(__file__).parent

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB. Master.xlsx is about 90 KB.

#


@app.get("/")
def upload_page():
    return send_from_directory(HERE, "upload.html")


@app.get("/draft")
def draft_page():
    return send_from_directory(HERE, "draft.html")


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

@app.get("/api/players")
def all_players():
    try:
        with get_connection() as conn:
            if _count_players(conn) == 0:
                return jsonify(ok=True, total=0, players=[])
            found = loaded_players(conn)
        return jsonify(ok=True, total=len(found), players=found)
    except psycopg.Error as e:
        return jsonify(ok=False, total=0, players=[], message=f"Couldn't load players: {type(e).__name__}"), 500


# which status code each of Justin's draft errors sends back
DRAFT_ERRORS = {
    PlayerNotFoundError: 404,
    PlayerAlreadyLockedError: 409,
    PickAlreadyMadeError: 409,
    NoPickError: 409,
    GameOverError: 409,
    NoDraftError: 409,
    NoSalaryError: 422,
    OverBudgetError: 422,
    ValueError: 400,
}

FRIENDLY = {
    GameOverError: "The draft is over. Every round is filled.",
    NoPickError: "Make a pick before moving to the next turn.",
    PickAlreadyMadeError: "This turn already has a pick. Hit Next turn.",
    NoSalaryError: "That player has no salary in the file, so he can't be drafted.",
    OverBudgetError: "That player costs more than this team has left under the cap.",
}


# Justin's idea: don't show who got picked until every team has picked that round
# a pick shows once the draft is past that round, or once the draft is over
# doing it here and not in the html so the names don't get sent to the browser early
# (otherwise anyone could see them in the network tab, or on the projector/phones)
def hide_current_round(draft):
    drafted = 0
    for pick in draft["picks"]:
        if draft["is_over"] or pick["round"] < draft["round"]:
            pick["revealed"] = True
            drafted = drafted + 1
        else:
            pick["revealed"] = False
            pick["name"] = None
            pick["position"] = None
            pick["team"] = None
            pick["salary"] = None
            pick["player_id"] = None
    draft["drafted"] = drafted  # for the "Round 1 is done, 3 players drafted" line
    return draft


# runs one draft step and always sends back JSON
# everything is one transaction, so if something fails the whole step gets undone
def draft_action(action):
    try:
        with get_connection() as conn:
            extra = action(conn) or {}
            return jsonify(ok=True, draft=hide_current_round(get_draft_data(conn)), **extra)
    except tuple(DRAFT_ERRORS) as e:
        status = next(code for cls, code in DRAFT_ERRORS.items() if isinstance(e, cls))
        message = FRIENDLY.get(type(e)) or str(e) or type(e).__name__
        return jsonify(ok=False, message=message), status
    except psycopg.errors.UndefinedTable:
        return jsonify(ok=False, message="No players loaded yet. Import a player file first."), 409
    except psycopg.Error as e:
        return jsonify(ok=False, message=f"Database error, nothing was saved: {type(e).__name__}"), 500


@app.get("/api/draft")
def draft_state():
    try:
        with get_connection() as conn:
            players = _count_players(conn)
            started = conn.execute("SELECT to_regclass('current_state')").fetchone()[0] is not None \
                and conn.execute("SELECT COUNT(*) FROM current_state").fetchone()[0] == 1
            draft = hide_current_round(get_draft_data(conn)) if started else None
        return jsonify(ok=True, started=started, players_loaded=players, draft=draft)
    except psycopg.Error as e:
        return jsonify(ok=False, message=f"Couldn't reach the database: {type(e).__name__}"), 500


@app.post("/api/draft/new")
def draft_new():
    body = request.get_json(silent=True) or {}
    names = [str(n).strip() for n in body.get("group_names", []) if str(n).strip()]
    try:
        cap = int(body.get("salary_cap", 0))
    except (TypeError, ValueError):
        return jsonify(ok=False, message="Salary cap must be a whole number."), 400
    if len(set(n.lower() for n in names)) != len(names):
        return jsonify(ok=False, message="Each team needs a different name."), 400

    def start(conn):
        set_up_draft(conn)
        new_draft(conn, names, cap)

    return draft_action(start)


@app.post("/api/draft/pick")
def draft_pick():
    body = request.get_json(silent=True) or {}
    try:
        player_id = int(body.get("player_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, message="Enter a player ID (numbers only)."), 400

    def pick(conn):
        turn = make_pick(conn, player_id)
        # don't send the name back yet, it shows on the board once the round is done
        return {"pick": {"pick_number": turn["pick_number"], "round": turn["round"]}}

    return draft_action(pick)


@app.post("/api/draft/next")
def draft_next():
    def next_turn(conn):
        continue_turn(conn)
    return draft_action(next_turn)

@app.post("/api/draft/undo")
def draft_undo():
    def undo_last(conn):
        if not undo(conn):
            raise ValueError("There's no pick to undo.")
    return draft_action(undo_last)


@app.get("/api/players/available")
def available_players():
    try:
        with get_connection() as conn:
            return jsonify(ok=True, players=get_available_players(conn))
    except psycopg.Error as e:
        return jsonify(ok=False, players=[], message=f"Couldn't load players: {type(e).__name__}"), 500


def _count_players(conn):
    if conn.execute("SELECT to_regclass('players')").fetchone()[0] is None:
        return 0
    return conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]


@app.errorhandler(413)
def too_big(_error):
    return jsonify(ok=False, message="File is too big (5 MB max).", warnings=[]), 413


if __name__ == "__main__":
    # Not Flask's default 5000: on newer Macs, AirPlay Receiver already listens on 5000.
    # Debug mode is off unless FLASK_DEBUG=1. Its in-browser debugger can run any Python code,
    # so it should never be on by accident (for example on a hosted server).
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001)
