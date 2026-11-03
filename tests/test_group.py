
import pytest
from group import Group

@pytest.fixture
def group():
    return Group(1, "First", 123456789, 0)  # id, name, salary_cap, spent

def test_check_overbudget(group):
    assert group.check_in_budget(100000) == True
    assert group.check_in_budget(123456789) == True
    assert group.check_in_budget(99999999999) == False

def test_check_overbudget_neg(group):
    assert group.check_in_budget(-100000) == True

def test_budget_uses_money_left_not_full_cap():
    group = Group(1, "First", 100, 80)  # cap 100, already spent 80
    assert group.remaining == 20
    assert group.check_in_budget(20) == True
    assert group.check_in_budget(21) == False
