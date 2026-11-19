from copy import deepcopy
from pathlib import Path

import pytest

from ai_gateway.invocation_state import InvocationTransitions


@pytest.fixture
def transitions():
    return InvocationTransitions(Path("contracts/model_invocation.schema.json"))


@pytest.fixture
def prepared():
    return dict(
        schema_version=1,
        invocation_id="a" * 32,
        actor_digest="b" * 64,
        budget_key="stu_" + "b" * 32,
        session_digest="c" * 64,
        question_version=1,
        context_generation=0,
        fingerprint="d" * 64,
        context_digest="a" * 64,
        quota_day="2026-11-16",
        fence=1,
        state="prepared",
        attempts=[],
    )


def test_claim_invalidates_old_worker_and_does_not_mutate_snapshot(transitions, prepared):
    original = deepcopy(prepared)
    claimed = transitions.claim(prepared, expected_fence=1)
    assert claimed["fence"] == 2
    assert prepared == original
    with pytest.raises(ValueError):
        transitions.dispatch(
            claimed, expected_fence=1, attempt_id="e" * 32, estimated_cost_micros=3
        )


def test_dispatch_is_unknown_and_cannot_be_reclaimed(transitions, prepared):
    sent = transitions.dispatch(
        prepared, expected_fence=1, attempt_id="e" * 32, estimated_cost_micros=3
    )
    assert sent["state"] == "dispatch_unknown"
    assert sent["attempts"][0]["estimated_cost_micros"] == 3
    for operation in (transitions.claim, transitions.cancel):
        with pytest.raises(ValueError):
            operation(sent, expected_fence=1)
    recovered = transitions.mark_unknown(sent, expected_fence=1)
    assert recovered["state"] == "outcome_unknown"
    assert recovered["quota_day"] == prepared["quota_day"]
    with pytest.raises(ValueError):
        transitions.dispatch(
            recovered, expected_fence=1, attempt_id="f" * 32, estimated_cost_micros=1
        )


def test_only_unsent_work_can_cancel(transitions, prepared):
    result = transitions.cancel(prepared, expected_fence=1)
    assert result["state"] == "cancelled_unsent"
    with pytest.raises(ValueError):
        transitions.claim(result, expected_fence=1)


@pytest.mark.parametrize("cost", [-1, True, 0.5])
def test_dispatch_rejects_invalid_cost(transitions, prepared, cost):
    with pytest.raises(ValueError):
        transitions.dispatch(
            prepared, expected_fence=1, attempt_id="e" * 32, estimated_cost_micros=cost
        )
