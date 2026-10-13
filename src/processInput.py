"""
Reads a player file (.csv or .xlsx) and loads it into Postgres.

Ported from Justin's SQLite version (commit 881b1d8, "Backend for input and database
reading"). Same idea and same two tables:

    players -> id, name, selected
               The "identity" side. Hidden until the admin types the ID in (name reveal).
    stats   -> id, team, position, all the stat columns, salary
               The "anonymous" side people actually draft from.

Run it from the terminal:
    python src/processInput.py path/to/Master.xlsx

The database comes from the DATABASE_URL environment variable. If that isn't set it
uses a local database called nba_draft (see README for the one-time setup).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

DEFAULT_DATABASE_URL = "postgresql://localhost:5432/nba_draft"

SUPPORTED_EXTENSIONS = (".csv", ".xlsx")

# The two columns we can't do anything without.
REQUIRED_COLUMNS = ["ID", "Player"]

# File header -> Postgres column name for the stats table.
# Postgres won't accept "%" in a plain column name or a name that starts with a digit,
# so "FG%" becomes fg_pct and "3P" becomes three_p. Justin's queries should use these names.
STAT_COLUMNS = {
    "Team": "team",
    "Pos": "position",
    "G": "g",
    "GS": "gs",
    "MP": "mp",
    "FG": "fg",
    "FGA": "fga",
    "FG%": "fg_pct",
    "3P": "three_p",
    "3PA": "three_pa",
    "3P%": "three_p_pct",
    "2P": "two_p",
    "2PA": "two_pa",
    "2P%": "two_p_pct",
    "eFG%": "efg_pct",
    "FT": "ft",
    "FTA": "fta",
    "FT%": "ft_pct",
    "ORB": "orb",
    "DRB": "drb",
    "TRB": "trb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TOV": "tov",
    "PF": "pf",
    "PTS": "pts",
    "Salary": "salary",
}

TEXT_COLUMNS = {"Team", "Pos"}
DECIMAL_COLUMNS = {"FG%", "3P%", "2P%", "eFG%", "FT%"}
# Everything else in STAT_COLUMNS is a whole number (games, makes, attempts, salary...).
INTEGER_COLUMNS = set(STAT_COLUMNS) - TEXT_COLUMNS - DECIMAL_COLUMNS

CREATE_PLAYERS_TABLE = """
    CREATE TABLE IF NOT EXISTS players (
        id       INTEGER PRIMARY KEY,
        name     TEXT    NOT NULL,
        selected BOOLEAN NOT NULL DEFAULT FALSE
    )
"""

# Stats are allowed to be blank (NULL). Master.xlsx really does have blanks:
# 27 players with no salary, 82 with no 3P%, a couple with no FG%. With NOT NULL on
# every column (like the SQLite draft had) the whole upload would fail on the first one.
CREATE_STATS_TABLE = """
    CREATE TABLE IF NOT EXISTS stats (
        id          INTEGER PRIMARY KEY REFERENCES players (id) ON DELETE CASCADE,
        team        TEXT,
        position    TEXT,
        g           INTEGER,
        gs          INTEGER,
        mp          INTEGER,
        fg          INTEGER,
        fga         INTEGER,
        fg_pct      FLOAT,
        three_p     INTEGER,
        three_pa    INTEGER,
        three_p_pct FLOAT,
        two_p       INTEGER,
        two_pa      INTEGER,
        two_p_pct   FLOAT,
        efg_pct     FLOAT,
        ft          INTEGER,
        fta         INTEGER,
        ft_pct      FLOAT,
        orb         INTEGER,
        drb         INTEGER,
        trb         INTEGER,
        ast         INTEGER,
        stl         INTEGER,
        blk         INTEGER,
        tov         INTEGER,
        pf          INTEGER,
        pts         INTEGER,
        salary      INTEGER
    )
