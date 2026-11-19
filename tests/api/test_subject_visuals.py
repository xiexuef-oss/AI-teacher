"""New fixed diagrams inherit SEC304 and subjective pending semantics."""

import pytest

from support.flows import PROOF, begin, choice, submit, tutor

CASES = [
    ("chem-process-reading", "chemical_process", choice("B")),
    (
        "math-triangle-coordinate-proof",
        "triangle_schematic",
        PROOF["math-triangle-coordinate-proof"],
    ),
]


@pytest.mark.parametrize("key,template,answer", CASES)
def test_new_diagrams_do_not_release_specs_even_with_visual_confirmation(
    onboarded, key, template, answer
):
    session, _ = begin(onboarded, key)
    step = tutor(onboarded, session["id"], "request_visual", confirm_end_independent=True)
    assert step["events"]
    assert all(event["type"] == "notice" for event in step["events"])
    assert not step["session"]["used_solution"]
    assert not step["session"]["independent_ended"]
    for event in step["events"]:
        assert not {"template_id", "params", "caption", "static_fallback"} & event["payload"].keys()


@pytest.mark.parametrize("key,template,answer", CASES)
def test_explicit_solution_then_new_diagram_is_available(onboarded, key, template, answer):
    session, _ = begin(onboarded, key)
    step = tutor(onboarded, session["id"], "request_standard", confirm_end_independent=True)
    assert step["session"]["used_solution"]
    visual = tutor(onboarded, session["id"], "request_visual")
    assert visual["events"][0]["payload"]["template_id"] == template
    assert visual["session"]["used_solution"]


@pytest.mark.parametrize("key,template,answer", CASES)
def test_submitted_new_diagram_preserves_objective_and_pending_rules(
    onboarded, key, template, answer
):
    session, attempt = begin(onboarded, key)
    result = submit(onboarded, attempt["id"], answer)
    if "proof" in key:
        assert result["evaluation"]["state"] == "pending"
        assert result["evaluation"]["is_correct"] is None
    else:
        assert result["evaluation"]["outcome"] == "correct"
    assert result["evaluation"]["independent"]
    visual = tutor(onboarded, session["id"], "request_visual")
    assert visual["events"][0]["payload"]["template_id"] == template
    assert not visual["session"]["used_solution"]
