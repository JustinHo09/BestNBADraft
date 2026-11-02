# player lock tests, need TEST_DATABASE_URL like the db tests in test_processInput.py

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from draft import PlayerAlreadyLockedError, PlayerNotFoundError, is_locked, lock_player, seat_pick, na, set_up_draft, new_draft, current_pick  # noqa: E402
from processInput import process_file  # noqa: E402
from group import load_group_data

TEST_DB = os.environ.get("TEST_DATABASE_URL")
# This will stop the test for things that don't need the DB up from running
#pytestmark = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run database tests")


@pytest.fixture
def db(monkeypatch, tmp_path):
    import psycopg
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS stats, players CASCADE")
        players = tmp_path / "players.csv"
        players.write_text("ID,Player,Salary\n1,First Guy,100\n2,Second Guy,200\n3,Third Guy,300\n")
        assert process_file(players)["ok"]
        yield conn


def test_new_players_start_unlocked(db):
    assert is_locked(db, 1) is False


def test_lock_player_locks_them(db):
    lock_player(db, 1)
    assert is_locked(db, 1) is True


def test_locking_one_player_leaves_the_others_alone(db):
    lock_player(db, 1)
    assert is_locked(db, 2) is False and is_locked(db, 3) is False


def test_cannot_lock_a_player_twice(db):
    lock_player(db, 2)
    with pytest.raises(PlayerAlreadyLockedError):
        lock_player(db, 2)
    assert is_locked(db, 2) is True


def test_two_teams_picking_at_the_same_time_only_one_gets_him(db):
    # A locks player 1 but hasn't committed, B tries the same player and should lose
    import threading
    import psycopg

    team_b_result = []

    def team_b_picks():
        with psycopg.connect(TEST_DB) as conn_b:
            try:
                lock_player(conn_b, 1)
                team_b_result.append("got him")
            except PlayerAlreadyLockedError:
                team_b_result.append("already taken")

    with psycopg.connect(TEST_DB) as conn_a:
        lock_player(conn_a, 1)
        team_b = threading.Thread(target=team_b_picks)
        team_b.start()
        team_b.join(timeout=1)
        assert team_b.is_alive()  # still waiting on A
        conn_a.commit()
    team_b.join(timeout=5)

    assert team_b_result == ["already taken"]


def test_locking_an_unknown_id_is_an_error(db):
    with pytest.raises(PlayerNotFoundError):
        lock_player(db, 999)
    with pytest.raises(PlayerNotFoundError):
        is_locked(db, 999)


def test_lock_route(db):
    from app import app
    client = app.test_client()

    res = client.post("/players/3/lock")
    assert res.status_code == 200 and res.get_json()["ok"] is True

    res = client.post("/players/3/lock")
    assert res.status_code == 409 and res.get_json()["ok"] is False

    res = client.post("/players/999/lock")
    assert res.status_code == 404 and res.get_json()["ok"] is False

    assert is_locked(db, 3) is True


def test_lock_route_when_database_is_down(db, monkeypatch):
    from app import app
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:1/nothing_here")
    res = app.test_client().post("/players/1/lock")
    assert res.status_code == 500 and res.get_json()["ok"] is False

def test_first_pick_seat():
    assert seat_pick(1,3) == (1,1)

def test_last_pick_seat():
    assert seat_pick(3, 3) == (3, 1)

def test_middle_pick_seat():
    assert seat_pick(3, 5) == (3, 1)

def test_new_round_pick_seat():
    assert seat_pick(4,3) == (1,2)

def test_invalid_groups_pick_seat():
    assert seat_pick(4,0) == (-1,-1)
    assert seat_pick(4, 6) == (-1, -1)
    assert seat_pick(4, -10) == (-1, -1)
    assert seat_pick(4, 60) == (-1, -1)

def test_invalid_turns_pick_seat():
    assert seat_pick(-4,4) == (-1,-1)
    assert seat_pick(0, 3) == (-1, -1)

def test_na():
    assert na("") == 'N/A'
    assert na(None) == 'N/A'
    assert na("Hello") == 'Hello'

def test_set_up_draft(db):
    set_up_draft(db)
    assert db.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM current_state").fetchone()[0] == 0

def test_start_new_draft(db):
    set_up_draft(db)
    new_draft(db, ["Jean Grey", "Archie Grey", "Gris"], 1000000)
    assert db.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 3
    assert db.execute("SELECT current_pick FROM current_state").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0

def test_current_pick(db):
    set_up_draft(db)
    new_draft(db, ["Jean Grey", "Archie Grey", "Gris"], 1000000)
    turn = current_pick(db)
    assert turn["pick_number"] == 1
    assert turn["round"] == 1
    assert turn["group"] == 1

def test_group(db):
    set_up_draft(db)
    new_draft(db, ["Jean Grey", "Archie Grey", "Gris"], 1000000)
    first_group = db.execute("SELECT id FROM groups WHERE seat =1").fetchone()[0]
    group = load_group_data(db, first_group)
    assert group.remaining == 1000000

def test_group_salary_down(db):
    set_up_draft(db)
    new_draft(db, ["Jean Grey", "Archie Grey", "Gris"], 1000000)
    first_group = db.execute("SELECT id FROM groups WHERE seat =1").fetchone()[0]
    db.execute("INSERT INTO picks VALUES (1,1,%s,1)", (first_group,),)
    group = load_group_data(db, first_group)
    assert group.remaining == 1000000-100