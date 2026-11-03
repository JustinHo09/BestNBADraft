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

## Draft board

Load the players first at http://127.0.0.1:5001 like before. Once the file loads, the upload page lists every player with their name, position and team. Then open http://127.0.0.1:5001/draft, name 3 to 5 teams, set the salary cap (defaults to $110M) and hit Start draft. Whose turn it is shows at the top. Type a player ID (or click a row in Available players) and press Enter. The spot on the board says Pick locked in, then hit Next turn (or Enter again) and it moves to the next team. Names stay hidden until every team has picked that round, so round 1's names show up once round 2 starts, along with how many players have been drafted so far. After the last team it wraps to the next round. The grid shows every pick and each team's money left.

The available list doesn't show names since it's a blind draft. It will reject a player who's already taken, an ID that doesn't exist, a player with no salary, or anyone the team can't afford. New draft at the bottom lets you set up a new one. The old picks only get cleared once you hit Start draft, and Cancel takes you back. Other screens like a projector or phones pick up new picks within about 3 seconds.

The page is src/draft.html. It's plain HTML and JS with no build step. All the data comes from the JSON routes listed at the top of src/app.py, so Xavier can restyle it or rebuild it as long as he calls those. The turn logic is Justin's from draft.py and group.py. I fixed a few things in it to get a full draft running:

- make_pick looked up turn["group_id"] but current_pick returns "group", so every pick crashed with a KeyError.
- check_in_budget compared the salary to the whole cap instead of the money left, so a team could spend $110M every round.
- new_draft did nothing when given the wrong number of teams, and current_pick crashed if no draft existed. Both raise clear errors now.
- Re-importing players after a draft started failed because picks point at players. Now importing clears the picks and sends the draft back to pick 1.
- test_group.py was still building Group the old way, so it errored. I updated it and added a budget test.
- get_draft_data returns a few more fields for the page: pick number, team name, whether this turn's pick is made, and salaries.

tests/test_draft_flow.py runs whole drafts through the API (picks, next turn, budget, bad IDs, 10 rounds ending the draft). All 50 tests pass.

Not in this version: undo, the timer, trading, music, and snake order. Picks go 1, 2, 3, 1, 2, 3 every round for now.

## What I changed from the SQLite version

A few things kept the old version from running. main() called readFile() without a file name and nothing called main(). df.loc[:,2] throws a KeyError since the columns have names, not numbers. The players CREATE TABLE was missing its parentheses and the stats one never ran. Every stat was NOT NULL, but Master.xlsx has 27 blank salaries and 82 blank 3P%, so the first blank killed the insert. The insert loop went over the column names instead of the rows, the SQL was built with + (which breaks on Shaquille O'Neal), and there was no commit(), so nothing ever saved.

Now it uses %s placeholders and the whole upload is one transaction, so either every row saves or none do. Postgres doesn't allow column names like fg% or 3p, so those are fg_pct, three_p and so on (STAT_COLUMNS in processInput.py has the full list). I also added PF, which was missing, and fixed 9 garbled names in Master.xlsx like Peja Stojaković so the name reveal doesn't look broken.

Justin, for the queries you'll want players.id, players.name, players.selected (starts false) and stats.salary (can be null).

Xavier, send the file to /upload as a form field called file. You get back JSON with ok, message, players_loaded and warnings. If ok is false, message says what went wrong.

## Still need to figure out

Uploading a new file replaces all the players. Dr. Best's whiteboard says "select from datasets already imported," which would need a datasets table, so we should decide that before the queries get too far.

27 players have no salary. Justin and I are thinking an admin option in the UI to either count them as $0 free agents or leave them out. Blank salaries are stored as null either way, so only the UI and salary cap code would change. We still haven't decided about other missing stats, might ask Dr. Best or Esteban.

I used Flask for now since we haven't picked a framework. If we switch, only app.py changes.
