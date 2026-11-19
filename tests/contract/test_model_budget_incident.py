from copy import deepcopy

import pytest

from tutor_api.services.model_cost_gate import incident_validator


def incident():
    return dict(
        schema_version=1,
        attempt_id="a" * 32,
        invocation_id="b" * 32,
        actor_digest="c" * 64,
        budget_key="stu_" + "d" * 32,
        quota_day="2026-11-17",
        reason="estimate_overrun",
        policy="pause_platform",
        reserved_cost_micros=3,
        observed_estimated_cost_micros=5,
        detected_at="2026-11-17T00:00:00Z",
    )


def test_metadata_and_review_pair_are_validated():
    value = incident()
    incident_validator().validate(value)
    value["review_reason"] = "pricing_corrected"
    assert list(incident_validator().iter_errors(value))
    value["reviewed_at"] = "2026-11-17T01:00:00Z"
    incident_validator().validate(value)


@pytest.mark.parametrize(
    "field", ["prompt", "response", "image", "api_key", "endpoint", "student_input"]
)
def test_raw_content_cannot_enter_cost_alert(field):
    value = deepcopy(incident())
    value[field] = "must-not-persist"
    assert list(incident_validator().iter_errors(value))
