"""内容审核后台里的证明题：已知、求证、参考证明、按阶段分组的要点都能看、能改，程序校验会把关
（PRD §5"数学解答/证明"：证明前提、逻辑链、分步 Rubric）。"""

from __future__ import annotations

import copy

from support.admin import decide, detail_of, edit, edit_body, make_draft
from support.flows import PROOF, solve
from support.seeds import PROOF_KEYS, qid
from tutor_api.services.content_seed import load_seed

DIFF = "math-ineq-diff-proof"
MONO = "math-mono-def-proof"
MUL = "math-ineq-mul-proof"
ENERGY = "phys-work-energy-proof"


def _seed(key: str) -> dict:
    return next(q for q in load_seed().questions if q["key"] == key)


def _content(detail: dict, **overrides) -> dict:
    return {**copy.deepcopy(detail["content"]), **overrides}


def _answer_with_steps(detail: dict, steps: list[dict]) -> dict:
    return {**detail["answer"], "value": {"steps": steps}}


def test_the_detail_shows_givens_the_claim_the_reference_proof_and_the_checklist(reviewer):
    seed = _seed(DIFF)

    detail = reviewer.data("GET", f"/admin/questions/{qid(DIFF)}")

    assert detail["answer_mode"] == "proof" and detail["type"] == "proof"
    assert detail["content"]["proof"] == seed["content"]["proof"]
    assert detail["answer"]["value"] == seed["answer"]["value"]
    assert detail["rubric"] == {"points": seed["rubric"]["points"]}
    assert detail["teaching"]["leak_markers"] == seed["teaching"]["leak_markers"]
    assert [s["kind"] for s in detail["solutions"]] == ["standard"]
    assert detail["check_problems"] == []


def test_the_queue_lists_the_proof_questions(reviewer):
    page = reviewer.data("GET", "/admin/questions", params={"limit": 50})

    proofs = [item for item in page["items"] if item["answer_mode"] == "proof"]
    assert len(proofs) == len(PROOF_KEYS)
    assert {item["type"] for item in proofs} == {"proof"}


def test_saving_the_unchanged_form_does_not_make_a_new_version(reviewer, db):
    """已知、求证和参考证明原样带回去，和库里的一模一样：没有任何改动，不产生新版本。"""
    question_id = make_draft(db, DIFF)
    detail = detail_of(reviewer, question_id)

    error = edit(reviewer, question_id, edit_body(detail), expect=422)

    assert error["code"] == "no_changes"


def test_editing_the_claim_makes_a_new_version_that_still_passes(reviewer, db):
    question_id = make_draft(db, DIFF)
    before = detail_of(reviewer, question_id)
    proof = {**before["content"]["proof"], "claim": before["content"]["proof"]["claim"] + "（改）"}

    after = edit(reviewer, question_id, edit_body(before, content=_content(before, proof=proof)))

    assert after["version"] == 2
    assert after["content"]["proof"]["claim"].endswith("（改）")
    assert after["content"]["proof"]["givens"] == before["content"]["proof"]["givens"]
    assert after["answer"] == before["answer"]
    assert after["history"][-1]["changes"] == ["content"]
    assert after["check_problems"] == []


def test_adding_a_given_makes_a_new_version(reviewer, db):
    question_id = make_draft(db, MUL)
    before = detail_of(reviewer, question_id)
    proof = {
        **before["content"]["proof"],
        "givens": [*before["content"]["proof"]["givens"], "（改）补一条"],
    }

    after = edit(reviewer, question_id, edit_body(before, content=_content(before, proof=proof)))

    assert after["content"]["proof"]["givens"][-1] == "（改）补一条"
    assert after["check_problems"] == []


def test_editing_a_reference_step_makes_a_new_version_and_keeps_the_order(reviewer, db):
    question_id = make_draft(db, MONO)
    before = detail_of(reviewer, question_id)
    steps = copy.deepcopy(before["answer"]["value"]["steps"])
    steps[1]["reason"] = steps[1]["reason"] + "（改）"

    after = edit(reviewer, question_id, edit_body(before, answer=_answer_with_steps(before, steps)))

    assert after["version"] == 2
    assert after["answer"]["value"]["steps"] == steps
    assert [s["stage"] for s in after["answer"]["value"]["steps"]] == [
        s["stage"] for s in before["answer"]["value"]["steps"]
    ]
    assert after["history"][-1]["changes"] == ["answer"]
    assert after["check_problems"] == []


