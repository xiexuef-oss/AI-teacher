"""联调用到的样题数据：标题、数据表、参考值、要点、答案。

全部从样题（services/api/seed）和测试里的答案表（tests/support/flows.py）取，脚本里不重抄一遍：
样题改了，联调跟着变；改得让联调对不上（比如少了一道题、答案不再判对），
`tests/unit/test_e2e_tooling.py` 会先红。
"""

from __future__ import annotations

from functools import cache
from typing import Any

from e2e import _paths  # noqa: F401  # 先把后端和测试辅助放进 sys.path
from support import flows as test_answers
from support.seeds import qid
from tutor_api.services import grading
from tutor_api.services.content_seed import load_seed

Cell = tuple[str, str, str]  # (表键, 行键, 列键)

_ANSWER_TABLES: dict[str, dict[str, dict[str, Any]]] = {
    "correct": test_answers.CORRECT,
    "wrong": test_answers.WRONG,
    "written": test_answers.WRITTEN,
    "experiment": test_answers.EXPERIMENT,
    "proof": test_answers.PROOF,
}


@cache
def _questions() -> dict[str, dict[str, Any]]:
    return {question["key"]: question for question in load_seed().questions}


def question(key: str) -> dict[str, Any]:
    """样题（已发布的那些）的原始内容；没有这个 key 会抛 KeyError。"""
    return _questions()[key]


def title_of(key: str) -> str:
    return question(key)["title"]


def question_id(key: str) -> str:
    return qid(key)


def published_count(answer_mode: str | None = None) -> int:
    return sum(1 for item in _questions().values() if answer_mode in (None, item["answer_mode"]))


def blank_cells(key: str) -> list[Cell]:
    """实验题里留空、由学生填的格子，按表、行、列的顺序（和页面上输入框的顺序一致）。"""
    return grading.blank_cell_keys(question(key)["content"])


def reference_values(key: str) -> dict[Cell, str]:
    values = question(key)["answer"]["value"]
    return {cell: values[".".join(cell)] for cell in blank_cells(key)}


def points_of(key: str) -> list[dict[str, Any]]:
    return question(key)["rubric"]["points"]


def answer_for(key: str, kind: str) -> dict[str, Any]:
    """kind：correct / wrong（客观题）、written（解答题）、experiment（实验题）、proof（证明题）。"""
    return _ANSWER_TABLES[kind][key]
