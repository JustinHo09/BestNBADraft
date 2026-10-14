# player lock tests, need TEST_DATABASE_URL like the db tests in test_processInput.py

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from draft import PlayerAlreadyLockedError, PlayerNotFoundError, is_locked, lock_player  # noqa: E402
from processInput import process_file  # noqa: E402

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run database tests")


@pytest.fixture
def db(monkeypatch, tmp_path):
    import psycopg
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS stats, players")
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
