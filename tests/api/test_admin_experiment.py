"""内容审核后台里的实验题：数据表、安全提示、参考数据都能看、能改，程序校验会把关
（PRD §5：审核实验安全提示；高风险实验现在不收录）。"""

from __future__ import annotations

import copy

from support.admin import decide, detail_of, edit, edit_body, make_draft
from support.flows import EXPERIMENT, solve
from support.seeds import EXPERIMENT_KEYS, qid
from tutor_api.services.content_seed import load_seed

TAPE = "phys-tape-experiment"
OHM = "phys-ohm-experiment"
TITRATION = "chem-titration-experiment"


def _seed(key: str) -> dict:
    return next(q for q in load_seed().questions if q["key"] == key)


def _content(detail: dict, **overrides) -> dict:
    return {**copy.deepcopy(detail["content"]), **overrides}


def test_the_detail_shows_tables_safety_notes_reference_data_and_checklist_points(reviewer):
    seed = _seed(TAPE)

    detail = reviewer.data("GET", f"/admin/questions/{qid(TAPE)}")

    assert detail["answer_mode"] == "experiment" and detail["type"] == "experiment"
    assert detail["content"]["data_tables"] == seed["content"]["data_tables"]
    assert detail["content"]["safety"] == seed["content"]["safety"]
    assert detail["answer"]["value"] == seed["answer"]["value"]
    assert detail["rubric"] == {"points": seed["rubric"]["points"]}
    # 审校员补的标记；由参考数据自动推出的那部分不在这里（保存时会跟着新答案重新算）
    assert detail["teaching"]["leak_markers"]
    assert set(detail["teaching"]["leak_markers"]) <= set(seed["teaching"]["leak_markers"])
    assert [s["kind"] for s in detail["solutions"]] == ["standard"]
    assert detail["check_problems"] == []


def test_the_queue_lists_the_experiment_questions(reviewer):
    page = reviewer.data("GET", "/admin/questions", params={"limit": 50})

    experiments = [item for item in page["items"] if item["answer_mode"] == "experiment"]
    assert len(experiments) == len(EXPERIMENT_KEYS)
    assert {item["type"] for item in experiments} == {"experiment"}


def test_saving_the_unchanged_form_does_not_make_a_new_version(reviewer, db):
    """表和安全提示原样带回去，和库里的一模一样：没有任何改动，不产生新版本。"""
    question_id = make_draft(db, TAPE)
    detail = detail_of(reviewer, question_id)

    error = edit(reviewer, question_id, edit_body(detail), expect=422)

    assert error["code"] == "no_changes"


def test_editing_a_given_value_in_a_table_makes_a_new_version_that_still_passes(reviewer, db):
    question_id = make_draft(db, TAPE)
    before = detail_of(reviewer, question_id)
    tables = copy.deepcopy(before["content"]["data_tables"])
    tables[0]["rows"][0]["cells"][1]["text"] = "4.10"  # 第一段的距离

    after = edit(
        reviewer, question_id, edit_body(before, content=_content(before, data_tables=tables))
    )

    assert after["version"] == 2
    assert after["content"]["data_tables"][0]["rows"][0]["cells"][1]["text"] == "4.10"
    assert after["content"]["safety"] == before["content"]["safety"]
    assert after["answer"] == before["answer"]
    assert after["history"][-1]["changes"] == ["content"]
    assert after["check_problems"] == []


def test_editing_the_safety_notes_makes_a_new_version(reviewer, db):
    question_id = make_draft(db, OHM)
    before = detail_of(reviewer, question_id)
    safety = {
        **before["content"]["safety"],
        "notes": [*before["content"]["safety"]["notes"], "（改）补一条"],
    }

    after = edit(reviewer, question_id, edit_body(before, content=_content(before, safety=safety)))

    assert after["content"]["safety"]["notes"][-1] == "（改）补一条"
    assert after["history"][-1]["changes"] == ["content"]
    assert after["check_problems"] == []


def test_an_experiment_without_safety_notes_blocks_approval(reviewer, new_reviewer, db):
    question_id = make_draft(db, TITRATION)
    before = detail_of(reviewer, question_id)

    after = edit(reviewer, question_id, edit_body(before, content=_content(before, safety=None)))

    assert any("safety" in problem for problem in after["check_problems"])
    error = decide(new_reviewer(), question_id, "approve", version=2, expect=422)
    assert error["code"] == "content_checks_failed"


def test_a_high_risk_experiment_is_flagged_and_cannot_be_approved(reviewer, new_reviewer, db):
    question_id = make_draft(db, TITRATION)
    before = detail_of(reviewer, question_id)
    safety = {**before["content"]["safety"], "level": "high"}

    after = edit(reviewer, question_id, edit_body(before, content=_content(before, safety=safety)))

    assert any("high" in problem and "不收录" in problem for problem in after["check_problems"])
    error = decide(new_reviewer(), question_id, "approve", version=2, expect=422)
    assert error["code"] == "content_checks_failed"