def test_a_proof_without_a_statement_blocks_approval(reviewer, new_reviewer, db):
    question_id = make_draft(db, ENERGY)
    before = detail_of(reviewer, question_id)

    after = edit(reviewer, question_id, edit_body(before, content=_content(before, proof=None)))

    assert any("content.proof" in problem for problem in after["check_problems"])
    error = decide(new_reviewer(), question_id, "approve", version=2, expect=422)
    assert error["code"] == "content_checks_failed"


def test_a_reference_proof_that_does_not_end_with_a_conclusion_is_flagged(reviewer, db):
    question_id = make_draft(db, DIFF)
    before = detail_of(reviewer, question_id)
    steps = copy.deepcopy(before["answer"]["value"]["steps"])
    steps[-1]["stage"] = "reasoning"

    after = edit(reviewer, question_id, edit_body(before, answer=_answer_with_steps(before, steps)))

    assert any("conclusion" in problem for problem in after["check_problems"])


def test_a_reference_step_without_a_reason_is_flagged(reviewer, db):
    question_id = make_draft(db, MUL)
    before = detail_of(reviewer, question_id)
    steps = copy.deepcopy(before["answer"]["value"]["steps"])
    steps[1]["reason"] = ""

    after = edit(reviewer, question_id, edit_body(before, answer=_answer_with_steps(before, steps)))

    assert any("reason" in problem for problem in after["check_problems"])


def test_a_stage_without_a_checklist_point_is_flagged(reviewer, db):
    question_id = make_draft(db, DIFF)
    before = detail_of(reviewer, question_id)
    points = [p for p in before["rubric"]["points"] if p["part"] != "construction"]

    after = edit(reviewer, question_id, edit_body(before, rubric={"points": points}))

    assert any(
        "rubric.points" in problem and "construction" in problem
        for problem in after["check_problems"]
    )


def test_a_point_that_points_at_a_missing_stage_is_flagged(reviewer, db):
    question_id = make_draft(db, DIFF)
    before = detail_of(reviewer, question_id)
    points = copy.deepcopy(before["rubric"]["points"])
    points[0]["part"] = "intro"

    after = edit(reviewer, question_id, edit_body(before, rubric={"points": points}))

    assert any(
        "rubric.points" in problem and "intro" in problem for problem in after["check_problems"]
    )


def test_a_hint_that_gives_the_key_step_away_is_flagged(reviewer, db):
    """泄题标记是审校员自己列的：提示里写出了标记里的式子，程序校验会发现。"""
    question_id = make_draft(db, DIFF)
    before = detail_of(reviewer, question_id)
    teaching = {
        **before["teaching"],
        "hints": [*before["teaching"]["hints"], "差等于 (a-b)^2/(ab)。"],
    }

    after = edit(reviewer, question_id, edit_body(before, teaching=teaching))

    assert any("可能泄题" in problem for problem in after["check_problems"])


def test_the_old_version_keeps_its_statement_and_its_reference_proof(reviewer, db):
    question_id = make_draft(db, MUL)
    before = detail_of(reviewer, question_id)
    proof = {**before["content"]["proof"], "claim": "（改）求证"}
    steps = copy.deepcopy(before["answer"]["value"]["steps"])
    steps[0]["text"] = "（改）第一步"
    edit(
        reviewer,
        question_id,
        edit_body(
            before,
            content=_content(before, proof=proof),
            answer=_answer_with_steps(before, steps),
        ),
    )

    first = reviewer.data("GET", f"/admin/questions/{question_id}/versions/1")
    second = reviewer.data("GET", f"/admin/questions/{question_id}/versions/2")

    assert first["content"]["proof"] == _seed(MUL)["content"]["proof"]
    assert first["answer"]["value"] == _seed(MUL)["answer"]["value"]
    assert second["content"]["proof"]["claim"] == "（改）求证"
    assert second["answer"]["value"]["steps"][0]["text"] == "（改）第一步"


def test_an_attempt_keeps_the_reference_proof_of_the_version_it_was_made_on(
    onboarded, reviewer, db
):
    """自查取的是会话开始时固定的那个版本：题目之后改过参考证明，不影响已经做完的这份作答。"""
    _, attempt, _ = solve(onboarded, DIFF, PROOF[DIFF])
    question_id = qid(DIFF)
    decide(reviewer, question_id, "withdraw", comment="核对证明")
    before = detail_of(reviewer, question_id)
    steps = copy.deepcopy(before["answer"]["value"]["steps"])
    steps[0]["text"] = "（改）第一步"
    edit(reviewer, question_id, edit_body(before, answer=_answer_with_steps(before, steps)))

    checklist = onboarded.data("GET", f"/attempts/{attempt['id']}/self-check")

    assert checklist["reference_steps"] == _seed(DIFF)["answer"]["value"]["steps"]
    assert checklist["reference_steps"][0]["text"] != "（改）第一步"
