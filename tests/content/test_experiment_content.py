"""实验题样题的内容校验（PRD §5：审核实验安全提示；Q-05、Q-06）。

样题没有经过学科审校，这里能保证的是：结构自洽（数据表、安全提示、参考值、自查要点互相对得上）、
不泄题、不收录高风险实验、不冒充真题，以及参考数据与从题设独立重算的结果一致。
"""

from __future__ import annotations

import copy
import math

import pytest

from tutor_api.services.content_seed import SeedBundle, leak_markers, load_seed, validate_seed

TAPE = "phys-tape-experiment"
OHM = "phys-ohm-experiment"
TITRATION = "chem-titration-experiment"
EXPERIMENT_KEYS = (TAPE, OHM, TITRATION)


@pytest.fixture(scope="module")
def bundle() -> SeedBundle:
    return load_seed()


def _by_key(bundle: SeedBundle) -> dict[str, dict]:
    return {q["key"]: q for q in bundle.questions}


def _mutated(bundle: SeedBundle, key: str, mutate) -> SeedBundle:
    clone = copy.deepcopy(bundle)
    mutate(_by_key(clone)[key])
    return clone


def _table(question: dict, key: str) -> dict:
    return next(table for table in question["content"]["data_tables"] if table["key"] == key)


def _given(question: dict, table: str, row: str, col: str) -> str | None:
    row_data = next(r for r in _table(question, table)["rows"] if r["key"] == row)
    return next(cell["text"] for cell in row_data["cells"] if cell["col"] == col)


def _reference(question: dict, table: str, row: str, col: str) -> str:
    return question["answer"]["value"][f"{table}.{row}.{col}"]


# ---------------------------------------------------------------- 整体


def test_the_experiment_samples_are_valid(bundle):
    assert validate_seed(bundle) == []


def test_there_are_experiment_samples_for_physics_and_chemistry(bundle):
    experiments = {q["key"]: q for q in bundle.questions if q["answer_mode"] == "experiment"}

    assert set(experiments) == set(EXPERIMENT_KEYS)
    assert {q["subject"] for q in experiments.values()} == {"physics", "chemistry"}
    assert {q["type"] for q in experiments.values()} == {"experiment"}
    # 都是通用题，没有地区标签
    assert all(not q.get("region_tags") for q in experiments.values())


@pytest.mark.parametrize("key", EXPERIMENT_KEYS)
def test_every_experiment_has_safety_notes_and_is_not_high_risk(bundle, key):
    safety = _by_key(bundle)[key]["content"]["safety"]

    assert safety["level"] in ("low", "medium")
    assert 1 <= len(safety["notes"]) <= 8
    # 都说明了这是纸面练习，不是操作指导
    assert any("不是操作指导" in note for note in safety["notes"])


@pytest.mark.parametrize("key", EXPERIMENT_KEYS)
def test_every_blank_cell_has_a_reference_value_and_nothing_else_does(bundle, key):
    question = _by_key(bundle)[key]
    blank_cells = {
        f"{table['key']}.{row['key']}.{cell['col']}"
        for table in question["content"]["data_tables"]
        for row in table["rows"]
        for cell in row["cells"]
        if cell["text"] is None
    }
    part_keys = {sub["key"] for sub in question["content"]["subquestions"]}

    assert blank_cells
    assert set(question["answer"]["value"]) == blank_cells | part_keys


@pytest.mark.parametrize("key", EXPERIMENT_KEYS)
def test_the_checklist_covers_every_subquestion_and_every_table_with_blanks(bundle, key):
    question = _by_key(bundle)[key]
    points = question["rubric"]["points"]
    parts = {p["part"] for p in points}
    wanted = {sub["key"] for sub in question["content"]["subquestions"]}
    wanted |= {
        table["key"]
        for table in question["content"]["data_tables"]
        if any(cell["text"] is None for row in table["rows"] for cell in row["cells"])
    }

    assert wanted <= parts
    assert all(set(p) == {"key", "part", "text"} for p in points)  # 不带分值