def test_turning_a_blank_cell_into_given_data_leaves_a_dangling_reference(reviewer, db):
    question_id = make_draft(db, TAPE)
    before = detail_of(reviewer, question_id)
    tables = copy.deepcopy(before["content"]["data_tables"])
    tables[0]["rows"][0]["cells"][2]["text"] = "0.400"  # 原来留空，现在给出了

    after = edit(
        reviewer, question_id, edit_body(before, content=_content(before, data_tables=tables))
    )

    assert any("answer.value" in problem for problem in after["check_problems"])


def test_a_table_row_that_misses_a_column_is_flagged(reviewer, db):
    question_id = make_draft(db, OHM)
    before = detail_of(reviewer, question_id)
    tables = copy.deepcopy(before["content"]["data_tables"])
    tables[0]["rows"][1]["cells"].pop()

    after = edit(
        reviewer, question_id, edit_body(before, content=_content(before, data_tables=tables))
    )

    assert any("cells" in problem for problem in after["check_problems"])


def test_a_reference_value_that_is_missing_is_flagged(reviewer, db):
    question_id = make_draft(db, OHM)
    before = detail_of(reviewer, question_id)
    value = dict(before["answer"]["value"])
    del value["t1.r1.r"]

    after = edit(
        reviewer, question_id, edit_body(before, answer={**before["answer"], "value": value})
    )

    assert any("answer.value" in problem for problem in after["check_problems"])


def test_a_hint_that_gives_a_reference_value_away_is_flagged_after_the_answer_changes(reviewer, db):
    """泄题标记跟着新答案重新算：改了参考值之后，提示里出现新的参考值也会被发现。"""
    question_id = make_draft(db, TAPE)
    before = detail_of(reviewer, question_id)
    value = {**before["answer"]["value"], "t2.r1.val": "3.14"}
    teaching = {**before["teaching"], "hints": [*before["teaching"]["hints"], "结果大约是 3.14。"]}

    after = edit(
        reviewer,
        question_id,
        edit_body(before, answer={**before["answer"], "value": value}, teaching=teaching),
    )

    assert any("可能泄题" in problem for problem in after["check_problems"])


def test_the_old_version_keeps_its_tables_and_its_reference_data(reviewer, db):
    question_id = make_draft(db, TAPE)
    before = detail_of(reviewer, question_id)
    tables = copy.deepcopy(before["content"]["data_tables"])
    tables[0]["rows"][0]["cells"][1]["text"] = "4.10"
    value = {**before["answer"]["value"], "t1.r1.v": "0.410"}
    edit(
        reviewer,
        question_id,
        edit_body(
            before,
            content=_content(before, data_tables=tables),
            answer={**before["answer"], "value": value},
        ),
    )

    first = reviewer.data("GET", f"/admin/questions/{question_id}/versions/1")
    second = reviewer.data("GET", f"/admin/questions/{question_id}/versions/2")

    assert first["content"]["data_tables"][0]["rows"][0]["cells"][1]["text"] == "4.00"
    assert first["answer"]["value"]["t1.r1.v"] == "0.400"
    assert second["content"]["data_tables"][0]["rows"][0]["cells"][1]["text"] == "4.10"
    assert second["answer"]["value"]["t1.r1.v"] == "0.410"
    assert first["content"]["safety"] == second["content"]["safety"]


def test_an_attempt_keeps_the_reference_data_of_the_version_it_was_made_on(onboarded, reviewer, db):
    """自查取的是会话开始时固定的那个版本：题目之后改过参考数据，不影响已经做完的这份作答。"""
    _, attempt, _ = solve(onboarded, TAPE, EXPERIMENT[TAPE])
    question_id = qid(TAPE)
    decide(reviewer, question_id, "withdraw", comment="核对数据")
    before = detail_of(reviewer, question_id)
    value = {**before["answer"]["value"], "t1.r1.v": "0.410"}
    tables = copy.deepcopy(before["content"]["data_tables"])
    tables[0]["rows"][0]["cells"][1]["text"] = "4.10"
    edit(
        reviewer,
        question_id,
        edit_body(
            before,
            content=_content(before, data_tables=tables),
            answer={**before["answer"], "value": value},
        ),
    )

    checklist = onboarded.data("GET", f"/attempts/{attempt['id']}/self-check")

    first = next(c for c in checklist["reference_cells"] if (c["table"], c["row"]) == ("t1", "r1"))
    assert first["value"] == "0.400"
