from tutor_api.services.learning_budget import remaining_minutes


def test_school_work_reduces_the_available_budget():
    assert remaining_minutes(50, 35) == 15


def test_zero_budget_or_excess_school_work_leaves_no_extra_practice():
    assert remaining_minutes(0, 0) == 0
    assert remaining_minutes(30, 45) == 0
