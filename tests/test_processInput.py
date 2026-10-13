"""
Tests for the import story's two acceptance criteria:
  1) a CSV or XLSX player file actually gets loaded
  2) bad files give an error message instead of crashing

    pytest                      # file-reading tests only, no database needed
    TEST_DATABASE_URL=postgresql://localhost:5432/nba_draft_test pytest
                                # also runs the Postgres tests (they WIPE that database's tables)
"""

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from processInput import InputFileError, process_file, readFile  # noqa: E402

# Master.xlsx sits one folder up (CSC2040-Project/Master.xlsx). Override with MASTER_XLSX.
MASTER = Path(os.environ.get("MASTER_XLSX", ROOT.parent / "Master.xlsx"))
needs_master = pytest.mark.skipif(not MASTER.exists(), reason=f"{MASTER} not found")

TEST_DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run database tests")


def write_csv(tmp_path, text, name="players.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------- reading good files ----------

@needs_master
def test_master_xlsx_loads_every_player():
    warnings = []
    df = readFile(MASTER, warnings)
    assert len(df) == 441
    assert df["ID"].is_unique
    assert "LeBron James" in set(df["Player"])
    assert any("27 player(s) have no salary" in w for w in warnings)


@needs_master
def test_garbled_names_are_fixed():
    names = set(readFile(MASTER)["Player"])
    assert "Peja Stojaković" in names
    assert "Željko Rebrača" in names
    assert not any("ƒ" in n or "≈" in n for n in names)
    assert "Shaquille O'Neal" in names  # apostrophes survive


@needs_master
def test_same_data_as_csv(tmp_path):
    csv_path = tmp_path / "Master.csv"
    pd.read_excel(MASTER).to_csv(csv_path, index=False)
    assert len(readFile(csv_path)) == 441


def test_messy_csv_is_cleaned_not_rejected(tmp_path):
    path = write_csv(tmp_path, (
        " id ,PLAYER,Team,Pos,G,Salary,Notes\n"
        '1,Good Guy,BOS,PG,82,"$1,234,567",hi\n'
        "2,Junk Games,BOS,SG,abc,500000,\n"
        ",No Id,BOS,C,10,1,\n"
        "3,,BOS,C,10,1,\n"
        "1,Duplicate Id,BOS,C,10,1,\n"
        ",,,,,,\n"
    ))
    warnings = []
    df = readFile(path, warnings)
    assert list(df["ID"]) == [1, 2]
    assert df.loc[0, "Salary"] == 1234567
    assert pd.isna(df.loc[1, "G"])
    text = " | ".join(warnings)
    assert "Ignored column(s)" in text and "Notes" in text
    assert "Skipped 2 row(s)" in text
    assert "duplicate ID" in text
    assert "G: 1 value(s) weren't numbers" in text


def test_windows_encoded_csv(tmp_path):
    path = tmp_path / "cp1252.csv"
    path.write_bytes("ID,Player\n1,José Calderón\n".encode("cp1252"))
    assert readFile(path).loc[0, "Player"] == "José Calderón"


# ---------- bad files: clear error, no crash ----------

@pytest.mark.parametrize("name,content,expected", [
    ("players.pdf", b"%PDF-1.4", "Must be .csv or .xlsx"),
    ("players.csv", b"", "empty"),
    ("players.xlsx", b"this is not really a spreadsheet", "Couldn't read"),
    ("players.csv", b"Name,Team\nBob,BOS\n", "Missing required column(s): ID, Player"),
    ("players.csv", b"ID,Player\n,\nabc,\n", "No player rows"),
])
def test_bad_files_raise_readable_errors(tmp_path, name, content, expected):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(InputFileError, match=expected.replace("(", r"\(").replace(")", r"\)")):
        readFile(path)


def test_process_file_never_raises(tmp_path):
    path = tmp_path / "bad.xlsx"
    path.write_bytes(b"garbage")
    result = process_file(path)
    assert result["ok"] is False
    assert "Couldn't read" in result["message"]


# ---------- Postgres ----------

@pytest.fixture
def db(monkeypatch):
    import psycopg
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS stats, players")
        yield conn


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@needs_db
@needs_master
def test_master_lands_in_postgres(db):
    result = process_file(MASTER)
    assert result["ok"], result["message"]
    assert count(db, "players") == 441 and count(db, "stats") == 441
    name, salary, selected = db.execute(
        "SELECT p.name, s.salary, p.selected FROM players p JOIN stats s USING (id) WHERE id = 18914"
    ).fetchone()
    assert (name, salary, selected) == ("Peja Stojaković", 10689133, False)


@needs_db
@needs_master
def test_reupload_replaces_instead_of_crashing(db):
    assert process_file(MASTER)["ok"]
    assert process_file(MASTER)["ok"]  # same IDs again would hit the primary key without the TRUNCATE
    assert count(db, "players") == 441


@needs_db
@needs_master
def test_failed_upload_keeps_previous_players(db, tmp_path):
    assert process_file(MASTER)["ok"]
    bad = write_csv(tmp_path, "ID,Player,Salary\n1,Too Rich,99999999999\n")  # too big for INTEGER
    result = process_file(bad)
    assert result["ok"] is False and "nothing was saved" in result["message"]
    assert count(db, "players") == 441  # the transaction rolled back


@needs_db
def test_upload_route(db, tmp_path):
    from app import app
    client = app.test_client()
    csv_path = write_csv(tmp_path, "ID,Player,Team,Pos,Salary\n7,Test Player,BOS,PG,1000\n")
    with open(csv_path, "rb") as f:
        res = client.post("/upload", data={"file": (f, "players.csv")})
    assert res.status_code == 200 and res.get_json()["players_loaded"] == 1
    res = client.post("/upload", data={"file": (open(csv_path, "rb"), "players.txt")})
    assert res.status_code == 400
    assert client.get("/players").get_json()["total_players"] == 1
