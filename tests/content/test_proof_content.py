"""证明题样题的内容校验（PRD §5"数学解答/证明"、§4.1"证明题逻辑链"；Q-05、Q-06）。

样题没有经过学科审校，这里能保证的是：结构自洽（已知、求证、参考证明、自查要点互相对得上）、
参考证明每一步都有依据并以结论收尾、提示不把关键构造说出来、不冒充真题，
以及证明里每个式子、每个"所以"与独立重算的结果一致。
"""

from __future__ import annotations

import copy
from fractions import Fraction as F
from itertools import combinations, product

import pytest

from tutor_api.services.content_seed import (
    SeedBundle,
    find_leak,
    leak_markers,
    load_seed,
    validate_seed,
)

DIFF = "math-ineq-diff-proof"
MONO = "math-mono-def-proof"
MUL = "math-ineq-mul-proof"
ENERGY = "phys-work-energy-proof"
PROOF_KEYS = (DIFF, MONO, MUL, ENERGY, "math-triangle-coordinate-proof", "math-circle-radius-proof")
STAGES = ("premise", "construction", "reasoning", "conclusion")


@pytest.fixture(scope="module")
def bundle() -> SeedBundle:
    return load_seed()


def _by_key(bundle: SeedBundle) -> dict[str, dict]:
    return {q["key"]: q for q in bundle.questions}


def _mutated(bundle: SeedBundle, key: str, mutate) -> SeedBundle:
    clone = copy.deepcopy(bundle)
    mutate(_by_key(clone)[key])
    return clone


def _steps(question: dict) -> list[dict]:
    return question["answer"]["value"]["steps"]


# ---------------------------------------------------------------- 整体


@pytest.mark.parametrize("expression", ["OA^2=1", "OB^2=1", "OA²=1", "OB²=1"])
def test_circle_reference_transform_is_explicitly_blocked_in_hints(bundle, expression):
    question = _by_key(bundle)["math-circle-radius-proof"]
    assert find_leak(expression, leak_markers(question)) is not None


def test_the_proof_samples_are_valid(bundle):
    assert validate_seed(bundle) == []


def test_there_are_proof_samples_for_math_and_physics(bundle):
    proofs = {q["key"]: q for q in bundle.questions if q["answer_mode"] == "proof"}

    assert set(proofs) == set(PROOF_KEYS)
    assert {q["subject"] for q in proofs.values()} == {"math", "physics"}
    assert {q["type"] for q in proofs.values()} == {"proof"}
    # 都是通用题，没有地区标签
    assert all(not q.get("region_tags") for q in proofs.values())
    # 数学覆盖多个证明主题，物理样题是推导。
    assert {code for q in proofs.values() for code in q["knowledge"]} >= {
        "math.inequality.basic",
        "math.function.monotonicity",
        "math.inequality.properties",
        "phys.newton.second",
    }


@pytest.mark.parametrize("key", PROOF_KEYS)
def test_a_proof_has_a_claim_and_givens_and_nothing_else_in_its_content(bundle, key):
    content = _by_key(bundle)[key]["content"]

    assert set(content["proof"]) == {"givens", "claim"}
    assert content["proof"]["claim"].strip()
    assert 1 <= len(content["proof"]["givens"]) <= 8
    assert not content.get("options") and not content.get("blanks")
    assert not content.get("subquestions") and not content.get("data_tables")
    assert not content.get("safety")


@pytest.mark.parametrize("key", PROOF_KEYS)
def test_the_reference_proof_gives_a_reason_for_every_step_and_ends_with_a_conclusion(bundle, key):
    question = _by_key(bundle)[key]
    steps = _steps(question)

    assert set(question["answer"]["value"]) == {"steps"}
    assert 2 <= len(steps) <= 20
    for step in steps:
        assert set(step) == {"stage", "text", "reason"}
        assert step["stage"] in STAGES
        assert step["text"].strip() and step["reason"].strip()
    assert steps[-1]["stage"] == "conclusion"
    assert {"premise", "reasoning"} <= {step["stage"] for step in steps}


