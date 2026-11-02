# Player lock: once a player is drafted (players.selected = TRUE) nobody else can pick him.


class PlayerNotFoundError(Exception):
    pass


class PlayerAlreadyLockedError(Exception):
    pass


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