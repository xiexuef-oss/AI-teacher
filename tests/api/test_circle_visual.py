import pytest

from support.flows import begin, submit, tutor

KEY = "math-circle-radius-proof"


@pytest.mark.parametrize("submitted", [False, True])
def test_circle_visual_phase_gate_and_proof_remains_pending(onboarded, submitted):
    session, attempt = begin(onboarded, KEY)
    if submitted:
        result = submit(
            onboarded,
            attempt["id"],
            {
                "steps": [{"text": "我使用题设的圆方程进行比较", "reason": ""}],
            },
        )
        assert result["evaluation"]["state"] == "pending"
        assert result["evaluation"]["is_correct"] is None
    response = tutor(onboarded, session["id"], "request_visual")
    visuals = [e for e in response["events"] if e["type"] == "visual"]
    assert bool(visuals) is submitted
    if submitted:
        assert visuals[0]["payload"]["template_id"] == "circle_schematic"
        assert result["review_item"] is None
    else:
        assert all(
            not {"template_id", "params", "caption", "static_fallback"} & e["payload"].keys()
            for e in response["events"]
        )
    assert response["session"]["used_solution"] is False


def test_circle_visual_requires_explicit_solution_to_end_independent_stage(onboarded):
    session, _ = begin(onboarded, KEY)
    blocked = tutor(onboarded, session["id"], "request_visual", confirm_end_independent=True)
    assert all(e["type"] != "visual" for e in blocked["events"])
    assert blocked["session"]["used_solution"] is False
    solution = tutor(onboarded, session["id"], "request_standard", confirm_end_independent=True)
    assert solution["session"]["used_solution"] is True
    visual = tutor(onboarded, session["id"], "request_visual")
    assert any(
        e["type"] == "visual" and e["payload"]["template_id"] == "circle_schematic"
        for e in visual["events"]
    )
