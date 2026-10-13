# BestNBADraft

Draft app for Dr. Best (CSC 2040, Best Bruins). Right now it has the player import. You give it a .csv or .xlsx of players and it loads them into Postgres.

I started from Justin's processInput.py and moved it from SQLite to Postgres. It still uses his two tables. players has the id, name and whether they've been picked, and that's the side that stays hidden until the admin types in an ID. stats has the id, team, position, all the stats and salary, and that's what people draft from.

Master.xlsx loads all 441 players. If you upload a bad file you get an error message back instead of a crash.

processInput.py does the reading and loading. app.py is a small Flask server with the upload route, and upload.html is a plain upload page (Xavier, use it or toss it, whatever works for the real front end). The tests are in tests/.

## Setup

This is for Mac. Install Postgres.app, open it and click Initialize. Then put its tools on your PATH and open a new terminal:

    sudo mkdir -p /etc/paths.d && echo /Applications/Postgres.app/Contents/Versions/latest/bin | sudo tee /etc/paths.d/postgresapp

Then make the databases and set up Python from the repo folder:

    createdb nba_draft
    createdb nba_draft_test
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

## Running it

    python src/processInput.py ../Master.xlsx
    python src/app.py
    TEST_DATABASE_URL=postgresql://localhost:5432/nba_draft_test pytest

The first one loads the file from the terminal. The second starts the app at http://127.0.0.1:5001 where you can drop the file in. It's on 5001 because AirPlay on newer Macs already uses 5000. Add FLASK_DEBUG=1 in front if you want auto reload while you work, just don't leave it on anywhere other people can get to it.

The last one runs the tests. Be careful with it, the database tests drop the tables in whatever database you point them at, so only ever use nba_draft_test. Without TEST_DATABASE_URL it skips those and only runs the file tests. Master.xlsx isn't in the repo, so the tests look for it one folder up, or wherever MASTER_XLSX points.

The app uses DATABASE_URL if it's set and the local nba_draft database if not, so when we host it we just set that and nothing else changes.

## What I changed from the SQLite version

A few things kept the old version from running. main() called readFile() without a file name and nothing called main(). df.loc[:,2] throws a KeyError since the columns have names, not numbers. The players CREATE TABLE was missing its parentheses and the stats one never ran. Every stat was NOT NULL, but Master.xlsx has 27 blank salaries and 82 blank 3P%, so the first blank killed the insert. The insert loop went over the column names instead of the rows, the SQL was built with + (which breaks on Shaquille O'Neal), and there was no commit(), so nothing ever saved.

Now it uses %s placeholders and the whole upload is one transaction, so either every row saves or none do. Postgres doesn't allow column names like fg% or 3p, so those are fg_pct, three_p and so on (STAT_COLUMNS in processInput.py has the full list). I also added PF, which was missing, and fixed 9 garbled names in Master.xlsx like Peja Stojaković so the name reveal doesn't look broken.

Justin, for the queries you'll want players.id, players.name, players.selected (starts false) and stats.salary (can be null).

Xavier, send the file to /upload as a form field called file. You get back JSON with ok, message, players_loaded and warnings. If ok is false, message says what went wrong.

## Still need to figure out

Uploading a new file replaces all the players. Dr. Best's whiteboard says "select from datasets already imported," which would need a datasets table, so we should decide that before the queries get too far.

27 players have no salary. Justin and I are thinking an admin option in the UI to either count them as $0 free agents or leave them out. Blank salaries are stored as null either way, so only the UI and salary cap code would change. We still haven't decided about other missing stats, might ask Dr. Best or Esteban.

I used Flask for now since we haven't picked a framework. If we switch, only app.py changes.