@pytest.mark.parametrize("key", EXPERIMENT_KEYS)
def test_numeric_reference_values_become_leak_markers(bundle, key):
    question = _by_key(bundle)[key]
    markers = leak_markers(question)

    for cell_key, value in question["answer"]["value"].items():
        if cell_key.count(".") == 2 and len(value) >= 3:
            assert value in markers, cell_key
    # 题目自己列的文字标记也在
    assert set(question["teaching"]["leak_markers"]) <= set(markers)


@pytest.mark.parametrize("key", EXPERIMENT_KEYS)
def test_no_hint_gives_a_reference_value_away(bundle, key):
    question = _by_key(bundle)[key]
    values = [
        value for cell_key, value in question["answer"]["value"].items() if cell_key.count(".") == 2
    ]
    for hint in question["teaching"]["hints"]:
        assert not any(value in hint for value in values), hint


# ---------------------------------------------------------------- 独立重算


def test_tape_data_reference_values_match_independent_recomputation(bundle):
    question = _by_key(bundle)[TAPE]
    period = 5 / 50  # 频率 50 Hz，相邻计数点之间隔了 5 个打点周期
    distances = {
        row: float(_given(question, "t1", row, "x")) / 100  # cm → m
        for row in ("r1", "r2", "r3", "r4")
    }

    for row, distance in distances.items():
        assert float(_reference(question, "t1", row, "v")) == pytest.approx(
            distance / period, rel=1e-3
        )
    steps = [distances[r] for r in ("r1", "r2", "r3", "r4")]
    # 题设是匀加速：相邻位移之差相等
    assert [round(b - a, 6) for a, b in zip(steps, steps[1:], strict=False)] == [0.02] * 3
    acceleration = ((steps[2] + steps[3]) - (steps[0] + steps[1])) / (4 * period**2)
    assert float(_reference(question, "t2", "r1", "val")) == pytest.approx(acceleration, rel=1e-3)
    assert acceleration == pytest.approx(2.0)


def test_ohm_data_reference_values_match_independent_recomputation(bundle):
    question = _by_key(bundle)[OHM]
    resistances = []
    for row in ("r1", "r2", "r3", "r4", "r5"):
        voltage = float(_given(question, "t1", row, "u"))
        current = float(_given(question, "t1", row, "i")) / 1000  # mA → A
        resistances.append(voltage / current)
        assert float(_reference(question, "t1", row, "r")) == pytest.approx(
            voltage / current, abs=0.05
        )
    mean = sum(resistances) / len(resistances)
    assert float(_reference(question, "t2", "r1", "val")) == pytest.approx(mean, abs=0.05)

    # 内接还是外接：R_x 比 sqrt(R_A·R_V) 大就内接。题设 R_A=0.5 Ω，R_V=3 kΩ
    assert mean**2 > 0.5 * 3000
    assert "内接" in question["answer"]["value"]["1"]
    assert "偏大" in question["answer"]["value"]["2"]


def test_titration_data_reference_values_match_independent_recomputation(bundle):
    question = _by_key(bundle)[TITRATION]
    volumes = []
    for row in ("r1", "r2", "r3"):
        volume = float(_given(question, "t1", row, "v1")) - float(_given(question, "t1", row, "v0"))
        volumes.append(volume)
        assert float(_reference(question, "t1", row, "dv")) == pytest.approx(volume, abs=0.005)
    mean = sum(volumes) / len(volumes)
    assert max(volumes) - min(volumes) < 0.1  # 三次接近，没有要舍去的
    assert float(_reference(question, "t2", "r1", "val")) == pytest.approx(mean, abs=0.005)

    # HCl + NaOH = NaCl + H2O，1:1；c(HCl) = c(NaOH)·V(NaOH)/V(HCl)
    concentration = 0.1000 * mean / 20.00
    assert float(_reference(question, "t2", "r2", "val")) == pytest.approx(concentration, abs=5e-5)
    assert math.isclose(concentration, 0.1004, abs_tol=5e-5)


# ---------------------------------------------------------------- 校验器抓得住问题


def _set(path: list, value):
    def mutate(question: dict) -> None:
        node = question
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value

    return mutate


def _delete(path: list):
    def mutate(question: dict) -> None:
        node = question
        for part in path[:-1]:
            node = node[part]
        del node[path[-1]]

    return mutate


def _append(path: list, value):
    def mutate(question: dict) -> None:
        node = question
        for part in path:
            node = node[part]
        node.append(value)

    return mutate


