# BestNBADraft: Postgres import (Ali's part)

This is the "import player's dataset" story moved from SQLite to Postgres. It started
from Justin's `src/processInput.py` (commit `881b1d8`) and keeps his design:

- `players`: id, name, selected. The hidden side that gets revealed when the admin types in an ID.
- `stats`: id plus team, position, every stat column, and salary. The anonymous side people draft from.

Acceptance criteria covered:
1. A `.csv` or `.xlsx` player file gets loaded into Postgres (`Master.xlsx` loads all 441 players).
2. A bad file returns an error message instead of crashing. Tests cover a wrong file type, an
   empty file, a corrupted xlsx, missing columns, junk cells, duplicate IDs, and a failed insert.

## Files

| File | What it does |
|---|---|
| `src/processInput.py` | Reads the file, cleans it, creates the tables, and loads them. Replaces Justin's SQLite version. |
| `src/app.py` | Small Flask server. `POST /upload` takes the file, and `GET /players` shows what loaded. |
| `src/upload.html` | Bare-minimum drag-and-drop upload page for Xavier to restyle or copy into the real front end. |
| `tests/test_processInput.py` | 15 tests (pytest). |
| `requirements.txt` | Python packages. |

`Master.xlsx` isn't in the repo. The tests look for it one folder up from the repo
(`../Master.xlsx`). If yours is somewhere else, set `MASTER_XLSX=/path/to/Master.xlsx`.
Without it, the tests that need it are skipped.

## One-time setup (Mac)

1. Open **Postgres.app** and click **Initialize**. The elephant in the menu bar means it's running.
2. Add its command-line tools to your PATH (one time, then open a new terminal):
   ```
   sudo mkdir -p /etc/paths.d && echo /Applications/Postgres.app/Contents/Versions/latest/bin | sudo tee /etc/paths.d/postgresapp
   ```
3. Create the database:
   ```
   createdb nba_draft
   ```
4. From this folder, set up Python:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Run it

```
python src/processInput.py ../Master.xlsx     # load from the terminal
python src/app.py                             # then open http://127.0.0.1:5001 and drop the file in
pytest                                        # file-reading tests (no DB needed)
TEST_DATABASE_URL=postgresql://localhost:5432/nba_draft_test pytest   # plus Postgres tests
```

The app runs on port 5001, not Flask's usual 5000, because AirPlay Receiver on newer Macs
already uses 5000. For auto-reload and error pages while you work, start it with
`FLASK_DEBUG=1 python src/app.py`. Debug mode is off otherwise, and should stay off anywhere
other people can reach the app.

The Postgres tests drop and recreate the tables in whatever database `TEST_DATABASE_URL` points
at, so give them their own (`createdb nba_draft_test`). Never point them at the real one.

The database comes from the `DATABASE_URL` environment variable and defaults to
`postgresql://localhost:5432/nba_draft`. When the app is hosted, set `DATABASE_URL` to the
hosted database's connection string and nothing in the code changes.

## What changed from the SQLite version, and why

| SQLite version | Problem | Now |
|---|---|---|
| `main()` calls `readFile()` with no file name, and nothing calls `main()` | Crashes immediately | `python src/processInput.py <file>` |
| `df.loc[:,2]` | Columns are named, not numbered, so it raises a KeyError | Uses the `ID` and `Player` columns by name |
| `CREATE TABLE ... players id INTEGER ...` | Missing the `( )` around the columns, so it's a syntax error | Fixed |
| `create_table_stats` is built but never executed | The stats table never exists | Executed |
| Columns named `fg%`, `3p`, `eFG%` | Not valid Postgres column names | `fg_pct`, `three_p`, `efg_pct`, and so on (full map in `STAT_COLUMNS`) |
| `PF` column | Missing from the stats table | Added |
| `NOT NULL` on every stat | Master.xlsx has 27 blank salaries and 82 blank 3P%, so the first blank fails the insert | Stats can be blank. Only id and name are required |
| `for player in players:` | Loops over column names, not rows | Inserts one row per player |
| `"INSERT ... VALUES(" + player + ")"` | Breaks on `Shaquille O'Neal` and allows SQL injection | `%s` placeholders |
| No `commit()` | Nothing is ever saved | One transaction: all rows save, or none do |
| Unsupported file type `return`s a string | The caller never checks it | Raises `InputFileError`, and the app shows the message |

Also new:
- Some names in Master.xlsx are garbled (`Peja Stojakoviƒá`), so 9 names would look broken on the
  name reveal. The import repairs them (`Peja Stojaković`).
- Headers don't have to match exactly. `salary`, ` Salary `, and `SALARY` all work.
- `$1,234,567` style salaries from CSV exports are parsed. CSVs saved by Windows Excel (not UTF-8) open too.

## For Justin's queries

Use these columns: `players.id`, `players.name`, `players.selected` (boolean, starts `FALSE`),
`stats.salary` (can be `NULL`). Both tables share `id`, and `stats.id` references `players.id`.
With psycopg, pass values as `%s` parameters, not by gluing strings together.

## For Xavier

POST the file to `/upload` as form field `file`. You get JSON back:
`{"ok": true, "message": "Loaded 441 players.", "players_loaded": 441, "warnings": [...]}`.
On failure, `ok` is `false` and `message` says why. The page never needs to handle a crash.

## Open questions for the team

1. **Re-uploading replaces the player pool.** A new upload wipes the current players (including
   `selected`) in the same transaction, so a failed upload leaves the old data alone. Dr. Best's
   whiteboard also says "select from datasets already imported." Supporting that means adding a
   `datasets` table and a `dataset_id` on both tables. That's worth deciding before Justin's
   queries get written.
2. **27 players have no salary** in Master.xlsx. Current plan (Ali and Justin): an admin option
   in the UI to either count blank salaries as $0 (free agents) or leave those players out of
   the pool. The import already stores a blank salary as `NULL`, so it supports either choice
   and only the UI and salary cap logic need to change.
   Still open: how to handle other missing stats (82 blank 3P%, a few blank FG%). They're also
   stored as `NULL` for now. We may ask Dr. Best or Esteban.
3. **Flask** is a guess, since the repo doesn't pick a web framework yet. If the team goes with
   something else, `processInput.process_file()` works the same way. Only `app.py` would change.
