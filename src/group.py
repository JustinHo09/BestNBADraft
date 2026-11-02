"""
This represents one instance of a group for the game

"""

class Group:

    def __init__(self,id: int, group_name: str, salary_cap:int, spent:int):
        self.id = id
        self.name = group_name
        self.salary = salary_cap
        self.remaining = salary_cap - spent

    def get_salary(self):
        return self.salary

    def check_in_budget(self, player_salary:int):
        return player_salary <= self.salary

def load_group_data(conn, group_id: int):
    group = conn.execute("SELECT name, salary_cap FROM groups WHERE id = %s", (group_id,)).fetchone()
    name = group[0]
    cap = group[1]

    rows = conn.execute("SELECT s.salary FROM picks p JOIN stats s on s.id = p.player_id "
                            "WHERE p.group_id = %s", (group_id,)).fetchall()
    spent = 0
    for row in rows:
        spent += row[0]

    return Group(group_id,name,cap,spent)


