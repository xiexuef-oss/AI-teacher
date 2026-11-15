"""自编工程样题的内容校验（Q-05、docs/07）。

样题没有经过学科审校，这里能保证的只是结构自洽、不泄题、不冒充真题，以及答案与
从题设独立重算的结果一致。
"""

from __future__ import annotations

import copy
import math
import re
from collections import Counter

import pytest

from tutor_api.services.content_seed import (
    SeedBundle,
    leak_markers,
    load_seed,
    seed_uuid,
    validate_seed,
)


@pytest.fixture(scope="module")
def bundle() -> SeedBundle:
    return load_seed()


def _by_key(bundle: SeedBundle) -> dict[str, dict]:
    return {q["key"]: q for q in bundle.questions}


def _mutated(bundle: SeedBundle, key: str, mutate) -> SeedBundle:
    clone = copy.deepcopy(bundle)
    mutate(_by_key(clone)[key])
    return clone


# ---------------------------------------------------------------- 整体


def test_seed_bundle_is_valid(bundle):
    assert validate_seed(bundle) == []


WRITTEN_KEYS = (
    "math-quadratic-param-written",
    "phys-pull-friction-written",
    "chem-ion-equation-written",
)


def test_seed_covers_three_subjects_with_objective_written_and_experiment_modes(bundle):
    combos = {(q["subject"], q["answer_mode"]) for q in bundle.questions}
    assert combos == {
        (subject, mode)
        for subject in ("math", "physics", "chemistry")
        for mode in ("single_choice", "multiple_choice", "fill", "written")
    } | {("physics", "experiment"), ("chemistry", "experiment")}  # 数学没有实验题
    written = {q["key"] for q in bundle.questions if q["answer_mode"] == "written"}
    assert written == set(WRITTEN_KEYS)


def test_seed_covers_the_sample_topics_of_prd_4_1(bundle):
    codes = {code for q in bundle.questions for code in q["knowledge"]}
    assert {
        "math.function.monotonicity",
        "math.inequality.basic",
        "phys.force.analysis",
        "phys.newton.second",
        "phys.experiment.tape",
        "chem.stoichiometry",
        "chem.ion.test",
        "chem.lab.safety",
    } <= codes


def test_seed_exercises_both_explanation_paths_and_all_templates(bundle):
    """一部分题带审核过的"换种讲法"，一部分不带（走模型网关）；六个图解模板都有题目用到。"""
    with_rephrase = [q for q in bundle.questions if q["teaching"].get("concept_rephrase")]
    assert 0 < len(with_rephrase) < len(bundle.questions)
    used = {
        q["teaching"]["visual"]["template_id"]
        for q in bundle.questions
        if q["teaching"].get("visual")
    }
    assert used == {
        "quadratic_graph",
        "rectangle_area",
        "number_line",
        "force_diagram",
        "motion_chart",
        "chemical_flow",
    }
    assert any(not q["teaching"].get("visual") for q in bundle.questions)
    assert any(q["solutions"].get("fast") for q in bundle.questions)
    assert any(not q["solutions"].get("fast") for q in bundle.questions)


def test_every_question_is_labelled_as_a_self_authored_sample(bundle):
    for question in bundle.questions:
        text = str(question)
        assert "真题" not in text and "原题" not in text, question["key"]
    assert seed_uuid("question", "math-mono-quadratic") == seed_uuid(
        "question", "math-mono-quadratic"
    )
    assert seed_uuid("question", "a") != seed_uuid("knowledge", "a")


def test_region_tags_only_use_launch_regions(bundle):
    tags = [(q["key"], tag) for q in bundle.questions for tag in q.get("region_tags", [])]
    assert {tag["region"] for _, tag in tags} == {"CN-51", "CN-50"}
    assert any(not q.get("region_tags") for q in bundle.questions), "需要有不带地区标签的通用题"


def test_variants_point_to_base_questions(bundle):
    questions = _by_key(bundle)
    variants = [q for q in bundle.questions if q.get("variant_of")]
    assert len(variants) >= 3
    for variant in variants:
        base = questions[variant["variant_of"]]
        assert base["subject"] == variant["subject"]
        assert not base.get("variant_of")


# ---------------------------------------------------------------- 独立重算答案