def _drop_points_for(part: str):
    def mutate(question: dict) -> None:
        question["rubric"]["points"] = [
            point for point in question["rubric"]["points"] if point["part"] != part
        ]

    return mutate


def _no_blanks_and_no_subquestions(question: dict) -> None:
    question["content"]["subquestions"] = []
    for table in question["content"]["data_tables"]:
        for row in table["rows"]:
            for cell in row["cells"]:
                if cell["text"] is None:
                    cell["text"] = "1"
    question["answer"]["value"] = {}


BROKEN = {
    # ---- 安全提示
    "实验题没有安全提示": (TAPE, _set(["content", "safety"], None), "safety"),
    "安全提示缺了说明": (TAPE, _delete(["content", "safety", "notes"]), "safety"),
    "安全提示是空的": (TAPE, _set(["content", "safety", "notes"], []), "safety.notes"),
    "安全提示有空话": (TAPE, _set(["content", "safety", "notes", 0], "  "), "safety.notes"),
    "高风险实验不收录": (TITRATION, _set(["content", "safety", "level"], "high"), "high"),
    "风险等级无效": (TITRATION, _set(["content", "safety", "level"], "none"), "level"),
    # ---- 数据表
    "表的键重复": (TAPE, _set(["content", "data_tables", 1, "key"], "t1"), "data_tables"),
    "表的键含点": (TAPE, _set(["content", "data_tables", 0, "key"], "t.1"), "data_tables"),
    "表没有标题": (TAPE, _set(["content", "data_tables", 0, "title"], ""), "title"),
    "表没有列": (TAPE, _set(["content", "data_tables", 0, "columns"], []), "columns"),
    "列的键重复": (
        TAPE,
        _set(["content", "data_tables", 0, "columns", 1, "key"], "seg"),
        "columns",
    ),
    "列没有标签": (TAPE, _set(["content", "data_tables", 0, "columns", 0, "label"], ""), "label"),
    "表没有行": (TAPE, _set(["content", "data_tables", 0, "rows"], []), "rows"),
    "行的键重复": (TAPE, _set(["content", "data_tables", 0, "rows", 1, "key"], "r1"), "rows"),
    "行少了一个格子": (
        TAPE,
        _set(["content", "data_tables", 0, "rows", 0, "cells"], [{"col": "seg", "text": "AB"}]),
        "cells",
    ),
    "行里的格子指向不存在的列": (
        TAPE,
        _set(["content", "data_tables", 0, "rows", 0, "cells", 0, "col"], "zz"),
        "cells",
    ),
    "格子带了多余的字段": (
        TAPE,
        _set(["content", "data_tables", 0, "rows", 0, "cells", 0, "weight"], 1),
        "cells",
    ),
    "给定的格子是空白字符": (
        TAPE,
        _set(["content", "data_tables", 0, "rows", 0, "cells", 1, "text"], "  "),
        "格子",
    ),
    "给定的格子太长": (
        TAPE,
        _set(["content", "data_tables", 0, "rows", 0, "cells", 1, "text"], "9" * 41),
        "格子",
    ),
    "太多张表": (
        TAPE,
        lambda q: q["content"]["data_tables"].extend(
            copy.deepcopy(q["content"]["data_tables"][0]) | {"key": f"x{i}"} for i in range(4)
        ),
        "data_tables",
    ),
    # ---- 小问
    "实验题的小问键含点": (
        TAPE,
        _set(["content", "subquestions", 0, "key"], "1.1"),
        "subquestions",
    ),
    "小问键和表键相同": (TAPE, _set(["content", "subquestions", 0, "key"], "t1"), "不能相同"),
    "小问键重复": (TAPE, _set(["content", "subquestions", 1, "key"], "1"), "subquestions"),
    "小问的作答方式不是 written": (
        TAPE,
        _set(["content", "subquestions", 0, "answer_mode"], "fill"),
        "subquestions",
    ),
    "小问题干为空": (TAPE, _set(["content", "subquestions", 0, "stem"], " "), "subquestions"),
    "实验题带了选项": (
        TAPE,
        _set(["content", "options"], [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]),
        "options",
    ),
    "没有留空的格子也没有小问": (OHM, _no_blanks_and_no_subquestions, "至少"),
    # ---- 参考答案
    "留空的格子没有参考值": (TAPE, _delete(["answer", "value", "t1.r1.v"]), "answer.value"),
    "给定的格子也有参考值": (TAPE, _set(["answer", "value", "t1.r1.x"], "4.00"), "answer.value"),
    "参考值是空话": (TAPE, _set(["answer", "value", "t1.r1.v"], " "), "answer.value"),
    "参考值太长": (TAPE, _set(["answer", "value", "t1.r1.v"], "1" * 41), "answer.value"),
    "小问没有参考答案": (TAPE, _delete(["answer", "value", "2"]), "answer.value"),
    "小问的参考答案是空话": (TAPE, _set(["answer", "value", "3"], "  "), "answer.value"),
    # ---- 自查要点
    "实验题没有自查要点": (TAPE, _delete(["rubric", "points"]), "rubric.points"),
    "有小问没有自查要点": (
        TAPE,
        _set(
            ["rubric", "points"],
            [
                {"key": "p1", "part": "1", "text": "a"},
                {"key": "p2", "part": "t1", "text": "b"},
                {"key": "p3", "part": "t2", "text": "c"},
            ],
        ),
        "rubric.points",
    ),
    "有留空格子的表没有自查要点": (TAPE, _drop_points_for("t2"), "rubric.points"),
    "自查要点指向不存在的部分": (OHM, _set(["rubric", "points", 0, "part"], "t9"), "rubric.points"),
    "自查要点带了分值": (OHM, _set(["rubric", "points", 0, "weight"], 2), "rubric.points"),
    "自查要点键重复": (OHM, _set(["rubric", "points", 1, "key"], "p1"), "rubric.points"),
    "自查要点文字为空": (OHM, _set(["rubric", "points", 0, "text"], ""), "rubric.points"),
    # ---- 泄题
    "实验题没有泄题标记": (TITRATION, _set(["teaching", "leak_markers"], []), "leak_markers"),
    "提示泄露了数据表的参考值": (
        TAPE,
        _append(["teaching", "hints"], "算出来第一段的平均速度是 0.400 m/s。"),
        "泄",
    ),
    "提示泄露了滴定的结果": (
        TITRATION,
        _append(["teaching", "hints"], "平均体积是 20.08 mL。"),
        "泄",
    ),
    "提示泄露了文字结论": (
        OHM,
        _append(["teaching", "hints"], "所以这里应内接。"),
        "泄",
    ),
    # ---- 题型和别的题型的边界
    "实验题的题型不对": (TAPE, _set(["type"], "solution"), "type"),
    "实验题的解法没有结论": (
        OHM,
        _set(["solutions", "standard", "final_answer"], ""),
        "final_answer",
    ),
    "实验题标称真题": (OHM, _set(["title"], "2025 年高考真题 · 伏安法"), "真题"),
    "题干带脚本标记": (OHM, _set(["content", "stem"], "<script>alert(1)</script>"), "标记"),
}


@pytest.mark.parametrize("label", sorted(BROKEN))
def test_validator_reports_broken_experiments(bundle, label):
    key, mutate, keyword = BROKEN[label]

    problems = validate_seed(_mutated(bundle, key, mutate))

    assert problems, f"校验器没有发现：{label}"
    assert any(key in problem and keyword in problem for problem in problems), problems


def test_only_experiments_may_carry_tables_or_safety_notes(bundle):
    tables = copy.deepcopy(_by_key(bundle)[TAPE]["content"]["data_tables"])
    safety = copy.deepcopy(_by_key(bundle)[TAPE]["content"]["safety"])
    for key in ("math-mono-quadratic", "math-ineq-min", "phys-pull-friction-written"):
        for field, value in (("data_tables", tables), ("safety", safety)):
            problems = validate_seed(_mutated(bundle, key, _set(["content", field], value)))
            assert any(key in p and "实验题" in p for p in problems), (key, field, problems)


def test_a_choice_question_cannot_pass_for_an_experiment(bundle):
    problems = validate_seed(
        _mutated(bundle, "math-mono-quadratic", _set(["answer_mode"], "experiment"))
    )

    assert any("math-mono-quadratic" in problem and "type" in problem for problem in problems)