"""


class InputFileError(Exception):
    """A problem with the uploaded file that the admin can fix (wrong type, missing columns...)."""


# ---------------------------------------------------------------------------
# Step 1: read the file and clean it up (no database needed, easy to test)
# ---------------------------------------------------------------------------

def readFile(filename, warnings: list[str] | None = None) -> pd.DataFrame:
    """
    Open a .csv or .xlsx player file and return a cleaned DataFrame with one row per player.

    Raises InputFileError with a readable message if the file can't be used.
    Smaller problems (blank salaries, a junk cell) get added to `warnings` instead,
    so one bad cell doesn't block the whole upload.
    """
    if warnings is None:
        warnings = []
    path = Path(filename)

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise InputFileError(
            f"Not a supported file type ({path.suffix or 'no extension'}). Must be .csv or .xlsx"
        )
    if not path.exists():
        raise InputFileError(f"File not found: {path.name}")
    if path.stat().st_size == 0:
        raise InputFileError("The file is empty.")

    df = _open_spreadsheet(path)

    # Ignore stray spaces in headers (" Salary " still counts as "Salary") and letter case.
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns=_match_headers(df.columns))

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise InputFileError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Columns found: {', '.join(map(str, df.columns))}"
        )

    known = REQUIRED_COLUMNS + list(STAT_COLUMNS)
    extra = [c for c in df.columns if c not in known]
    if extra:
        warnings.append(f"Ignored column(s) the app doesn't use: {', '.join(extra)}")
    not_in_file = [c for c in STAT_COLUMNS if c not in df.columns]
    if not_in_file:
        warnings.append(f"Column(s) not in the file, left blank: {', '.join(not_in_file)}")
        for c in not_in_file:
            df[c] = None
    df = df[known]

    # Excel files often have empty rows at the bottom. Drop rows that are completely blank.
    df = df.dropna(how="all")

    # --- ID and name: every player needs both ---
    df["ID"] = _to_number(df["ID"])
    df["Player"] = df["Player"].astype("string").str.strip().map(_fix_name, na_action="ignore")
    no_id = df["ID"].isna() | (df["ID"] % 1 != 0)        # blank, text, or a decimal like 12.5
    no_name = df["Player"].fillna("").eq("")
    bad = no_id | no_name
    if bad.any():
        # +2 turns the 0-based row index into the row number you'd see in Excel (header is row 1)
        rows = ", ".join(str(i + 2) for i in df.index[bad][:5])
        warnings.append(f"Skipped {bad.sum()} row(s) with a missing/invalid ID or name (row {rows}...)")
        df = df[~bad]
    df["ID"] = df["ID"].astype("int64")

    dupes = df["ID"].duplicated()
    if dupes.any():
        ids = ", ".join(str(i) for i in df.loc[dupes, "ID"].head(5))
        warnings.append(f"Skipped {dupes.sum()} duplicate ID(s), kept the first one: {ids}")
        df = df[~dupes]

    if df.empty:
        raise InputFileError("No player rows found in the file.")

    # --- stats ---
    for col in TEXT_COLUMNS:
        df[col] = df[col].astype("string").str.strip()

    for col in INTEGER_COLUMNS | DECIMAL_COLUMNS:
        before_blank = df[col].isna()
        df[col] = _to_number(df[col])
        junk = df[col].isna() & ~before_blank
        if junk.any():
            warnings.append(f"{col}: {junk.sum()} value(s) weren't numbers and were left blank")
        if col in INTEGER_COLUMNS:
            df[col] = df[col].round().astype("Int64")  # Int64 (capital I) allows blanks

    no_salary = df["Salary"].isna()
    if no_salary.any():
        names = ", ".join(df.loc[no_salary, "Player"].head(3))
        warnings.append(
            f"{no_salary.sum()} player(s) have no salary (e.g. {names}). "
            "They're loaded with a blank salary."
        )

    return df.reset_index(drop=True)


def _open_spreadsheet(path: Path) -> pd.DataFrame:
    """Read the raw file. Turns pandas' many possible errors into one InputFileError."""
    try:
        if path.suffix.lower() == ".xlsx":
            return pd.read_excel(path)  # first sheet
        # CSVs saved from Excel aren't always UTF-8, so try the common encodings in order.
        # latin-1 can decode any bytes, so the loop always ends with a result.
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return pd.read_csv(path, encoding=encoding)
            except UnicodeDecodeError:
                continue
    except pd.errors.EmptyDataError:
        raise InputFileError("The file has no data in it.")
    except Exception as e:  # corrupted file, a PDF renamed to .xlsx, etc.
        raise InputFileError(f"Couldn't read {path.name} as a {path.suffix} file ({type(e).__name__}).")


def _match_headers(headers) -> dict:
    """Map headers like 'salary' or 'player' to the exact names the code expects."""
    wanted = {name.lower(): name for name in REQUIRED_COLUMNS + list(STAT_COLUMNS)}
    return {h: wanted[h.lower()] for h in headers if h.lower() in wanted}