def test_numeric_answers_match_independent_recomputation(bundle):
    q = _by_key(bundle)

    def blank(key: str) -> float:
        return float(q[key]["answer"]["value"]["b1"])

    # x + 4/x 在 x>0 上的最小值（细网格搜索）
    assert blank("math-ineq-min") == pytest.approx(
        min(x / 1000 + 4 / (x / 1000) for x in range(1, 20000)), abs=1e-4
    )
    # x + y = 8 时 xy 的最大值
    assert blank("math-ineq-product-v1") == pytest.approx(
        max(x / 100 * (8 - x / 100) for x in range(1, 800))
    )
    # 光滑斜面 a = g sin30°
    assert blank("phys-incline-accel") == pytest.approx(10 * math.sin(math.radians(30)))
    # x = v0 t + a t² / 2，用逐步积分核对
    dt, v, x = 1e-4, 2.0, 0.0
    for _ in range(int(4 / dt)):
        x += v * dt + 0.5 * 3 * dt * dt
        v += 3 * dt
    assert blank("phys-vt-displacement") == pytest.approx(x, rel=1e-6)
    # 10 g CaCO3 → CO2
    assert blank("chem-conservation-co2") == pytest.approx(10 / (40 + 12 + 16 * 3) * (12 + 16 * 2))


def test_choice_answers_match_independent_recomputation(bundle):
    q = _by_key(bundle)

    def correct_text(key: str) -> str:
        question = q[key]
        (answer,) = question["answer"]["value"]
        return next(o["text"] for o in question["content"]["options"] if o["key"] == answer)

    # f(x) = x² - 2x - 3：对称轴 x = 1，开口向上，递增区间从 1 开始向右
    assert "1" in correct_text("math-mono-quadratic") and "+\\infty" in correct_text(
        "math-mono-quadratic"
    )
    # 周长 20 的矩形最大面积
    assert f"{max(x / 100 * (10 - x / 100) for x in range(1, 1000)):g}" in correct_text(
        "math-ineq-rect"
    )
    # a = F / m
    assert f"{12 / 4:g}" in correct_text("phys-newton2-force")
    # a = Δx / T²，Δx = 0.50 cm
    assert f"{0.50e-2 / 0.1**2:.2f}" in correct_text("phys-tape-accel")
    # 6.5 g Zn → H2 的物质的量
    assert f"{6.5 / 65:g}" in correct_text("chem-conservation-h2")
    # 电荷守恒：0.2 + 2×0.4 = 0.4 + 2c
    assert f"{(0.2 + 2 * 0.4 - 0.4) / 2:g}" in correct_text("chem-charge-conservation")


def test_multiple_choice_keys_match_independent_checks(bundle):
    q = _by_key(bundle)
    # (0, +∞) 上单调递增：逐点检查
    functions = {
        "A": lambda x: 2 * x + 1,
        "B": lambda x: 1 / x,
        "C": lambda x: x * x,
        "D": lambda x: -abs(x),
    }
    points = [0.1 * k for k in range(1, 200)]
    increasing = {
        key
        for key, f in functions.items()
        if all(f(a) < f(b) for a, b in zip(points, points[1:], strict=False))
    }
    assert set(q["math-mono-judge"]["answer"]["value"]) == increasing == {"A", "C"}
    assert set(q["phys-force-analysis"]["answer"]["value"]) == {"A", "B"}
    assert set(q["chem-ion-inference"]["answer"]["value"]) == {"B", "C"}
    assert q["chem-lab-operation"]["answer"]["value"] == ["C"]


def test_interval_and_expression_answers(bundle):
    q = _by_key(bundle)
    # f(x) = -x² + 4x + 1：对称轴 x = 2，开口向下，递增区间在左侧
    assert q["math-mono-quadratic-v1"]["answer"]["value"]["b1"] == "(-inf,2]"
    assert -4 / (2 * -1) == 2
    assert q["phys-incline-accel-v1"]["answer"]["value"]["b1"] == "g*sin(theta)"


# ---------------------------------------------------------------- 解答题样题


def test_written_samples_have_subquestions_and_checklist_points_for_each(bundle):
    q = _by_key(bundle)
    for key in WRITTEN_KEYS:
        question = q[key]
        assert question["type"] == "solution", key
        parts = [sub["key"] for sub in question["content"]["subquestions"]]
        assert len(parts) >= 2 and len(set(parts)) == len(parts), key
        assert set(question["answer"]["value"]) == set(parts), key

        points = question["rubric"]["points"]
        point_keys = [point["key"] for point in points]
        assert len(set(point_keys)) == len(point_keys), key
        covered = {point["part"] for point in points}
        assert set(parts) <= covered <= set(parts) | {None}, key
        # 解答题的答案是一整段话，推不出泄题标记，必须由题目自己列
        assert question["teaching"]["leak_markers"], key
        assert not question["content"].get("options") and not question["content"].get("blanks")


