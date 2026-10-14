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