@pytest.mark.parametrize("key", PROOF_KEYS)
def test_the_checklist_covers_every_stage_of_the_reference_proof(bundle, key):
    question = _by_key(bundle)[key]
    points = question["rubric"]["points"]
    stages = {step["stage"] for step in _steps(question)}

    assert stages <= {p["part"] for p in points}
    assert {p["part"] for p in points} <= {*STAGES, None}
    assert all(set(p) == {"key", "part", "text"} for p in points)  # 不带分值
    # 每份证明都有一条针对整份证明的要点：每一步都写了依据
    assert any(p["part"] is None and "依据" in p["text"] for p in points)


@pytest.mark.parametrize("key", PROOF_KEYS)
def test_the_leak_markers_are_the_key_steps_and_no_hint_gives_them_away(bundle, key):
    question = _by_key(bundle)[key]
    markers = leak_markers(question)
    proof_text = " ".join(
        [step["text"] for step in _steps(question)] + question["solutions"]["standard"]["steps"]
    )

    assert markers == question["teaching"]["leak_markers"], "证明题的泄题标记全由题目自己列"
    assert find_leak(proof_text, markers), "标记要真的对得上参考证明里的式子，不是随手写的"
    for hint in question["teaching"]["hints"]:
        assert find_leak(hint, markers) is None, hint
    rephrase = question["teaching"].get("concept_rephrase")
    assert rephrase is None or find_leak(rephrase, markers) is None


# ---------------------------------------------------------------- 独立重算


def test_the_difference_proof_checks_out_with_exact_fractions(bundle):
    """a/b + b/a − 2 恒等于 (a−b)²/(ab)，它非负，并且只有 a=b 时为 0。"""
    values = [F(n, 4) for n in range(1, 25)]  # 1/4 … 6
    for a, b in product(values, repeat=2):
        difference = a / b + b / a - 2
        assert difference == (a - b) ** 2 / (a * b)  # 作差、通分、配成平方
        assert difference >= 0
        assert (difference == 0) == (a == b)  # 等号当且仅当 a=b


def test_the_monotonicity_proof_checks_out_with_exact_fractions(bundle):
    def f(x: F) -> F:
        return x + 1 / x

    values = [F(n, 4) for n in range(4, 25)]  # 1 … 6
    for x1, x2 in combinations(values, 2):  # 总有 x1 < x2
        assert f(x1) - f(x2) == (x1 - x2) * (x1 * x2 - 1) / (x1 * x2)  # 作差、通分、提公因式
        assert x1 - x2 < 0 and x1 * x2 > 1 and x1 * x2 > 0  # 各因式的符号
        assert f(x1) < f(x2)
    # 区间左端点 1 就是分界：区间往左伸进 (0,1)，结论就不成立
    assert f(F(1, 2)) > f(F(1))


def test_the_product_proof_checks_out_and_needs_positivity(bundle):
    for a, b, c, d in product(range(1, 8), repeat=4):
        if a > b and c > d:
            assert a * c > b * c  # 同乘正数 c，方向不变
            assert b * c > b * d  # 同乘正数 b，方向不变
            assert a * c > b * d  # 传递性
    # 去掉"都是正数"，结论就不成立：2>1，-1>-2，可是 2·(-1) 并不大于 1·(-2)
    a, b, c, d = 2, 1, -1, -2
    assert a > b and c > d and not a * c > b * d


def test_the_work_energy_derivation_checks_out_with_exact_fractions(bundle):
    cases = product(
        [F(1), F(2), F(5, 2)],  # 质量 m
        [F(1), F(3), F(10, 3)],  # 恒力 F
        [F(0), F(1), F(3, 2)],  # 初速度 v1
        [F(1, 2), F(1), F(2)],  # 时间 t
    )
    for m, force, v1, t in cases:
        a = force / m  # 牛顿第二定律
        v2 = v1 + a * t
        s = v1 * t + a * t * t / 2
        assert v2 * v2 - v1 * v1 == 2 * a * s  # 速度—位移公式
        assert v2 * v2 - v1 * v1 == 2 * force * s / m  # 代入 a=F/m
        assert force * s == m * v2 * v2 / 2 - m * v1 * v1 / 2  # 结论


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


