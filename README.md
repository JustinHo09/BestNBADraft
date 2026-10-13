# BestNBADraft

Draft app for Dr. Best (CSC 2040, Best Bruins). Right now it has the player import. You give it a .csv or .xlsx of players and it loads them into Postgres.

I started from Justin's processInput.py (881b1d8) and moved it from SQLite to Postgres. It still uses his two tables:

- `players` (id, name, selected) is the hidden side. The name shows up when the admin types in the ID.
- `stats` (id, team, position, all the stats, salary) is what people actually draft from.

Master.xlsx loads all 441 players. If you upload a bad file (wrong type, empty, broken xlsx, missing columns, stuff like that) you get an error message back instead of a crash.

## What's in here

- `src/processInput.py` reads the file, cleans it up and loads it into the database
- `src/app.py` is a small Flask server. `POST /upload` takes the file and `GET /players` shows what got loaded
- `src/upload.html` is a plain drag and drop upload page. Xavier, restyle it or pull it into the real front end, whatever works
- `tests/test_processInput.py` has 15 pytest tests
- `requirements.txt`

Master.xlsx isn't in the repo. The tests look for it one folder up (`../Master.xlsx`), or you can point them at it with `MASTER_XLSX=/path/to/Master.xlsx`. If they can't find it, those tests just get skipped.

## Setup (Mac)

1. Install Postgres.app, open it and click Initialize. If the elephant is in your menu bar, it's running.
2. Put its command line tools on your PATH, then open a new terminal:
   ```
   sudo mkdir -p /etc/paths.d && echo /Applications/Postgres.app/Contents/Versions/latest/bin | sudo tee /etc/paths.d/postgresapp
   ```
3. Make the database:
   ```
   createdb nba_draft
   ```
4. Set up Python from the repo folder:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Running it

```
python src/processInput.py ../Master.xlsx     # load from the terminal
python src/app.py                             # then open http://127.0.0.1:5001 and drop the file in
pytest                                        # file reading tests (no DB needed)
TEST_DATABASE_URL=postgresql://localhost:5432/nba_draft_test pytest   # plus Postgres tests
```

The app is on port 5001 instead of 5000 because AirPlay on newer Macs already takes 5000. If you want auto reload and error pages while you work, run `FLASK_DEBUG=1 python src/app.py`. Just don't leave debug on anywhere other people can get to it.

Heads up on the database tests: they drop the tables in whatever `TEST_DATABASE_URL` points to. Give them their own database (`createdb nba_draft_test`) and never point them at the real one.

The app connects to `DATABASE_URL`, and if that isn't set it uses `postgresql://localhost:5432/nba_draft`. When we host it we just set `DATABASE_URL` and the code stays the same.

## What I changed from the SQLite version

A few things kept the old version from running:

- `main()` called `readFile()` without a file name, and nothing called `main()` anyway. Now you run `python src/processInput.py <file>`.
- `df.loc[:,2]` throws a KeyError because the columns have names, not numbers. It uses `ID` and `Player` now.
- The players `CREATE TABLE` was missing the `( )` around the columns, and the stats one never got executed.
- `fg%`, `3p` and `eFG%` aren't valid column names in Postgres, so they're `fg_pct`, `three_p`, `efg_pct` and so on. The full list is `STAT_COLUMNS` in processInput.py. `PF` was missing so I added it.
- Every stat was `NOT NULL`, but Master.xlsx has 27 blank salaries and 82 blank 3P%, so the first blank killed the insert. Now only id and name are required.
- The insert loop went over the column names instead of the rows.
- Building the SQL with `+` broke on Shaquille O'Neal, and it's open to SQL injection. It uses `%s` placeholders now.
- There was no `commit()`, so nothing actually saved. The whole upload is one transaction now. Either every row saves or none of them do.
- A bad file type returned a string that nothing checked. Now it raises `InputFileError` and the app shows the message.

Smaller stuff I fixed while I was in there:

- 9 names in Master.xlsx are garbled, like `Peja Stojakoviƒá`. The import fixes them (`Peja Stojaković`) so the name reveal doesn't look broken.
- Capitalization and extra spaces in the headers don't matter. `salary` and ` SALARY ` both work.
- Salaries written like `$1,234,567` work, and so do CSVs saved from Excel on Windows.

## Justin

For the queries you'll want `players.id`, `players.name`, `players.selected` (boolean, starts as `FALSE`) and `stats.salary` (can be `NULL`). Both tables share `id`. Pass values with `%s` instead of adding strings together.

## Xavier

Send the file to `/upload` as a form field called `file`. You get JSON back like this:

```
{"ok": true, "message": "Loaded 441 players.", "players_loaded": 441, "warnings": [...]}
```

If something's wrong, `ok` is `false` and `message` says what happened. It won't crash on you.

## Still need to figure out

1. Uploading a new file replaces all the players, selected flags included. If the upload fails, the old players stay. Dr. Best's whiteboard says "select from datasets already imported," and that would need a `datasets` table and a `dataset_id` column. We should decide before the queries get too far.
2. 27 players have no salary. Justin and I are thinking an admin option in the UI: count them as $0 free agents, or leave them out. The import stores a blank salary as `NULL` either way, so only the UI and the salary cap logic would change. We still haven't decided what to do with other missing stats (82 blank 3P%, a few blank FG%). Might ask Dr. Best or Esteban.
3. I picked Flask for now since we haven't chosen a framework. If we switch, only `app.py` changes. `process_file()` works the same either way.