def test_written_samples_never_give_points_or_weights(bundle):
    """自查要点只是清单，不带分值：一旦带了分，学生就会把它当成评分。"""
    for key in WRITTEN_KEYS:
        for point in _by_key(bundle)[key]["rubric"]["points"]:
            assert set(point) == {"key", "part", "text"}, (key, point)


def test_written_math_answers_match_independent_recomputation(bundle):
    question = _by_key(bundle)["math-quadratic-param-written"]

    def f(x: float, a: float) -> float:
        return x * x - 2 * a * x + 3

    # (1) 在 [1,+∞) 上单调递增当且仅当 a≤1：在足够长的网格上逐点比较
    grid = [1 + k * 0.05 for k in range(400)]

    def increasing(a: float) -> bool:
        return all(f(x, a) < f(y, a) for x, y in zip(grid, grid[1:], strict=False))

    candidates = [k / 4 for k in range(-12, 13)]
    assert {a for a in candidates if increasing(a)} == {a for a in candidates if a <= 1}
    # (2) a=2，区间 [0,3]
    values = [f(3 * k / 1000, 2) for k in range(1001)]
    assert min(values) == pytest.approx(-1, abs=1e-5)
    assert max(values) == pytest.approx(3)

    answers = question["answer"]["value"]
    assert "a\\le 1" in answers["1"]
    assert "$3$" in answers["2"] and "$-1$" in answers["2"]


def test_written_physics_answers_match_independent_recomputation(bundle):
    question = _by_key(bundle)["phys-pull-friction-written"]
    m, force, mu, g = 2, 10, 0.5, 10
    # 题目给的 sin37°、cos37° 取一位小数，先核对它们与真值一致
    assert (round(math.sin(math.radians(37)), 1), round(math.cos(math.radians(37)), 1)) == (
        0.6,
        0.8,
    )
    support = m * g - force * 0.6
    friction = mu * support
    assert force * 0.8 > friction, "拉力的水平分力要大于滑动摩擦力，物体才会滑动"
    acceleration = (force * 0.8 - friction) / m
    assert support == pytest.approx(14)
    assert acceleration == pytest.approx(0.5)

    answers = question["answer"]["value"]
    assert "14" in answers["1"] and "0.5" in answers["2"]


def _plain_equation(latex: str) -> str:
    """把 $...$ 里的离子方程式化成容易数原子的纯文本：电荷写成 |2p| / |1m|。"""
    text = latex.strip("$")
    text = re.sub(r"\\text\{([^}]*)\}", r"\1", text)
    text = re.sub(r"_\{?(\d+)\}?", r"\1", text)
    text = text.replace("\\uparrow", "").replace("\\downarrow", "")
    return re.sub(
        r"\^\{?(\d*)([+-])\}?",
        lambda m: f"|{m.group(1) or 1}{'p' if m.group(2) == '+' else 'm'}|",
        text,
    )


def _side_totals(side: str) -> tuple[Counter, int]:
    atoms: Counter = Counter()
    charge = 0
    for term in side.split("+"):
        if not term:
            continue
        coefficient = re.match(r"\d+", term)
        count = int(coefficient.group()) if coefficient else 1
        body = term[coefficient.end() if coefficient else 0 :]
        ion = re.search(r"\|(\d)([pm])\|$", body)
        if ion:
            charge += count * int(ion.group(1)) * (1 if ion.group(2) == "p" else -1)
            body = body[: ion.start()]
        for element, number in re.findall(r"([A-Z][a-z]?)(\d*)", body):
            atoms[element] += count * int(number or 1)
    return atoms, charge


def test_written_chemistry_equations_balance_in_atoms_and_charge(bundle):
    question = _by_key(bundle)["chem-ion-equation-written"]
    answers = question["answer"]["value"]
    for part, latex in answers.items():
        left, right = _plain_equation(latex).split("=")
        assert _side_totals(left) == _side_totals(right), (part, latex)
    # 第 (2) 问：OH⁻ 与 H⁺ 的系数都是 2，不能约成 1:1
    assert "2\\text{OH}^-" in answers["2"] and "2\\text{H}^+" in answers["2"]
    # 标准解法的结论与参考答案一致
    final = question["solutions"]["standard"]["final_answer"]
    assert all(latex in final for latex in answers.values())


# ---------------------------------------------------------------- 泄题标记


def test_leak_markers_cover_common_ways_of_giving_the_answer_away(bundle):
    q = _by_key(bundle)
    choice = leak_markers(q["math-mono-quadratic"])
    assert {"选B", "答案是B", "答案为B", "故选B", "B正确"} <= set(choice)
    assert "选A" not in choice
    multi = leak_markers(q["math-mono-judge"])
    assert {"选AC", "选A", "选C"} <= set(multi)
    numeric = leak_markers(q["math-ineq-min"])
    assert {"答案是4", "最小值为4", "最小值是4"} <= set(numeric)
    assert any("sin" in marker for marker in leak_markers(q["phys-incline-accel-v1"]))


