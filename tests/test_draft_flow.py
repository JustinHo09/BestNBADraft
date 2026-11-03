# full draft tests through the routes, same calls draft.html makes
# need TEST_DATABASE_URL like the other database tests

import os

import pytest

from processInput import process_file

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run database tests")


@pytest.fixture
def client(monkeypatch, tmp_path):
    import psycopg
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS picks, current_state, groups, stats, players CASCADE")
    # 40 cheap players (IDs 1-40, $10 each) plus one with no salary (ID 99)
    rows = "\n".join(f"{i},Player {i},PG,{10}" for i in range(1, 41))
    players = tmp_path / "players.csv"
    players.write_text(f"ID,Player,Pos,Salary\n{rows}\n99,No Salary Guy,C,\n")
    assert process_file(players)["ok"]

    from app import app
    return app.test_client()


def start(client, names=("A", "B", "C"), cap=1000):
    res = client.post("/api/draft/new", json={"group_names": list(names), "salary_cap": cap})
    assert res.status_code == 200, res.get_json()
    return res.get_json()["draft"]


def test_pages_load(client):
    assert b'id="board"' in client.get("/draft").data   # draft board
    assert b'id="drop"' in client.get("/").data          # upload page stays at / like before


def test_state_before_any_draft(client):
    data = client.get("/api/draft").get_json()
    assert data["ok"] and data["started"] is False and data["players_loaded"] == 41


def test_pick_reveals_name_and_fills_the_grid(client):
    start(client)
    res = client.post("/api/draft/pick", json={"player_id": 7})
    data = res.get_json()
    assert res.status_code == 200
    assert data["player"]["name"] == "Player 7"
    assert data["draft"]["picks"] == [{
        "round": 1, "seat": 1, "name": "Player 7", "position": "PG", "team": "N/A",
        "pick_number": 1, "player_id": 7, "salary": 10,
    }]
    assert data["draft"]["pick_made"] is True
    assert data["draft"]["groups"][0]["money_left"] == 990


def test_next_turn_moves_to_the_next_team_then_the_next_round(client):
    start(client)
    expected = [(1, 2, "B"), (1, 3, "C"), (2, 1, "A")]   # after picks 1, 2, 3
    for player_id, (rnd, seat, team) in zip([1, 2, 3], expected):
        assert client.post("/api/draft/pick", json={"player_id": player_id}).status_code == 200
        d = client.post("/api/draft/next").get_json()["draft"]
        assert (d["round"], d["seat"], d["group_name"], d["pick_made"]) == (rnd, seat, team, False)


def test_cannot_skip_a_turn_or_pick_twice(client):
    start(client)
    assert client.post("/api/draft/next").status_code == 409
    client.post("/api/draft/pick", json={"player_id": 1})
    assert client.post("/api/draft/pick", json={"player_id": 2}).status_code == 409


def test_bad_picks_are_rejected_without_using_the_turn(client):
    start(client, cap=15)
    client.post("/api/draft/pick", json={"player_id": 1})
    client.post("/api/draft/next")
    assert client.post("/api/draft/pick", json={"player_id": 1}).status_code == 409    # already drafted
    assert client.post("/api/draft/pick", json={"player_id": 500}).status_code == 404  # no such ID
    assert client.post("/api/draft/pick", json={"player_id": 99}).status_code == 422   # no salary
    assert client.post("/api/draft/pick", json={"player_id": "x"}).status_code == 400  # not a number
    d = client.get("/api/draft").get_json()["draft"]
    assert d["pick_number"] == 2 and d["pick_made"] is False  # still B's turn, nothing saved


def test_budget_counts_what_was_already_spent(client):
    start(client, cap=15)                         # each team can afford exactly one $10 player
    for pid in (1, 2, 3):                         # A, B, C each take one
        client.post("/api/draft/pick", json={"player_id": pid})
        client.post("/api/draft/next")
    res = client.post("/api/draft/pick", json={"player_id": 4})  # A again, only $5 left
    assert res.status_code == 422 and "cap" in res.get_json()["message"]


def test_draft_ends_after_ten_rounds(client):
    start(client)
    for pid in range(1, 31):                      # 3 teams x 10 rounds
        assert client.post("/api/draft/pick", json={"player_id": pid}).status_code == 200
        client.post("/api/draft/next")
    d = client.get("/api/draft").get_json()["draft"]
    assert d["is_over"] is True and len(d["picks"]) == 30
    assert client.post("/api/draft/pick", json={"player_id": 31}).status_code == 409


def test_new_draft_needs_3_to_5_unique_teams(client):
    assert client.post("/api/draft/new", json={"group_names": ["A", "B"], "salary_cap": 10}).status_code == 400
    assert client.post("/api/draft/new", json={"group_names": ["A", "a", "B"], "salary_cap": 10}).status_code == 400
    assert client.post("/api/draft/new", json={"group_names": list("ABCDEF"), "salary_cap": 10}).status_code == 400
    assert client.post("/api/draft/new", json={"group_names": ["A", "B", "C"], "salary_cap": 0}).status_code == 400


def test_new_draft_clears_the_old_one(client):
    start(client)
    client.post("/api/draft/pick", json={"player_id": 1})
    d = start(client, names=("X", "Y", "Z", "W"))
    assert d["picks"] == [] and d["pick_number"] == 1 and [g["name"] for g in d["groups"]] == list("XYZW")
    assert client.post("/api/draft/pick", json={"player_id": 1}).status_code == 200  # unlocked again


def test_available_players_hide_names_and_drop_drafted_players(client):
    start(client)
    client.post("/api/draft/pick", json={"player_id": 1})
    players = client.get("/api/players/available").get_json()["players"]
    assert len(players) == 40 and all("name" not in p for p in players)
    assert 1 not in {p["id"] for p in players}


def test_reimporting_players_mid_draft_resets_picks(client, tmp_path):
    start(client)
    client.post("/api/draft/pick", json={"player_id": 1})
    client.post("/api/draft/next")
    again = tmp_path / "again.csv"
    again.write_text("ID,Player,Salary\n1,New Guy,5\n")
    assert process_file(again)["ok"]          # this used to fail because picks pointed at the old players
    d = client.get("/api/draft").get_json()["draft"]
    assert d["picks"] == [] and d["pick_number"] == 1


def test_player_list_for_the_import_page(client, tmp_path):
    roster = tmp_path / "roster.csv"
    roster.write_text("ID,Player,Pos,Team,Salary\n5,Kevin Garnett,PF,MIN,1\n6,LeBron James,SF,CLE,1\n7,Ray Allen,SG,SEA,1\n")
    assert process_file(roster)["ok"]
    data = client.get("/api/players").get_json()
    assert data["total"] == 3
    # sorted by last name, and no IDs (the ID is only for typing in a pick)
    assert data["players"] == [
        {"name": "Ray Allen", "position": "SG", "team": "SEA"},
        {"name": "Kevin Garnett", "position": "PF", "team": "MIN"},
        {"name": "LeBron James", "position": "SF", "team": "CLE"},
    ]
