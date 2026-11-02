# Player lock: once a player is drafted (players.selected = TRUE) nobody else can pick him.


class PlayerNotFoundError(Exception):
    pass


class PlayerAlreadyLockedError(Exception):
    pass

class GameOverError(Exception):
    pass

MIN_GROUP_SIZE = 3
MAX_GROUP_SIZE = 5
NUM_ROUNDS = 10

def lock_player(conn, player_id):
    # only works if nobody picked him yet, so 2 teams can't both get him
    locked = conn.execute(
        "UPDATE players SET selected = TRUE WHERE id = %s AND selected = FALSE RETURNING id",
        (player_id,),
    ).fetchone()
    if locked is None:
        is_locked(conn, player_id)  # raises PlayerNotFoundError if the id doesn't exist
        raise PlayerAlreadyLockedError(f"Player {player_id} has already been drafted.")


def is_locked(conn, player_id):
    row = conn.execute("SELECT selected FROM players WHERE id = %s", (player_id,)).fetchone()
    if row is None:
        raise PlayerNotFoundError(f"No player with ID {player_id}.")
    return row[0]

def get_player_salary(conn, player_id):
    salary = conn.execute("SELECT salary FROM stats WHERE id = %s", (player_id,)).fetchone()
    if salary is None:
        raise PlayerNotFoundError(f"No player with ID {player_id}.")
    return salary[0]

# This is just the basic beginning of a turn eventually we will need to keep track of actions for undo,
# and if we plan to make turns a while loop or not.
def turn(conn, player_id, group):
    if not is_locked(conn, player_id):
        if group.add_player(player_id, get_player_salary(conn, player_id)):
            lock_player(conn, player_id)
        else:
            print("BROKE BROKE BROKE NOT ENOUGH MONEY TO BUY THIS PLAYER")

def seat_pick(pick_number, num_groups):
    if 0 < pick_number and 2 < num_groups < 6:
        group = (pick_number-1) % num_groups + 1
        round = (pick_number-1) // num_groups + 1
        return group, round
    return -1,-1

# Changes None or Null in the database to be N/A like Dr.Best requested
def na(value):
    if value is None:
        return "N/A"
    if isinstance(value, str) and value.strip() == "":
        return "N/A"
    return value

def set_up_draft(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS groups "
                 "( id SERIAL PRIMARY KEY,"
                 "name TEXT NOT NULL,"
                 "seat INTEGER NOT NULL UNIQUE,"
                 "salary_cap INTEGER NOT NULL "
                 ")")

    conn.execute("CREATE TABLE IF NOT EXISTS current_state ("
                 "id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
                 "current_pick INTEGER NOT NULL DEFAULT 1,"
                 "num_rounds INTEGER NOT NULL DEFAULT 10"
                 ")")

    conn.execute("CREATE TABLE IF NOT EXISTS picks ("
                 "pick_number INTEGER PRIMARY KEY,"
                 "round INTEGER NOT NULL,"
                 "group_id INTEGER NOT NULL REFERENCES groups (id),"
                 "player_id INTEGER NOT NULL UNIQUE REFERENCES players (id)"
                 ")")

    conn.execute("TRUNCATE TABLE groups, picks, current_state RESTART IDENTITY CASCADE")

def new_draft(conn, group_names, salary_cap):
    if MIN_GROUP_SIZE <= len(group_names) <= MAX_GROUP_SIZE and salary_cap > 0:
        conn.execute("TRUNCATE TABLE groups, picks, current_state RESTART IDENTITY CASCADE")
        conn.execute('UPDATE players SET selected = False')

        i=1
        for group in group_names:
            conn.execute('INSERT INTO groups (name, seat, salary_cap) VALUES (%s, %s, %s)', (group,i, salary_cap))
            i+=1
        conn.execute('INSERT INTO current_state (current_pick) VALUES (%s)',(1,))

def current_pick(conn):
    current_pick = conn.execute("SELECT current_pick FROM current_state").fetchone()[0]
    num_groups = conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
    if current_pick > num_groups * NUM_ROUNDS:
        raise GameOverError

    current_seat, current_round = seat_pick(current_pick, num_groups)
    current_group = conn.execute("SELECT id FROM groups WHERE seat = %s", (current_seat,)).fetchone()[0]
    return {"pick_number": current_pick,"round": current_round,"group": current_group}


