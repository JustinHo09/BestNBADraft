import pandas as pd
# SQLite is temporary for now will need to probably switch to Postgres this will be for basic testing
import sqlite3

def main():
    readFile()

def readFile(filename):
    df =[]
    if(filename.endswith(".csv")):
        df = pd.read_csv(filename)
    elif(filename.endswith(".xlsx")):
        df = pd.read_excel(filename)
    else:
        return 'Error Not a supported file type. Must be .csv or .xlsx'

    identities = df.loc[:,2]

    anonymous_stats = df.drop(columns = ['Player'])

    set_up_db(identities, anonymous_stats)

def set_up_db(players, stats):
    conn = sqlite3.connect('test.db')
    cursor = conn.cursor()
    # Create the first table of player and is mapping this uses the Postgres convention of BOOLEAN
    create_table_id =("CREATE TABLE IF NOT EXISTS players id INTEGER PRIMARY KEY,"
                      " name VARCHAR(50) NOT NULL, "
                      "selected BOOLEAN NOT NULL DEFAULT FALSE")
    cursor.execute(create_table_id)

    # Create the second table of the hidden player id and stats
    create_table_stats = ("CREATE TABLE IF NOT EXISTS stats "
                          "id INTEGER FOREIGN KEY NOT NULL,"
                          "team VARCHAR(50) NOT NULL,"
                          "position VARCHAR(50) NOT NULL,"
                          "g INTEGER NOT NULL,"
                          "gs INTEGER NOT NULL,"
                          "mp INTEGER NOT NULL,"
                          "fg INTEGER NOT NULL,"
                          "fga INTEGER NOT NULL,"
                          "fg% FLOAT NOT NULL,"
                          "3p INTEGER NOT NULL,"
                          "3pa INTEGER NOT NULL,"
                          "3p% FLOAT NOT NULL,"
                          "2p INTEGER NOT NULL,"
                          "2pa INTEGER NOT NULL,"
                          "2p% FLOAT NOT NULL,"
                          "eFG% FLOAT NOT NULL,"
                          "FT INTEGER NOT NULL,"
                          "FTA INTEGER NOT NULL,"
                          "FT% FLOAT NOT NULL,"
                          "ORB INTEGER NOT NULL,"
                          "DRB INTEGER NOT NULL,"
                          "TRB INTEGER NOT NULL,"
                          "AST INTEGER NOT NULL,"
                          "STL INTEGER NOT NULL,"
                          "BLK INTEGER NOT NULL,"
                          "TOV INTEGER NOT NULL,"
                          "PTS INTEGER NOT NULL,"
                          "Salary INTEGER NOT NULL,"
                          "(id) REFERENCES players ")

    for player in players:
        insert_players(player,cursor)

    for stat in stats:
        insert_stats(stat,cursor)

def insert_players(player,db_cursor):
    insert_player_query = ("INSERT INTO players VALUES("+ player + ")")
    db_cursor.execute(insert_player_query)

def insert_stats(stat, db_cursor):
    insert_player_stat_query = ("INSERT INTO stats VALUES("+ stat + ")")
    db_cursor.execute(insert_player_stat_query)