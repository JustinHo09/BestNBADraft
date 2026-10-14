"""
This represents one instance of a group for the game

"""

class Group:

    def __init__(self,group_name: str, salary_cap:int):
        self.name = group_name
        self.salary = salary_cap
        self.players = []

    def get_salary(self):
        return self.salary

    def reduce_salary(self, change: int):
        self.salary -= change

    def increase_salary(self, change: int):
        self.salary += change

    def check_overbudget(self, player_salary:int):
        if player_salary > self.salary:
            # Temporary test print
            print("BROKE ALERT, TOO BROKE TO BUY THIS PLAYER")
            return True
        else:
            return False

    def add_player(self, player_id:int, player_salary:int):
        # Returns T/F to indicate weather or not it was successful draft.
        if not self.check_overbudget(player_salary):
            self.players.append(player_id)
            self.salary -= player_salary
            return True
        else:
            return False

    def remove_player(self, player_id:int, player_salary:int):
        self.players.remove(player_id)
        self.salary += player_salary

