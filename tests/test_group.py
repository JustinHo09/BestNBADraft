
import pytest
from group import Group

@pytest.fixture
def group():
    return Group("First", 123456789)

def test_check_overbudget(group):
    assert group.check_in_budget(100000) == True
    assert group.check_in_budget(123456789) == True
    assert group.check_in_budget(99999999999) == False

def test_check_overbudget_neg(group):
    assert group.check_in_budget(-100000) == True