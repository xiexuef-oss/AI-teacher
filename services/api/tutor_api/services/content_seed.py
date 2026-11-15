"""自编工程样题的加载、校验与入库（Q-05）。

样题只用于在本机跑通流程，没有经过学科审校。入库时题目状态为 published、解法 reviewed=True，
这两个标记在这里只表示"通过了下面的工程自检"，不代表 docs/07 要求的独立二审；接口会把这些题
明确标成"自编工程样题"。seed/drafts/ 里的是待审样题：入库为 draft、解法未审核，学生看不到，
要在审核后台二审、上线（services/review_service.py）。

校验能保证的是结构自洽：答案在选项内、填空答案过得了自己的判定规则、提示和错项分析不泄题、
快速解法带适用条件和边界、图解参数在白名单内、不冒充真题。校验不了的是学科内容本身对不对。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_gateway import VisualTemplateError
from ai_gateway.validation import contains_blocked_markup
from tutor_api import launch
from tutor_api.models import (
    KnowledgeEdge,
    KnowledgeNode,
    Question,
    QuestionKnowledge,
    QuestionRegionApplicability,
    QuestionVersion,
    Rubric,
    Solution,
)
from tutor_api.services import grading, mathparse
from tutor_api.settings import SEED_DIR
from tutor_api.visuals import visual_registry

SEED_NAMESPACE = uuid.UUID("6f0c1c1e-8a57-4c6e-9a3b-2d5e7f9a1b3c")
ENGINEERING_SAMPLE_LICENSE = "internal-engineering-sample"
ENGINEERING_SAMPLE_NAME = "自编工程样题"
REGION_TAG_NOTE = "工程筛选测试标签，不代表官方命题规则"

_TYPE_BY_MODE = {
    "single_choice": "single_choice",
    "multiple_choice": "multiple_choice",
    "fill": "fill_blank",
    "written": "solution",
    "experiment": "experiment",
    "proof": "proof",
}
_CHOICE_MODES = {"single_choice", "multiple_choice"}
_MAX_PARTS = 20
_MAX_POINTS = 40
_POINT_FIELDS = {"key", "part", "text"}  # 自查要点只有这三个字段：不带分值，它不是评分
_REAL_EXAM_CLAIMS = ("真题", "原题")
_MAX_TEXT = 4000
_MAX_SHORT = 200
# 实验题：表、行、列的键只用字母、数字和下划线（格子的键是 "表键.行键.列键"，不能含点）
_TABLE_KEY = re.compile(r"^[A-Za-z0-9_]{1,16}$")
_MAX_TABLES = 5
_MAX_COLUMNS = 12
_MAX_ROWS = 30
_MAX_CELL_TEXT = 40
_MAX_SAFETY_NOTES = 8
_SAFETY_LEVELS = ("low", "medium")  # high（高风险）现在不收录
_NUMBER_LIKE = re.compile(r"^[-+]?\d+(?:\.\d+)?$")
# 证明题：参考证明里一步的角色（对应 docs/06 的"拆解前提、构造、关键变形、结论"）
_STAGES = ("premise", "construction", "reasoning", "conclusion")
_MAX_GIVENS = 8
_MAX_GIVEN = 400
_MAX_CLAIM = 500
_MIN_PROOF_STEPS = 2
_MAX_PROOF_STEPS = 20
_MAX_STEP_TEXT = 1000
_MAX_STEP_REASON = 400


DRAFT_AUTHOR_KEY = "engineering-seed"


@dataclass
class SeedBundle:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[list[str]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    # 待审样题：入库时是 draft，学生看不到，用来演示和测试内容审核流程（seed/drafts/）
    drafts: list[dict[str, Any]] = field(default_factory=list)


def seed_uuid(kind: str, key: str) -> str:
    """由种子 key 推出的稳定 ID，保证重复导入不产生新行。"""
    return str(uuid.uuid5(SEED_NAMESPACE, f"{kind}:{key}"))


def load_seed(directory: Path = SEED_DIR) -> SeedBundle:
    knowledge = yaml.safe_load((directory / "knowledge.yaml").read_text(encoding="utf-8"))
    questions: list[dict[str, Any]] = []
    for path in sorted((directory / "questions").glob("*.yaml")):
        questions.extend(yaml.safe_load(path.read_text(encoding="utf-8")) or [])
    drafts: list[dict[str, Any]] = []
    for path in sorted((directory / "drafts").glob("*.yaml")):
        drafts.extend(yaml.safe_load(path.read_text(encoding="utf-8")) or [])
    return SeedBundle(
        nodes=list(knowledge.get("nodes", [])),
        edges=[list(edge) for edge in knowledge.get("edges", [])],
        questions=questions,
        drafts=drafts,
    )


# ---------------------------------------------------------------- 泄题标记


def leak_markers(question: dict[str, Any]) -> list[str]:
    """不能出现在提示、换种讲法、错项分析和模型输出里的答案表述。比较时两边都做 fold。"""
    markers = list(question.get("teaching", {}).get("leak_markers", []))
    answer = question["answer"]["value"]
    if question["answer_mode"] in _CHOICE_MODES:
        keys = sorted(answer)
        for key in {*keys, "".join(keys)}:
            markers += [
                f"选{key}",
                f"应选{key}",
                f"故选{key}",
                f"答案是{key}",
                f"答案为{key}",
                f"{key}正确",
                f"{key}项正确",
                f"选项{key}正确",
                f"{key}是对的",
            ]
    elif question["answer_mode"] == "proof":
        pass  # 关键构造和关键变形推不出标记：全由题目自己在 leak_markers 里列
    elif question["answer_mode"] == "experiment":
        # 数据表里留空格子的参考值（键是 "表键.行键.列键"）：提示里不能出现这些数
        for cell_key, value in answer.items():
            text = value.strip() if isinstance(value, str) else ""
            if cell_key.count(".") == 2 and len(text) >= 3 and _NUMBER_LIKE.match(text):
                markers.append(text)
    else:
        rules = question["answer"].get("equivalence_rules", {})
        for blank, value in answer.items():
            if rules.get(blank, {}).get("type") != "numeric":
                continue  # 区间与表达式的写法太多，由题目自己在 leak_markers 里列出
            markers += [
                f"答案是{value}",
                f"答案为{value}",
                f"结果是{value}",
                f"结果为{value}",
                f"最小值是{value}",
                f"最小值为{value}",
                f"最大值是{value}",
                f"最大值为{value}",
                f"等于{value}",
                f"={value}",
            ]
    return markers


def find_leak(text: str, markers: list[str]) -> str | None:
    folded = grading.fold(text)
    return next((marker for marker in markers if grading.fold(marker) in folded), None)


# ---------------------------------------------------------------- 校验


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in _strings(value)]
    return []


def _nonempty_text(value: Any, limit: int = _MAX_TEXT) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _check_solution(
    key: str, name: str, solution: dict[str, Any], expected_final: str | None
) -> list[str]:
    problems = []
    steps = solution.get("steps")
    if not isinstance(steps, list) or not steps or not all(_nonempty_text(step) for step in steps):
        problems.append(f"{key}: solutions.{name}.steps 不能为空")
    final_answer = solution.get("final_answer")
    if not _nonempty_text(final_answer):
        problems.append(f"{key}: solutions.{name}.final_answer 不能为空")
    elif expected_final is not None and final_answer != expected_final:
        problems.append(f"{key}: solutions.{name}.final_answer 与答案不一致")
    for point in solution.get("key_points", []):
        if not _nonempty_text(point, _MAX_SHORT):
            problems.append(f"{key}: solutions.{name}.key_points 每条应在 {_MAX_SHORT} 字以内")
    return problems


def _short_key(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 16


def _check_no_subquestions(key: str, question: dict[str, Any]) -> list[str]:
    problems = _check_no_experiment_content(key, question) + _check_no_proof_content(key, question)
    if question["content"].get("subquestions"):
        problems.append(f"{key}: 选择题和填空题不分小问（content.subquestions 只用于解答题）")
    return problems


def _check_no_experiment_content(key: str, question: dict[str, Any]) -> list[str]:
    content = question["content"]
    if content.get("data_tables") or content.get("safety"):
        return [f"{key}: 只有实验题才能有 content.data_tables 和 content.safety"]
    return []


def _check_no_proof_content(key: str, question: dict[str, Any]) -> list[str]:
    if question["content"].get("proof"):
        return [f"{key}: 只有证明题才能有 content.proof"]
    return []


def _check_points(
    key: str,
    question: dict[str, Any],
    valid_parts: list[str],
    required_parts: list[str],
    where_name: str,
) -> list[str]:
    """自查要点：只有 key、part、text 三个字段（不带分值）；part 要指向存在的小问（或数据表）；
    每个必须覆盖的小问（或数据表）至少有一条要点。解答题和实验题共用。"""
    problems: list[str] = []
    points = (question.get("rubric") or {}).get("points")
    if not isinstance(points, list) or not 1 <= len(points) <= _MAX_POINTS:
        problems.append(
            f"{key}: rubric.points 至少一条、至多 {_MAX_POINTS} 条（提交后给学生对照自查）"
        )
        points = []
    point_keys: list[str] = []
    covered: set[str] = set()
    for index, point in enumerate(points):
        where = f"rubric.points[{index}]"
        if not isinstance(point, dict) or set(point) != _POINT_FIELDS:
            problems.append(f"{key}: {where} 只能有 key、part、text 三个字段（自查要点不带分值）")
            continue
        if _short_key(point["key"]):
            point_keys.append(point["key"])
        else:
            problems.append(f"{key}: {where}.key 不能为空且不超过 16 个字符")
        if not _nonempty_text(point["text"], _MAX_SHORT):
            problems.append(f"{key}: {where}.text 不能为空且不超过 {_MAX_SHORT} 字")
        part = point["part"]
        if part is None:
            continue
        if part in valid_parts:
            covered.add(part)
        else:
            problems.append(f"{key}: {where}.part 指向不存在的{where_name} {part!r}")
    if len(set(point_keys)) != len(point_keys):
        problems.append(f"{key}: rubric.points 的 key 不能重复")
    problems += [
        f"{key}: rubric.points 没有覆盖{where_name} {part}"
        for part in required_parts
        if part not in covered
    ]
    return problems


def _check_written(key: str, question: dict[str, Any]) -> list[str]:
    """解答题：分小问作答，不自动评分；提交之后学生对照 rubric.points 自查。

    这里只能保证结构自洽——每个小问有参考答案、有至少一条自查要点，要点不带分值，
    提示不泄题（泄题标记必须由题目自己列：一段话的答案没法自动推出来）。
    """
    problems: list[str] = []
    content = question["content"]
    if content.get("options") or content.get("blanks"):
        problems.append(f"{key}: 解答题不能有 content.options 或 content.blanks")
    problems += _check_no_experiment_content(key, question)
    problems += _check_no_proof_content(key, question)

    subquestions = content.get("subquestions")
    if not isinstance(subquestions, list) or not 1 <= len(subquestions) <= _MAX_PARTS:
        problems.append(f"{key}: content.subquestions 至少一个、至多 {_MAX_PARTS} 个")
        subquestions = []
    part_keys: list[str] = []
    for index, sub in enumerate(subquestions):
        where = f"content.subquestions[{index}]"
        if not isinstance(sub, dict):
            problems.append(f"{key}: {where} 不是对象")
            continue
        if _short_key(sub.get("key")):
            part_keys.append(sub["key"])
        else:
            problems.append(f"{key}: {where}.key 不能为空且不超过 16 个字符")
        if not _nonempty_text(sub.get("stem")):
            problems.append(f"{key}: {where}.stem 不能为空")
        if sub.get("answer_mode", "written") != "written":
            problems.append(f"{key}: {where}.answer_mode 必须是 written")
        if sub.get("options") or sub.get("blanks"):
            problems.append(f"{key}: {where} 不能带选项或空位")
    if len(set(part_keys)) != len(part_keys):
        problems.append(f"{key}: content.subquestions 的 key 不能重复")

    values = question["answer"].get("value")
    if (
        not isinstance(values, dict)
        or set(values) != set(part_keys)
        or not all(_nonempty_text(text) for text in values.values())
    ):
        problems.append(f"{key}: answer.value 必须给出每个小问的参考答案文字")

    problems += _check_points(key, question, part_keys, part_keys, "小问")

    markers = (question.get("teaching") or {}).get("leak_markers")
    if (
        not isinstance(markers, list)
        or not markers
        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)
    ):
        problems.append(
            f"{key}: teaching.leak_markers 不能为空（解答题的答案推不出泄题标记，要题目自己列）"
        )
    return problems


def _check_safety(key: str, content: dict[str, Any]) -> list[str]:
    """实验安全提示（PRD §5：审核实验安全提示）：每道实验题必须有，高风险的现在不收录。"""
    safety = content.get("safety")
    if not isinstance(safety, dict) or set(safety) != {"level", "notes"}:
        return [
            f"{key}: content.safety 必须有 level 和 notes"
            "（实验题必须有安全提示，上线前由审核员确认）"
        ]
    problems: list[str] = []
    level = safety["level"]
    if level == "high":
        problems.append(
            f"{key}: content.safety.level 是 high：高风险实验现在不收录，还没有专项审核流程"
        )
    elif level not in _SAFETY_LEVELS:
        problems.append(f"{key}: content.safety.level 取值无效：{level!r}")
    notes = safety["notes"]
    if (
        not isinstance(notes, list)
        or not 1 <= len(notes) <= _MAX_SAFETY_NOTES
        or not all(_nonempty_text(note, _MAX_SHORT) for note in notes)
    ):
        problems.append(
            f"{key}: content.safety.notes 至少一条、至多 {_MAX_SAFETY_NOTES} 条，每条不超过 {_MAX_SHORT} 字"
        )
    return problems


def _check_table(key: str, where: str, table: Any) -> tuple[list[str], str | None, list[str]]:
    """一张数据表：返回 (问题, 表键, 留空格子的键 "表键.行键.列键")。"""
    if not isinstance(table, dict):
        return [f"{key}: {where} 不是对象"], None, []
    problems: list[str] = []
    table_key = table.get("key")
    if not (isinstance(table_key, str) and _TABLE_KEY.match(table_key)):
        problems.append(f"{key}: {where}.key 只能用字母、数字、下划线，1~16 个字符")
        table_key = None
    if not _nonempty_text(table.get("title"), 120):
        problems.append(f"{key}: {where}.title 不能为空且不超过 120 字")

    column_keys: list[str] = []
    columns = table.get("columns")
    if not isinstance(columns, list) or not 1 <= len(columns) <= _MAX_COLUMNS:
        problems.append(f"{key}: {where}.columns 至少一列、至多 {_MAX_COLUMNS} 列")
        columns = []
    for index, column in enumerate(columns):
        here = f"{where}.columns[{index}]"
        if not isinstance(column, dict) or set(column) != {"key", "label", "unit"}:
            problems.append(f"{key}: {here} 只能有 key、label、unit 三个字段")
            continue
        if isinstance(column["key"], str) and _TABLE_KEY.match(column["key"]):
            column_keys.append(column["key"])
        else:
            problems.append(f"{key}: {here}.key 只能用字母、数字、下划线，1~16 个字符")
        if not _nonempty_text(column["label"], 40):
            problems.append(f"{key}: {here}.label 不能为空且不超过 40 字")
        unit = column["unit"]
        if unit is not None and not _nonempty_text(unit, 16):
            problems.append(f"{key}: {here}.unit 要么是 null，要么是不超过 16 字的单位")
    if len(set(column_keys)) != len(column_keys):
        problems.append(f"{key}: {where}.columns 的 key 不能重复")

    blanks: list[str] = []
    row_keys: list[str] = []
    rows = table.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_ROWS:
        problems.append(f"{key}: {where}.rows 至少一行、至多 {_MAX_ROWS} 行")
        rows = []
    for index, row in enumerate(rows):
        here = f"{where}.rows[{index}]"
        if not isinstance(row, dict) or set(row) != {"key", "label", "cells"}:
            problems.append(f"{key}: {here} 只能有 key、label、cells 三个字段")
            continue
        if isinstance(row["key"], str) and _TABLE_KEY.match(row["key"]):
            row_keys.append(row["key"])
        else:
            problems.append(f"{key}: {here}.key 只能用字母、数字、下划线，1~16 个字符")
        if row["label"] is not None and not _nonempty_text(row["label"], 40):
            problems.append(f"{key}: {here}.label 要么是 null，要么是不超过 40 字的文字")
        cells = row["cells"]
        if not isinstance(cells, list) or not all(
            isinstance(cell, dict) and set(cell) == {"col", "text"} for cell in cells
        ):
            problems.append(f"{key}: {here}.cells 每个格子只能有 col、text 两个字段")
            continue
        cell_columns = [cell["col"] for cell in cells]
        if sorted(cell_columns) != sorted(column_keys):
            problems.append(f"{key}: {here}.cells 必须给每一列恰好一个格子")
        for cell in cells:
            value = cell["text"]
            if value is None:
                if table_key is not None and isinstance(row["key"], str):
                    blanks.append(f"{table_key}.{row['key']}.{cell['col']}")
            elif not _nonempty_text(value, _MAX_CELL_TEXT):
                problems.append(
                    f"{key}: {here} 的格子 {cell['col']} 要么留空（null），要么是不超过 {_MAX_CELL_TEXT} 字的文字"
                )
    if len(set(row_keys)) != len(row_keys):
        problems.append(f"{key}: {where}.rows 的 key 不能重复")
    return problems, table_key, blanks


def _check_experiment(key: str, question: dict[str, Any]) -> list[str]:
    """实验题：带数据表和安全提示的主观题。不自动评分，提交之后学生对照参考数据和 rubric.points 自查。

    这里只能保证结构自洽：每个留空的格子都有参考值、每个小问有参考答案、每张有留空格子的表和每个小问
    都有自查要点，高风险的实验不收录，提示不泄题（泄题标记要题目自己列，数值参考值会自动加进去）。
    """
    problems: list[str] = []
    content = question["content"]
    if content.get("options") or content.get("blanks"):
        problems.append(f"{key}: 实验题不能有 content.options 或 content.blanks")
    problems += _check_no_proof_content(key, question)
    problems += _check_safety(key, content)

    tables = content.get("data_tables")
    if tables is None:
        tables = []
    if not isinstance(tables, list) or len(tables) > _MAX_TABLES:
        problems.append(f"{key}: content.data_tables 至多 {_MAX_TABLES} 张表")
        tables = []
    table_keys: list[str] = []
    blank_cells: list[str] = []
    tables_with_blanks: list[str] = []
    for index, table in enumerate(tables):
        found, table_key, blanks = _check_table(key, f"content.data_tables[{index}]", table)
        problems += found
        if table_key is not None:
            table_keys.append(table_key)
            if blanks:
                tables_with_blanks.append(table_key)
        blank_cells += blanks
    if len(set(table_keys)) != len(table_keys):
        problems.append(f"{key}: content.data_tables 的 key 不能重复")

    subquestions = content.get("subquestions")
    if subquestions is None:
        subquestions = []
    if not isinstance(subquestions, list) or len(subquestions) > _MAX_PARTS:
        problems.append(f"{key}: content.subquestions 至多 {_MAX_PARTS} 个")
        subquestions = []
    part_keys: list[str] = []
    for index, sub in enumerate(subquestions):
        where = f"content.subquestions[{index}]"
        if not isinstance(sub, dict):
            problems.append(f"{key}: {where} 不是对象")
            continue
        if isinstance(sub.get("key"), str) and _TABLE_KEY.match(sub["key"]):
            part_keys.append(sub["key"])
        else:
            problems.append(f"{key}: {where}.key 只能用字母、数字、下划线，1~16 个字符")
        if not _nonempty_text(sub.get("stem")):
            problems.append(f"{key}: {where}.stem 不能为空")
        if sub.get("answer_mode", "written") != "written":
            problems.append(f"{key}: {where}.answer_mode 必须是 written")
        if sub.get("options") or sub.get("blanks"):
            problems.append(f"{key}: {where} 不能带选项或空位")
    if len(set(part_keys)) != len(part_keys):
        problems.append(f"{key}: content.subquestions 的 key 不能重复")
    if set(part_keys) & set(table_keys):
        problems.append(
            f"{key}: 小问的 key 和数据表的 key 不能相同（自查要点靠它们指向各自的部分）"
        )
    if not blank_cells and not part_keys:
        problems.append(f"{key}: 实验题至少要有一个留空的格子或一个小问")

    values = question["answer"].get("value")
    expected = [*part_keys, *blank_cells]
    if (
        not isinstance(values, dict)
        or set(values) != set(expected)
        or not all(_nonempty_text(values[part]) for part in part_keys if part in values)
        or not all(
            _nonempty_text(values[cell], _MAX_CELL_TEXT) for cell in blank_cells if cell in values
        )
    ):
        problems.append(
            f"{key}: answer.value 必须给出每个小问的参考答案文字，"
            "和每个留空格子（键是 表键.行键.列键）的参考值"
        )

    problems += _check_points(
        key, question, [*part_keys, *table_keys], [*part_keys, *tables_with_blanks], "小问或数据表"
    )

    markers = (question.get("teaching") or {}).get("leak_markers")
    if (
        not isinstance(markers, list)
        or not markers
        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)
    ):
        problems.append(
            f"{key}: teaching.leak_markers 不能为空（实验题的文字答案推不出泄题标记，要题目自己列）"
        )
    return problems


def _check_proof_statement(key: str, content: dict[str, Any]) -> list[str]:
    """证明题的已知和求证：只有 givens 和 claim 两项。"""
    proof = content.get("proof")
    if not isinstance(proof, dict) or set(proof) != {"givens", "claim"}:
        return [f"{key}: content.proof 必须有 givens 和 claim 两项（证明题的已知和求证）"]
    problems: list[str] = []
    givens = proof["givens"]
    if (
        not isinstance(givens, list)
        or len(givens) > _MAX_GIVENS
        or not all(_nonempty_text(given, _MAX_GIVEN) for given in givens)
    ):
        problems.append(
            f"{key}: content.proof.givens 至多 {_MAX_GIVENS} 条，每条不能为空、不超过 {_MAX_GIVEN} 字"
        )
    if not _nonempty_text(proof["claim"], _MAX_CLAIM):
        problems.append(f"{key}: content.proof.claim 不能为空且不超过 {_MAX_CLAIM} 字")
    return problems


def _reference_steps(question: dict[str, Any]) -> list[dict[str, Any]]:
    """证明题的参考证明（形状不对时返回空列表，由 _check_reference_proof 指出来）。"""
    value = (question.get("answer") or {}).get("value")
    steps = value.get("steps") if isinstance(value, dict) else None
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def _check_reference_proof(key: str, question: dict[str, Any]) -> list[str]:
    """参考证明：answer.value 是 {steps: [{stage, text, reason}]}。参考证明自己要示范"每一步有依据"，
    并且以结论收尾。"""
    value = question["answer"].get("value")
    if not isinstance(value, dict) or set(value) != {"steps"}:
        return [
            f"{key}: answer.value 必须是 {{steps: [...]}}（参考证明，每步有 stage、text、reason）"
        ]
    steps = value["steps"]
    if not isinstance(steps, list) or not _MIN_PROOF_STEPS <= len(steps) <= _MAX_PROOF_STEPS:
        return [f"{key}: answer.value.steps 至少 {_MIN_PROOF_STEPS} 步、至多 {_MAX_PROOF_STEPS} 步"]
    problems: list[str] = []
    for index, step in enumerate(steps):
        where = f"answer.value.steps[{index}]"
        if not isinstance(step, dict) or set(step) != {"stage", "text", "reason"}:
            problems.append(f"{key}: {where} 只能有 stage、text、reason 三个字段")
            continue
        if step["stage"] not in _STAGES:
            problems.append(f"{key}: {where}.stage 取值无效：{step['stage']!r}")
        if not _nonempty_text(step["text"], _MAX_STEP_TEXT):
            problems.append(f"{key}: {where}.text 不能为空且不超过 {_MAX_STEP_TEXT} 字")
        if not _nonempty_text(step["reason"], _MAX_STEP_REASON):
            problems.append(
                f"{key}: {where}.reason 不能为空且不超过 {_MAX_STEP_REASON} 字"
                "（参考证明要示范每一步都有依据）"
            )
    last = steps[-1]
    if isinstance(last, dict) and last.get("stage") != "conclusion":
        problems.append(
            f"{key}: answer.value.steps 的最后一步必须是 conclusion（证明要以结论收尾）"
        )
    return problems


def _check_proof(key: str, question: dict[str, Any]) -> list[str]:
    """证明题：有已知和求证，学生把证明写成一步一步；不自动评分，提交之后学生对照参考证明和 rubric.points 自查。

    这里只能保证结构自洽——参考证明每步有依据并以结论收尾、参考证明里出现过的每个阶段都有至少一条自查要点、
    要点不带分值，提示不泄题（泄题标记必须由题目自己列：关键构造和关键变形推不出来）。
    """
    problems: list[str] = []
    content = question["content"]
    if content.get("options") or content.get("blanks"):
        problems.append(f"{key}: 证明题不能有 content.options 或 content.blanks")
    if content.get("subquestions"):
        problems.append(f"{key}: 证明题不分小问（content.subquestions 只用于解答题和实验题）")
    problems += _check_no_experiment_content(key, question)
    problems += _check_proof_statement(key, content)
    problems += _check_reference_proof(key, question)

    used = {step.get("stage") for step in _reference_steps(question)}
    problems += _check_points(
        key, question, list(_STAGES), [stage for stage in _STAGES if stage in used], "证明阶段"
    )

    markers = (question.get("teaching") or {}).get("leak_markers")
    if (
        not isinstance(markers, list)
        or not markers
        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)
    ):
        problems.append(
            f"{key}: teaching.leak_markers 不能为空（证明题的关键构造推不出泄题标记，要题目自己列）"
        )
    return problems


def _check_choice(key: str, question: dict[str, Any]) -> list[str]:
    problems = _check_no_subquestions(key, question)
    options = question["content"].get("options") or []
    option_keys = [option.get("key") for option in options]
    if len(option_keys) < 2 or len(set(option_keys)) != len(option_keys):
        problems.append(f"{key}: content.options 至少两个且键不能重复")
    if not all(_nonempty_text(option.get("text")) for option in options):
        problems.append(f"{key}: content.options 的文本不能为空")

    answer = question["answer"].get("value")
    if not isinstance(answer, list) or not answer or not set(answer) <= set(option_keys):
        problems.append(f"{key}: answer.value 含有不存在的选项")
    elif question["answer_mode"] == "single_choice" and len(answer) != 1:
        problems.append(f"{key}: 单选题必须恰好有一个正确选项")
    elif question["answer_mode"] == "multiple_choice" and len(set(answer)) < 2:
        problems.append(f"{key}: 多选题至少要有两个正确选项")

    analysis = question.get("teaching", {}).get("option_analysis") or {}
    if set(analysis) != set(option_keys) or not all(
        _nonempty_text(text) for text in analysis.values()
    ):
        problems.append(f"{key}: teaching.option_analysis 必须覆盖每个选项")

    rule = (question.get("rubric") or {}).get("multi_choice_rule")
    if rule is not None and rule not in grading.MULTI_CHOICE_RULES:
        problems.append(f"{key}: rubric.multi_choice_rule 取值无效：{rule!r}")
    return problems


def _check_fill(key: str, question: dict[str, Any]) -> list[str]:
    problems = _check_no_subquestions(key, question)
    blanks = [blank.get("key") for blank in question["content"].get("blanks") or []]
    if not blanks or len(set(blanks)) != len(blanks):
        problems.append(f"{key}: content.blanks 至少一个且键不能重复")
    answer = question["answer"]
    values = answer.get("value")
    rules = answer.get("equivalence_rules") or {}
    units = answer.get("units") or {}
    if not isinstance(values, dict) or set(values) != set(blanks):
        return [*problems, f"{key}: answer.value 与空位不一致"]

    for blank in blanks:
        rule = rules.get(blank) or {}
        if rule.get("type") not in grading.RULE_TYPES:
            problems.append(
                f"{key}: answer.equivalence_rules.{blank} 类型未知：{rule.get('type')!r}"
            )
            continue
        unit = units.get(blank)
        canonical = str(values[blank])
        if unit and unit.get("required"):
            canonical = f"{canonical} {unit['accepted'][0]}"
        try:
            result = grading.check_blank(rule, str(values[blank]), unit, canonical)
        except (ValueError, KeyError, IndexError, mathparse.EvalError):
            result = None
        if result is None or result.status != "correct":
            problems.append(f"{key}: answer.value.{blank} 通不过自己的判定规则")
    return problems


def _check_question(
    question: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    by_key: dict[str, dict[str, Any]],
    *,
    forbid_exam_claims: bool = True,
) -> list[str]:
    key = str(question.get("key", "?"))
    problems: list[str] = []
    mode = question.get("answer_mode")
    if mode not in _TYPE_BY_MODE:
        return [
            f"{key}: answer_mode {mode!r} 不在本阶段支持的范围内（单选、多选、填空、解答、实验、证明）"
        ]
    if question.get("type") != _TYPE_BY_MODE[mode]:
        problems.append(f"{key}: type 与 answer_mode 不一致")
    if question.get("subject") not in launch.SUBJECT_NAMES:
        problems.append(f"{key}: subject 不是首发学科")
    difficulty = question.get("difficulty")
    if isinstance(difficulty, bool) or not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
        problems.append(f"{key}: difficulty 应为 1~5 的整数")
    if question.get("grade") is not None and question["grade"] not in launch.GRADE_NUMBERS:
        problems.append(f"{key}: grade 取值无效")
    if not _nonempty_text(question.get("title"), 120):
        problems.append(f"{key}: title 不能为空且不超过 120 字")
    if not _nonempty_text(question.get("content", {}).get("stem")):
        problems.append(f"{key}: content.stem 不能为空")

    for code in question.get("knowledge") or [None]:
        if code not in nodes:
            problems.append(f"{key}: 知识点 {code} 不存在")
        elif nodes[code]["subject"] != question.get("subject"):
            problems.append(f"{key}: 知识点 {code} 与题目学科不一致")

    if mode in _CHOICE_MODES:
        problems += _check_choice(key, question)
    elif mode == "written":
        problems += _check_written(key, question)
    elif mode == "experiment":
        problems += _check_experiment(key, question)
    elif mode == "proof":
        problems += _check_proof(key, question)
    else:
        problems += _check_fill(key, question)

    teaching = question.get("teaching") or {}
    hints = teaching.get("hints")
    if (
        not isinstance(hints, list)
        or not 2 <= len(hints) <= 4
        or not all(_nonempty_text(h) for h in hints)
    ):
        problems.append(f"{key}: teaching.hints 需要 2~4 层非空提示")
        hints = []
    if not _nonempty_text(teaching.get("concept"), _MAX_SHORT):
        problems.append(f"{key}: teaching.concept 不能为空")

    # 泄题检查：提示、换种讲法、错误选项的分析都不能把答案说出来
    try:
        markers = leak_markers(question)
    except (KeyError, TypeError, AttributeError):
        markers = []
    guarded: list[tuple[str, str]] = [
        (f"teaching.hints[{i}]", text) for i, text in enumerate(hints)
    ]
    if teaching.get("concept_rephrase"):
        guarded.append(("teaching.concept_rephrase", teaching["concept_rephrase"]))
    if mode in _CHOICE_MODES and isinstance(question["answer"].get("value"), list):
        correct = set(question["answer"]["value"])
        guarded += [
            (f"teaching.option_analysis.{option}", text)
            for option, text in (teaching.get("option_analysis") or {}).items()
            if option not in correct and isinstance(text, str)
        ]
    for where, text in guarded:
        marker = find_leak(text, markers)
        if marker is not None:
            problems.append(f"{key}: {where} 可能泄题，命中 {marker!r}")

    solutions = question.get("solutions") or {}
    expected_final = None
    if mode in _CHOICE_MODES and isinstance(question["answer"].get("value"), list):
        expected_final = "".join(sorted(question["answer"]["value"]))
    if "standard" not in solutions:
        problems.append(f"{key}: 缺少 solutions.standard")
    else:
        problems += _check_solution(key, "standard", solutions["standard"], expected_final)
    if "fast" in solutions:
        fast = solutions["fast"]
        problems += _check_solution(key, "fast", fast, expected_final)
        conditions = fast.get("conditions")
        if (
            not isinstance(conditions, list)
            or not conditions
            or not all(_nonempty_text(c) for c in conditions)
        ):
            problems.append(
                f"{key}: solutions.fast.conditions 不能为空（快速解法必须写明适用条件）"
            )
        if not _nonempty_text(fast.get("boundary")):
            problems.append(f"{key}: solutions.fast.boundary 不能为空（要说明不适用的情形）")

    visual = teaching.get("visual")
    if visual is not None:
        try:
            visual_registry().normalize(visual.get("template_id", ""), visual.get("params") or {})
        except VisualTemplateError as error:
            problems.append(f"{key}: teaching.visual 无效：{error}")
        if not _nonempty_text(visual.get("caption")):
            problems.append(f"{key}: teaching.visual.caption 不能为空")

    for tag in question.get("region_tags") or []:
        if tag.get("region") not in launch.REGION_NAMES:
            problems.append(f"{key}: region_tags 的地区 {tag.get('region')} 不是首发地区")
        year_from, year_to = tag.get("exam_year_from"), tag.get("exam_year_to")
        if year_from is not None and year_to is not None and year_from > year_to:
            problems.append(f"{key}: region_tags 的 exam_year_from 大于 exam_year_to")

    base_key = question.get("variant_of")
    if base_key is not None:
        base = by_key.get(base_key)
        if base is None:
            problems.append(f"{key}: variant_of 指向不存在的题 {base_key}")
        elif base.get("variant_of"):
            problems.append(f"{key}: variant_of 指向的题本身是变式")
        elif base.get("subject") != question.get("subject"):
            problems.append(f"{key}: variant_of 指向的题学科不同")

    texts = _strings(question)
    if any(contains_blocked_markup(text) for text in texts):
        problems.append(f"{key}: 文本包含不允许的标记")
    if forbid_exam_claims and any(claim in text for text in texts for claim in _REAL_EXAM_CLAIMS):
        problems.append(f"{key}: 自编样题不得标称真题或原题")
    if any(len(text) > _MAX_TEXT for text in texts):
        problems.append(f"{key}: 单段文本超过 {_MAX_TEXT} 字")
    return problems


def check_question(
    question: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    by_key: dict[str, dict[str, Any]],
    *,
    forbid_exam_claims: bool = True,
) -> list[str]:
    """对一道（种子形状的）题做入库同款的程序校验；审核后台对库里的题也用它。

    forbid_exam_claims：自编样题不得标称真题或原题；有授权来源的真题没有这条限制。
    """
    return _check_question(question, nodes, by_key, forbid_exam_claims=forbid_exam_claims)


def _check_graph(bundle: SeedBundle) -> list[str]:
    problems = []
    codes = [node.get("code") for node in bundle.nodes]
    if len(set(codes)) != len(codes):
        problems.append("知识点 code 重复")
    for node in bundle.nodes:
        if node.get("subject") not in launch.SUBJECT_NAMES:
            problems.append(f"知识点 {node.get('code')} 的学科不是首发学科")
        if not _nonempty_text(node.get("title"), 120) or not _nonempty_text(
            node.get("summary"), 500
        ):
            problems.append(f"知识点 {node.get('code')} 需要标题和一句话说明")

    graph: dict[str, list[str]] = {code: [] for code in codes}
    for prereq, target in bundle.edges:
        missing = [code for code in (prereq, target) if code not in graph]
        if missing:
            problems += [f"知识点依赖引用了不存在的知识点 {code}" for code in missing]
        elif prereq == target:
            problems.append(f"知识点 {prereq} 存在自环")
        else:
            graph[prereq].append(target)

    # 应用层检环（docs/04）：深度优先，遇到正在访问的节点即成环
    state: dict[str, int] = {}

    def visit(code: str, trail: list[str]) -> None:
        state[code] = 1
        for nxt in graph[code]:
            if state.get(nxt) == 1:
                problems.append("知识点依赖存在环：" + " → ".join([*trail, code, nxt]))
            elif nxt not in state:
                visit(nxt, [*trail, code])
        state[code] = 2

    for code in graph:
        if code not in state:
            visit(code, [])
    return problems


def validate_seed(bundle: SeedBundle) -> list[str]:
    """返回发现的问题；空列表表示通过。"""
    problems = _check_graph(bundle)
    nodes = {node["code"]: node for node in bundle.nodes if "code" in node}
    by_key: dict[str, dict[str, Any]] = {}
    everything = [*bundle.questions, *bundle.drafts]
    for question in everything:
        key = question.get("key")
        if key in by_key:
            problems.append(f"题目 key 重复：{key}")
        by_key[key] = question
    for question in everything:
        problems += _check_question(question, nodes, by_key)
    return problems


# ---------------------------------------------------------------- 入库


def apply_seed(db: Session, bundle: SeedBundle, now: datetime) -> int:
    for node in bundle.nodes:
        db.add(
            KnowledgeNode(
                id=seed_uuid("knowledge", node["code"]),
                subject=node["subject"],
                code=node["code"],
                title=node["title"],
                summary=node["summary"],
                created_at=now,
            )
        )
    db.flush()
    for prereq, target in bundle.edges:
        db.add(
            KnowledgeEdge(
                id=seed_uuid("edge", f"{prereq}>{target}"),
                prereq_id=seed_uuid("knowledge", prereq),
                target_id=seed_uuid("knowledge", target),
            )
        )

    # 先入母题再入变式，满足 variant_of 的外键
    draft_keys = {question["key"] for question in bundle.drafts}
    ordered = sorted(
        [*bundle.questions, *bundle.drafts], key=lambda q: q.get("variant_of") is not None
    )
    for question in ordered:
        key = question["key"]
        is_draft = key in draft_keys
        question_id = seed_uuid("question", key)
        teaching = dict(question.get("teaching") or {})
        teaching["leak_markers"] = leak_markers(question)
        content = question["content"]
        solutions = question["solutions"]
        variant_of = question.get("variant_of")

        db.add(
            Question(
                id=question_id,
                subject=question["subject"],
                type=question["type"],
                answer_mode=question["answer_mode"],
                status="draft" if is_draft else "published",
                version=1,
                difficulty=question["difficulty"],
                grade=question.get("grade"),
                source_type="self_authored",
                source_category="foundation",
                source_name=ENGINEERING_SAMPLE_NAME,
                source_year=None,
                source_license=ENGINEERING_SAMPLE_LICENSE,
                source_url=None,
                variant_of_id=seed_uuid("question", variant_of) if variant_of else None,
                # 待审样题有"作者"（一个固定的工程占位 ID），审核后台才能执行"不能审自己的题"
                created_by=seed_uuid("author", DRAFT_AUTHOR_KEY) if is_draft else None,
                published_at=None if is_draft else now,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            QuestionVersion(
                id=seed_uuid("question_version", f"{key}:1"),
                question_id=question_id,
                version=1,
                content_json={
                    "title": question["title"],
                    "stem": content["stem"],
                    "options": content.get("options") or [],
                    "blanks": content.get("blanks") or [],
                    "subquestions": [
                        {
                            "key": sub["key"],
                            "stem": sub["stem"],
                            "answer_mode": "written",
                            "options": [],
                            "blanks": [],
                        }
                        for sub in content.get("subquestions") or []
                    ],
                    "attachments": [],
                    "data_tables": content.get("data_tables") or [],
                    "safety": content.get("safety"),
                    "proof": content.get("proof"),
                },
                answer_json={
                    "value": question["answer"]["value"],
                    "equivalence_rules": question["answer"].get("equivalence_rules") or {},
                    "units": question["answer"].get("units") or {},
                },
                teaching_json=teaching,
                created_at=now,
            )
        )
        for code in question["knowledge"]:
            db.add(
                QuestionKnowledge(
                    question_id=question_id, knowledge_id=seed_uuid("knowledge", code)
                )
            )
        db.add(
            Solution(
                id=seed_uuid("solution", f"{key}:1:standard"),
                question_id=question_id,
                version=1,
                kind="standard",
                content_json=solutions["standard"],
                reviewed=not is_draft,
                created_at=now,
            )
        )
        if "fast" in solutions:
            fast = solutions["fast"]
            db.add(
                Solution(
                    id=seed_uuid("solution", f"{key}:1:fast"),
                    question_id=question_id,
                    version=1,
                    kind="fast",
                    content_json={"steps": fast["steps"], "final_answer": fast["final_answer"]},
                    conditions_json={
                        "conditions": fast["conditions"],
                        "boundary": fast["boundary"],
                    },
                    reviewed=not is_draft,
                    created_at=now,
                )
            )
        db.add(
            Rubric(
                id=seed_uuid("rubric", f"{key}:1"),
                question_id=question_id,
                version=1,
                rubric_json=question.get("rubric") or {},
                created_at=now,
            )
        )
        for tag in question.get("region_tags") or []:
            db.add(
                QuestionRegionApplicability(
                    id=seed_uuid("region_tag", f"{key}:{tag['region']}"),
                    question_id=question_id,
                    origin_region_code=None,
                    recommended_region_code=tag["region"],
                    exam_year_from=tag.get("exam_year_from"),
                    exam_year_to=tag.get("exam_year_to"),
                    review_status="approved",
                    note=REGION_TAG_NOTE,
                    created_at=now,
                    updated_at=now,
                )
            )
    return len(bundle.questions) + len(bundle.drafts)


def seed_if_empty(db: Session, now: datetime) -> int:
    """题库为空时写入样题，返回写入的题目数；已有题目则什么都不做。"""
    if db.scalar(select(func.count()).select_from(Question)):
        return 0
    bundle = load_seed()
    problems = validate_seed(bundle)
    if problems:
        raise ValueError("样题没有通过校验：\n" + "\n".join(problems))
    return apply_seed(db, bundle, now)
