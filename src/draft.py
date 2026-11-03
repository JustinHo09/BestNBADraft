# Player lock: once a player is drafted (players.selected = TRUE) nobody else can pick him.


class PlayerNotFoundError(Exception):
    pass


class PlayerAlreadyLockedError(Exception):
    pass

class GameOverError(Exception):
    pass

class PickAlreadyMadeError(Exception):
    pass

class NoSalaryError(Exception):
    pass

class OverBudgetError(Exception):
    pass

class NoPickError(Exception):
    pass

class NoDraftError(Exception):
    pass

MIN_GROUP_SIZE = 3
MAX_GROUP_SIZE = 5
NUM_ROUNDS = 10

from group import load_group_data

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
    else:
        # before this it just did nothing, so the board got stuck with no draft and no error
        raise ValueError(f"Need {MIN_GROUP_SIZE}-{MAX_GROUP_SIZE} groups and a salary cap above 0.")

def current_pick(conn):
    row = conn.execute("SELECT current_pick FROM current_state").fetchone()
    if row is None:  # new_draft hasn't been run yet
        raise NoDraftError("No draft has been started yet.")
    current_pick = row[0]
    num_groups = conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
    if current_pick > num_groups * NUM_ROUNDS:
        raise GameOverError

    current_seat, current_round = seat_pick(current_pick, num_groups)
    current_group = conn.execute("SELECT id FROM groups WHERE seat = %s", (current_seat,)).fetchone()[0]
    return {"pick_number": current_pick,"round": current_round,"group": current_group}

def continue_turn(conn):
    turn = current_pick(conn)
    picked = conn.execute( "SELECT 1 FROM picks WHERE pick_number = %s",(turn["pick_number"],)).fetchone()
    if picked is None:
        raise NoPickError("No pick has been made this turn")
    conn.execute("UPDATE current_state SET current_pick = current_pick + 1")

def make_pick(conn, player_id):
    turn = current_pick(conn)

    already = conn.execute("SELECT 1 FROM picks where pick_number = %s", (turn["pick_number"],)).fetchone()
    if already is not None:
        raise PickAlreadyMadeError("This a pick has already been made this turn")

    salary = get_player_salary(conn, player_id)

    if salary is None:
        raise NoSalaryError("No salary for this player so they can't be drafted")

    # current_pick returns the group as "group", not "group_id" (that was causing a KeyError)
    group = load_group_data(conn, turn["group"])
    if not group.check_in_budget(salary):
        raise OverBudgetError("This player can't be drafted too broke")

    lock_player(conn, player_id)
    conn.execute("INSERT INTO picks VALUES (%s, %s, %s, %s)",
                 (turn["pick_number"], turn["round"], turn["group"], player_id),)

    return turn

# everything the board needs in one call
# added seat and salary_cap for each group, pick_number, player_id and salary for each pick,
# and who is on the clock plus whether they picked yet
def get_draft_data(conn):
    groups = []
    for row in conn.execute("SELECT id, name, seat, salary_cap FROM groups ORDER BY seat").fetchall():
        group = load_group_data(conn, row[0])
        groups.append({"id": row[0], "name": row[1], "seat": row[2], "salary_cap": row[3],
                       "money_left": group.remaining})

    picks = []
    rows = conn.execute("SELECT p.round, g.seat, pl.name, s.position, s.team, p.pick_number, p.player_id, s.salary "
                        "FROM picks p JOIN groups g ON g.id = p.group_id "
                        "JOIN players pl ON p.player_id = pl.id "
                        "JOIN stats s ON s.id = p.player_id "
                        "ORDER BY p.pick_number").fetchall()
    for row in rows:
        picks.append({"round":row[0], "seat":row[1], "name":row[2], "position": na(row[3]),"team":na(row[4]),
                      "pick_number": row[5], "player_id": row[6], "salary": row[7]})

    pick_number, group_name, pick_made = None, None, False
    try:
        turn = current_pick(conn)
        seat, round = seat_pick(turn["pick_number"], len(groups))
        pick_number = turn["pick_number"]
        group_name = next(g["name"] for g in groups if g["id"] == turn["group"])
        pick_made = any(p["pick_number"] == pick_number for p in picks)
    except GameOverError:
        seat, round = None,None
    return {"groups":groups, "picks":picks, "seat":seat, "round":round,
            "pick_number": pick_number, "group_name": group_name, "pick_made": pick_made,
            "num_rounds": NUM_ROUNDS, "is_over": seat is None}


# undrafted players for the list on the board
# no names since it's a blind draft, the name only shows up after the ID is typed in
def get_available_players(conn, limit=500):
    rows = conn.execute("SELECT p.id, s.position, s.g, s.pts, s.trb, s.ast, s.fg_pct, s.salary "
                        "FROM players p JOIN stats s ON s.id = p.id "
                        "WHERE p.selected = FALSE "
                        "ORDER BY s.pts DESC NULLS LAST, p.id LIMIT %s", (limit,)).fetchall()
    return [{"id": r[0], "position": na(r[1]), "g": r[2], "pts": r[3], "trb": r[4], "ast": r[5],
             "fg_pct": r[6], "salary": r[7]} for r in rows]