def _to_number(column: pd.Series) -> pd.Series:
    """Convert a column to numbers. '$1,234' -> 1234. Anything else non-numeric -> blank."""
    as_text = column.astype("string").str.replace(r"[$,\s]", "", regex=True)
    return pd.to_numeric(as_text, errors="coerce")


def _fix_name(name: str) -> str:
    """
    Master.xlsx stores some names garbled: 'Peja Stojakoviƒá' instead of 'Peja Stojaković'
    (9 players). That's UTF-8 text that got read as Mac Roman at some point. Reversing it
    gives the real name back, which matters because this is what shows on the name reveal.
    Names that are already fine (plain ASCII, or real accents like 'José') come back unchanged.
    """
    if name.isascii():
        return name
    try:
        return name.encode("mac_roman").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


# ---------------------------------------------------------------------------
# Step 2: write it to Postgres
# ---------------------------------------------------------------------------

def get_connection() -> psycopg.Connection:
    return psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))


def set_up_db(conn: psycopg.Connection) -> None:
    """Create the players and stats tables if they don't exist yet."""
    with conn.cursor() as cursor:
        cursor.execute(CREATE_PLAYERS_TABLE)
        cursor.execute(CREATE_STATS_TABLE)


def insert_players(df: pd.DataFrame, cursor) -> None:
    # %s placeholders let psycopg handle quoting, so names like O'Neal can't break the SQL.
    rows = [(int(r.ID), r.Player) for r in df[["ID", "Player"]].itertuples(index=False)]
    cursor.executemany("INSERT INTO players (id, name) VALUES (%s, %s)", rows)


def insert_stats(df: pd.DataFrame, cursor) -> None:
    columns = ["id"] + list(STAT_COLUMNS.values())
    placeholders = ", ".join(["%s"] * len(columns))
    # Safe to build the column list with join: the names come from STAT_COLUMNS above, never from the file.
    query = f"INSERT INTO stats ({', '.join(columns)}) VALUES ({placeholders})"
    rows = [
        tuple(_plain_python(v) for v in row)
        for row in df[["ID"] + list(STAT_COLUMNS)].itertuples(index=False)
    ]
    cursor.executemany(query, rows)


def _plain_python(value):
    """psycopg can't send pandas/numpy types, so turn them into normal Python values (blank -> None)."""
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def load_into_db(df: pd.DataFrame, conn: psycopg.Connection) -> None:
    """
    Replace whatever players are in the database with the ones in df.

    Everything happens in ONE transaction: if anything fails halfway, Postgres rolls it
    all back and the previous player list is still there untouched.
    """
    with conn.transaction():
        set_up_db(conn)
        with conn.cursor() as cursor:
            # New upload = new player pool. (Open question for the team, see README.)
            cursor.execute("TRUNCATE stats, players")
            insert_players(df, cursor)
            insert_stats(df, cursor)


# ---------------------------------------------------------------------------
# The one function the web app calls. It never raises; it always returns a result.
# ---------------------------------------------------------------------------

def process_file(filename) -> dict:
    """
    Read + load a player file. Returns:
        {"ok": True/False, "message": "...", "players_loaded": n, "warnings": [...]}
    """
    warnings: list[str] = []
    try:
        df = readFile(filename, warnings)
        with get_connection() as conn:
            load_into_db(df, conn)
        return {
            "ok": True,
            "message": f"Loaded {len(df)} players.",
            "players_loaded": len(df),
            "warnings": warnings,
        }
    except InputFileError as e:
        return _failed(str(e), warnings)
    except psycopg.OperationalError:
        return _failed("Couldn't connect to the database. Is Postgres running?", warnings)
    except psycopg.Error as e:
        return _failed(f"Database error, nothing was saved: {e}", warnings)
    except Exception as e:  # last line of defense so the app never crashes on an upload
        return _failed(f"Unexpected error, nothing was saved: {type(e).__name__}: {e}", warnings)


def _failed(message: str, warnings: list[str]) -> dict:
    return {"ok": False, "message": message, "players_loaded": 0, "warnings": warnings}


def main():
    if len(sys.argv) != 2:
        print("Usage: python src/processInput.py path/to/file.xlsx")
        sys.exit(1)
    result = process_file(sys.argv[1])
    print(result["message"])
    for w in result["warnings"]:
        print("  warning:", w)
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