def _repeat_the_last_step(times: int):
    def mutate(question: dict) -> None:
        steps = question["answer"]["value"]["steps"]
        steps.extend(copy.deepcopy(steps[-1]) for _ in range(times))

    return mutate


BROKEN = {
    # ---- 已知与求证
    "证明题没有已知和求证": (DIFF, _set(["content", "proof"], None), "content.proof"),
    "缺了求证": (DIFF, _delete(["content", "proof", "claim"]), "content.proof"),
    "缺了已知": (DIFF, _delete(["content", "proof", "givens"]), "content.proof"),
    "已知和求证之外还有别的": (DIFF, _set(["content", "proof", "hint"], "x"), "content.proof"),
    "求证是空话": (DIFF, _set(["content", "proof", "claim"], "  "), "claim"),
    "求证太长": (DIFF, _set(["content", "proof", "claim"], "证" * 501), "claim"),
    "已知不是列表": (DIFF, _set(["content", "proof", "givens"], "a>0"), "givens"),
    "已知太多": (DIFF, _set(["content", "proof", "givens"], ["条件"] * 9), "givens"),
    "已知里有空话": (DIFF, _set(["content", "proof", "givens", 0], " "), "givens"),
    "一条已知太长": (DIFF, _set(["content", "proof", "givens", 0], "长" * 401), "givens"),
    "题干为空": (DIFF, _set(["content", "stem"], " "), "stem"),
    # ---- 和别的题型的边界
    "证明题带了选项": (
        DIFF,
        _set(["content", "options"], [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]),
        "options",
    ),
    "证明题带了小问": (
        DIFF,
        _set(["content", "subquestions"], [{"key": "1", "stem": "x", "answer_mode": "written"}]),
        "subquestions",
    ),
    "证明题带了数据表": (DIFF, _set(["content", "data_tables"], [{"key": "t1"}]), "实验题"),
    "证明题带了安全提示": (
        DIFF,
        _set(["content", "safety"], {"level": "low", "notes": ["x"]}),
        "实验题",
    ),
    # ---- 参考证明
    "没有参考证明": (DIFF, _delete(["answer", "value", "steps"]), "answer.value"),
    "参考证明的形状不对": (DIFF, _set(["answer", "value"], ["a", "b"]), "answer.value"),
    "参考答案里多出别的键": (DIFF, _set(["answer", "value", "1"], "x"), "answer.value"),
    "参考证明不是列表": (DIFF, _set(["answer", "value", "steps"], "略"), "steps"),
    "参考证明只有一步": (
        DIFF,
        lambda q: q["answer"]["value"].update(steps=q["answer"]["value"]["steps"][-1:]),
        "steps",
    ),
    "参考证明太长": (DIFF, _repeat_the_last_step(20), "steps"),
    "步骤的阶段无效": (DIFF, _set(["answer", "value", "steps", 0, "stage"], "intro"), "stage"),
    "步骤没有阶段": (DIFF, _delete(["answer", "value", "steps", 0, "stage"]), "steps"),
    "步骤多出字段": (DIFF, _set(["answer", "value", "steps", 0, "score"], 1), "steps"),
    "步骤文字是空话": (DIFF, _set(["answer", "value", "steps", 1, "text"], " "), "text"),
    "步骤文字太长": (DIFF, _set(["answer", "value", "steps", 1, "text"], "长" * 1001), "text"),
    "参考证明的步骤没有依据": (DIFF, _set(["answer", "value", "steps", 1, "reason"], ""), "reason"),
    "依据太长": (DIFF, _set(["answer", "value", "steps", 1, "reason"], "长" * 401), "reason"),
    "最后一步不是结论": (
        DIFF,
        _set(["answer", "value", "steps", -1, "stage"], "reasoning"),
        "conclusion",
    ),
    # ---- 自查要点
    "证明题没有自查要点": (DIFF, _delete(["rubric", "points"]), "rubric.points"),
    "要点指向不存在的阶段": (DIFF, _set(["rubric", "points", 0, "part"], "intro"), "rubric.points"),
    "要点指向小问的键": (DIFF, _set(["rubric", "points", 0, "part"], "1"), "rubric.points"),
    "结论阶段没有要点": (DIFF, _drop_points_for("conclusion"), "rubric.points"),
    "前提阶段没有要点": (MONO, _drop_points_for("premise"), "rubric.points"),
    "推理阶段没有要点": (ENERGY, _drop_points_for("reasoning"), "rubric.points"),
    "构造阶段没有要点": (MUL, _drop_points_for("construction"), "rubric.points"),
    "要点带了分值": (DIFF, _set(["rubric", "points", 0, "weight"], 2), "rubric.points"),
    "要点键重复": (DIFF, _set(["rubric", "points", 1, "key"], "p1"), "rubric.points"),
    "要点文字为空": (DIFF, _set(["rubric", "points", 0, "text"], ""), "rubric.points"),
    # ---- 泄题
    "证明题没有泄题标记": (DIFF, _set(["teaching", "leak_markers"], []), "leak_markers"),
    "提示写出了作差的结果": (
        DIFF,
        _append(["teaching", "hints"], "差化简以后是 (a-b)^2/(ab)。"),
        "泄",
    ),
    "提示写出了因式分解的结果": (
        MONO,
        _append(["teaching", "hints"], "差等于 (x_1-x_2)(x_1x_2-1)/(x_1x_2)。"),
        "泄",
    ),
    "提示写出了中间量": (MUL, _append(["teaching", "hints"], "先证 ac>bc 再证 bc>bd。"), "泄"),
    "提示写出了运动学公式": (
        ENERGY,
        _append(["teaching", "hints"], "用 v_2^2-v_1^2=2as 就行。"),
        "泄",
    ),
    "换种讲法泄了题": (
        DIFF,
        _set(["teaching", "concept_rephrase"], "分子就是 (a-b)^2，所以非负。"),
        "泄",
    ),
    # ---- 解法、题型、真题声明
    "证明题的题型不对": (DIFF, _set(["type"], "solution"), "type"),
    "证明题的解法没有结论": (
        MUL,
        _set(["solutions", "standard", "final_answer"], ""),
        "final_answer",
    ),
    "证明题标称真题": (MUL, _set(["title"], "2025 年高考真题 · 不等式的性质"), "真题"),
    "题干带脚本标记": (DIFF, _set(["content", "stem"], "<script>alert(1)</script>"), "标记"),
}


@pytest.mark.parametrize("label", sorted(BROKEN))
def test_validator_reports_broken_proofs(bundle, label):
    key, mutate, keyword = BROKEN[label]

    problems = validate_seed(_mutated(bundle, key, mutate))

    assert problems, f"校验器没有发现：{label}"
    assert any(key in problem and keyword in problem for problem in problems), problems


def test_only_proofs_may_carry_a_proof_statement(bundle):
    statement = copy.deepcopy(_by_key(bundle)[DIFF]["content"]["proof"])
    for key in (
        "math-mono-quadratic",
        "math-ineq-min",
        "phys-pull-friction-written",
        "phys-tape-experiment",
    ):
        problems = validate_seed(_mutated(bundle, key, _set(["content", "proof"], statement)))
        assert any(key in p and "证明题" in p for p in problems), (key, problems)


def test_a_choice_question_cannot_pass_for_a_proof(bundle):
    problems = validate_seed(
        _mutated(bundle, "math-mono-quadratic", _set(["answer_mode"], "proof"))
    )

    assert any("math-mono-quadratic" in problem and "type" in problem for problem in problems)