# ---------------------------------------------------------------- 校验器抓得住问题


def _set(path: list, value):
    def mutate(question: dict) -> None:
        node = question
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value

    return mutate


def _append(path: list, value):
    def mutate(question: dict) -> None:
        node = question
        for part in path:
            node = node[part]
        node.append(value)

    return mutate


def _delete(path: list):
    def mutate(question: dict) -> None:
        node = question
        for part in path[:-1]:
            node = node[part]
        del node[path[-1]]

    return mutate


BROKEN = {
    "答案不在选项里": ("math-mono-quadratic", _set(["answer", "value"], ["E"]), "answer"),
    "单选题有两个答案": ("math-mono-quadratic", _set(["answer", "value"], ["A", "B"]), "单选"),
    "多选题只有一个答案": ("math-mono-judge", _set(["answer", "value"], ["A"]), "多选"),
    "提示泄露了选项": (
        "math-mono-quadratic",
        _append(["teaching", "hints"], "所以这题选 B。"),
        "泄",
    ),
    "提示泄露了填空答案": (
        "math-ineq-min",
        _append(["teaching", "hints"], "所以最小值为 4。"),
        "泄",
    ),
    "换种讲法泄题": (
        "math-mono-quadratic",
        _set(["teaching", "concept_rephrase"], "答案是B，记住就行。"),
        "泄",
    ),
    "错项分析泄露正确项": (
        "math-mono-quadratic",
        _set(["teaching", "option_analysis", "A"], "不对，应选 B。"),
        "泄",
    ),
    "提示太少": ("math-mono-quadratic", _set(["teaching", "hints"], ["只有一层"]), "hints"),
    "选项分析缺一项": (
        "math-mono-quadratic",
        _delete(["teaching", "option_analysis", "D"]),
        "option_analysis",
    ),
    "快速解法没有适用条件": (
        "math-mono-quadratic",
        _set(["solutions", "fast", "conditions"], []),
        "conditions",
    ),
    "快速解法没有边界说明": (
        "math-mono-quadratic",
        _set(["solutions", "fast", "boundary"], ""),
        "boundary",
    ),
    "没有常规解法": ("math-mono-quadratic", _delete(["solutions", "standard"]), "standard"),
    "解法结论与答案不一致": (
        "math-mono-quadratic",
        _set(["solutions", "standard", "final_answer"], "A"),
        "final_answer",
    ),
    "图解用了未注册模板": (
        "math-mono-quadratic",
        _set(["teaching", "visual", "template_id"], "free_canvas"),
        "visual",
    ),
    "图解参数越界": (
        "math-mono-quadratic",
        _set(["teaching", "visual", "params", "a"], 99),
        "visual",
    ),
    "知识点不存在": ("math-mono-quadratic", _set(["knowledge"], ["math.no.such"]), "math.no.such"),
    "知识点跨学科": ("math-mono-quadratic", _set(["knowledge"], ["phys.newton.second"]), "学科"),
    "题干带脚本标记": (
        "math-mono-quadratic",
        _set(["content", "stem"], "<script>alert(1)</script>"),
        "标记",
    ),
    "标称真题": ("math-mono-quadratic", _set(["title"], "2025 年四川高考真题"), "真题"),
    "变式指向不存在的题": (
        "math-mono-quadratic-v1",
        _set(["variant_of"], "no-such-key"),
        "variant_of",
    ),
    "变式的变式": ("math-ineq-rect", _set(["variant_of"], "math-mono-quadratic-v1"), "variant_of"),
    "地区标签不是首发地区": (
        "math-mono-quadratic",
        _set(["region_tags"], [{"region": "CN-11"}]),
        "CN-11",
    ),
    "地区标签年份倒置": (
        "math-mono-quadratic",
        _set(["region_tags"], [{"region": "CN-51", "exam_year_from": 2029, "exam_year_to": 2027}]),
        "exam_year",
    ),
    "填空标准答案过不了自己的规则": (
        "math-ineq-min",
        _set(["answer", "value", "b1"], "四"),
        "answer",
    ),
    "未知的等价规则": (
        "math-ineq-min",
        _set(["answer", "equivalence_rules", "b1"], {"type": "fuzzy"}),
        "fuzzy",
    ),
    "未知的多选规则": (
        "math-mono-judge",
        _set(["rubric", "multi_choice_rule"], "half_points"),
        "multi_choice_rule",
    ),
    "难度越界": ("math-mono-quadratic", _set(["difficulty"], 9), "difficulty"),
    "作答方式不支持": ("math-mono-quadratic", _set(["answer_mode"], "essay"), "answer_mode"),
    "作答方式写错了": ("math-mono-quadratic", _set(["answer_mode"], "experiment"), "answer_mode"),
    # ---- 解答题
    "解答题的题型不对": (
        "math-quadratic-param-written",
        _set(["type"], "fill_blank"),
        "type",
    ),
    "解答题没有小问": (
        "math-quadratic-param-written",
        _set(["content", "subquestions"], []),
        "subquestions",
    ),
    "解答题小问键重复": (
        "math-quadratic-param-written",
        _set(["content", "subquestions", 1, "key"], "1"),
        "subquestions",
    ),
    "解答题小问的作答方式不是 written": (
        "math-quadratic-param-written",
        _set(["content", "subquestions", 0, "answer_mode"], "fill"),
        "subquestions",
    ),
    "解答题小问题干为空": (
        "math-quadratic-param-written",
        _set(["content", "subquestions", 0, "stem"], "  "),
        "subquestions",
    ),
    "解答题带了选项": (
        "math-quadratic-param-written",
        _set(["content", "options"], [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]),
        "options",
    ),
    "解答题参考答案缺一个小问": (
        "math-quadratic-param-written",
        _delete(["answer", "value", "2"]),
        "answer.value",
    ),
    "解答题参考答案是空话": (
        "math-quadratic-param-written",
        _set(["answer", "value", "1"], "  "),
        "answer.value",
    ),
    "解答题没有自查要点": (
        "math-quadratic-param-written",
        _delete(["rubric", "points"]),
        "rubric.points",
    ),
    "解答题有小问没有自查要点": (
        "math-quadratic-param-written",
        _set(
            ["rubric", "points"],
            [{"key": "p1", "part": "1", "text": "写出对称轴"}],
        ),
        "rubric.points",
    ),
    "自查要点指向不存在的小问": (
        "phys-pull-friction-written",
        _set(["rubric", "points", 0, "part"], "9"),
        "rubric.points",
    ),
    "自查要点键重复": (
        "phys-pull-friction-written",
        _set(["rubric", "points", 1, "key"], "p1"),
        "rubric.points",
    ),
    "自查要点文字为空": (
        "phys-pull-friction-written",
        _set(["rubric", "points", 0, "text"], ""),
        "rubric.points",
    ),
    "自查要点带了分值": (
        "phys-pull-friction-written",
        _set(["rubric", "points", 0, "weight"], 2),
        "rubric.points",
    ),
    "解答题没有泄题标记": (
        "chem-ion-equation-written",
        _set(["teaching", "leak_markers"], []),
        "leak_markers",
    ),
    "解答题提示泄露了结论": (
        "math-quadratic-param-written",
        _append(["teaching", "hints"], "所以第 (1) 问的结果是 $a\\le 1$。"),
        "泄",
    ),
    "解答题提示泄露了数值结果": (
        "phys-pull-friction-written",
        _append(["teaching", "hints"], "算出来支持力是 14 N。"),
        "泄",
    ),
    "解答题的解法没有结论": (
        "chem-ion-equation-written",
        _set(["solutions", "standard", "final_answer"], ""),
        "final_answer",
    ),
}


@pytest.mark.parametrize("label", sorted(BROKEN))
def test_validator_reports_broken_content(bundle, label):
    key, mutate, keyword = BROKEN[label]

    problems = validate_seed(_mutated(bundle, key, mutate))

    assert problems, f"校验器没有发现：{label}"
    assert any(key in problem and keyword in problem for problem in problems), problems


def test_validator_reports_duplicate_keys(bundle):
    clone = copy.deepcopy(bundle)
    clone.questions.append(copy.deepcopy(clone.questions[0]))
    assert any("重复" in problem for problem in validate_seed(clone))


def test_validator_reports_prerequisite_cycles(bundle):
    clone = copy.deepcopy(bundle)
    first = clone.edges[0]
    clone.edges.append([first[1], first[0]])
    assert any("环" in problem for problem in validate_seed(clone))


def test_validator_reports_self_loops_and_unknown_nodes(bundle):
    clone = copy.deepcopy(bundle)
    code = clone.nodes[0]["code"]
    clone.edges.append([code, code])
    clone.edges.append([code, "math.no.such"])
    problems = validate_seed(clone)
    assert any("自环" in problem for problem in problems)
    assert any("math.no.such" in problem for problem in problems)
