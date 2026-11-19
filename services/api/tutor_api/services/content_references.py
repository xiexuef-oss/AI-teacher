"""Fixed-version reviewed content spans. IDs are ordinal, never arbitrary pointers."""

from __future__ import annotations

import hashlib
from collections import Counter

from sqlalchemy import select

from tutor_api.models import Rubric, Solution, TutorEventRow
from tutor_api.schemas import ContentSpanRef, TeachingReferenceLink


def blocks(content, teaching, solutions, rubric=None, answer=None):
    result = {}

    def add(key, text):
        if isinstance(text, str) and 0 < len(text) <= 4000:
            result[key] = text

    add("stem", content.get("stem"))
    for i, option in enumerate(content.get("options") or [], 1):
        add(f"option:{i}", option.get("text"))
    for i, sub in enumerate(content.get("subquestions") or [], 1):
        add(f"subquestion:{i}:stem", sub.get("stem"))
        for j, option in enumerate(sub.get("options") or [], 1):
            add(f"subquestion:{i}:option:{j}", option.get("text"))
    proof = content.get("proof") or {}
    for i, given in enumerate(proof.get("givens") or [], 1):
        add(f"proof:given:{i}", given)
    add("proof:claim", proof.get("claim"))
    for i, hint in enumerate(teaching.get("hints") or [], 1):
        add(f"hint:{i}", hint)
    add("rephrase", teaching.get("concept_rephrase"))
    for key in ("caption", "static_fallback"):
        add("visual:" + key, (teaching.get("visual") or {}).get(key))
    for kind, solution in solutions.items():
        for field, singular in (
            ("steps", "step"),
            ("conditions", "condition"),
            ("key_points", "key_point"),
        ):
            for i, text in enumerate(solution.get(field) or [], 1):
                add(f"solution:{kind}:{singular}:{i}", text)
        for field in ("final_answer", "boundary"):
            add(f"solution:{kind}:{field}", solution.get(field))
    rubric = rubric or {}
    values = (answer or {}).get("value") or {}
    for i, point in enumerate(rubric.get("points") or [], 1):
        add(f"rubric:point:{i}", point.get("text"))
    for i, step in enumerate(values.get("steps", []) if isinstance(values, dict) else [], 1):
        for field in ("text", "reason"):
            add(f"reference_step:{i}:{field}", step.get(field))
    # Reference cells refer to their physical table/row/column ordinals.
    for ti, table in enumerate(content.get("data_tables") or [], 1):
        for ri, row in enumerate(table.get("rows") or [], 1):
            for ci, column in enumerate(table.get("columns") or [], 1):
                cell = next(
                    (c for c in row.get("cells", []) if c.get("col") == column.get("key")), None
                )
                if isinstance(values, dict) and cell is not None and cell.get("text") is None:
                    value = values.get(f"{table.get('key')}.{row.get('key')}.{column.get('key')}")
                    add(f"reference_cell:{ti}:{ri}:{ci}", value)
    return result


def _label(block_id):
    parts = block_id.split(":")
    if block_id == "stem":
        return "题干"
    if parts[0] == "subquestion":
        return f"第{parts[1]}小问题干" if parts[2] == "stem" else f"第{parts[1]}小问选项{parts[3]}"
    if parts[0] == "option":
        return f"选项{parts[1]}"
    if parts[0] == "proof":
        return "证明求证" if parts[1] == "claim" else f"证明已知{parts[2]}"
    if parts[0] == "hint":
        return f"第{parts[1]}层提示"
    if block_id == "rephrase":
        return "换种讲法"
    if parts[0] == "solution":
        kind = "常规解法" if parts[1] == "standard" else "快速解法"
        field = {
            "step": "步骤",
            "final_answer": "最终结论",
            "condition": "适用条件",
            "boundary": "适用边界",
            "key_point": "要点",
        }[parts[2]]
        return kind + field + (parts[3] if len(parts) > 3 else "")
    if parts[0] == "visual":
        return "图解说明" if parts[1] == "caption" else "图解文字说明"
    if parts[0] == "rubric":
        return f"自查要点{parts[2]}"
    if parts[0] == "reference_cell":
        return f"参考表{parts[1]}第{parts[2]}行第{parts[3]}列"
    if parts[0] == "reference_step":
        return f"参考证明第{parts[1]}步" + ("文字" if parts[2] == "text" else "依据")
    raise ValueError("unknown reference block label")


def resolve(span, directory):
    span = ContentSpanRef.model_validate(span)
    text = directory.get(span.block_id)
    if (
        text is None
        or hashlib.sha256(text.encode()).hexdigest() != span.block_sha256
        or span.end > len(text)
    ):
        raise ValueError("reference block/hash/range does not match fixed version")
    return {**span.model_dump(), "block_text": text, "label": _label(span.block_id)}


def validate_links(content, teaching, solutions, rubric=None, answer=None):
    directory = blocks(content, teaching, solutions, rubric, answer)
    seen = set()
    counts = Counter()
    for raw in teaching.get("reference_links") or []:
        link = TeachingReferenceLink.model_validate(raw)
        target = link.target_block_id
        if target != "rephrase" and target not in directory:
            raise ValueError("reference target does not exist")
        span = resolve(link.source_span, directory)
        key = (target, span["block_id"], span["block_sha256"], span["start"], span["end"])
        if key in seen:
            raise ValueError("duplicate reference link")
        seen.add(key)
        counts[target] += 1
        if counts[target] > 8:
            raise ValueError("more than eight references for target")
    return directory


def version_blocks(db, version):
    solutions = {}
    for s in db.scalars(
        select(Solution).where(
            Solution.question_id == version.question_id, Solution.version == version.version
        )
    ):
        solutions[s.kind] = {**s.content_json, **(s.conditions_json or {})}
    rubric = db.scalar(
        select(Rubric).where(
            Rubric.question_id == version.question_id, Rubric.version == version.version
        )
    )
    return blocks(
        version.content_json,
        version.teaching_json or {},
        solutions,
        rubric.rubric_json if rubric else {},
        version.answer_json,
    )


def catalog(turn, targets):
    from tutor_api.services.content_seed import find_leak
    from tutor_api.services.grading import SUBJECTIVE_MODES

    if turn.session.origin == "review" and not turn.submitted:
        return []
    directory = version_blocks(turn.tc.db, turn.version)
    unlocked = {
        event.event_type
        for event in turn.tc.db.scalars(
            select(TutorEventRow).where(TutorEventRow.session_id == turn.session.id)
        )
        if event.event_type in ("standard", "fast", "visual")
        and event.event_json.get("meta", {}).get("question_id") == turn.version.question_id
        and event.event_json.get("meta", {}).get("question_version") == turn.version.version
    }
    # This action is explicitly exposing its own kind; used_solution alone never
    # unlocks the other kind or any future hint.
    unlocked.update(
        t.split(":")[1] for t in targets if t.startswith("solution:") and turn.session.used_solution
    )
    if "visual:caption" in targets and (turn.session.used_solution or turn.submitted):
        unlocked.add("visual")
    result = []
    seen = set()
    for raw in turn.teaching.get("reference_links") or []:
        try:
            link = TeachingReferenceLink.model_validate(raw)
            if link.target_block_id not in targets:
                continue
            span = resolve(link.source_span, directory)
            key = tuple(span[k] for k in ("block_id", "block_sha256", "start", "end"))
            block = span["block_id"]
            visible = False
            if (
                block == "stem"
                or (block.startswith("subquestion:") and block.endswith(":stem"))
                or block.startswith("proof:")
            ):
                visible = True
            elif block.startswith("option:") or (
                block.startswith("subquestion:") and ":option:" in block
            ):
                visible = turn.session.used_solution and "standard" in unlocked
            elif block.startswith("visual:"):
                visible = "visual" in unlocked
            elif block.startswith("hint:"):
                visible = int(block.split(":")[1]) <= turn.session.hint_level_revealed
            elif block.startswith("solution:"):
                visible = turn.session.used_solution and block.split(":")[1] in unlocked
            elif block.startswith("rubric:"):
                visible = turn.submitted > 0 and turn.question.answer_mode in SUBJECTIVE_MODES
            elif block.startswith("reference_cell:"):
                visible = turn.submitted > 0 and turn.question.answer_mode == "experiment"
            elif block.startswith("reference_step:"):
                visible = turn.submitted > 0 and turn.question.answer_mode == "proof"
            elif block == "rephrase":
                visible = (
                    bool(turn.teaching.get("concept_rephrase"))
                    and link.target_block_id == "rephrase"
                )
            if not visible:
                continue
            if not turn.session.used_solution and not block.startswith(
                ("rubric:", "reference_cell:", "reference_step:", "visual:")
            ):
                if not link.independent_safe or not (
                    block == "stem"
                    or block.startswith("proof:")
                    or (block.startswith("subquestion:") and block.endswith(":stem"))
                ):
                    continue
                if find_leak(span["block_text"], turn.teaching.get("leak_markers") or []):
                    continue
            if key not in seen:
                result.append(span)
                seen.add(key)
        except (ValueError, TypeError, KeyError):
            continue
    return result[:8]


def resolve_proposals(proposals, before, after):
    if not isinstance(proposals, list) or len(proposals) > 8:
        raise ValueError("model references must be an array of at most eight spans")
    allowed = {tuple(x[k] for k in ("block_id", "block_sha256", "start", "end")): x for x in before}
    current = {tuple(x[k] for k in ("block_id", "block_sha256", "start", "end")) for x in after}
    result = []
    seen = set()
    for proposal in proposals:
        ref = ContentSpanRef.model_validate(proposal).model_dump()
        key = tuple(ref[k] for k in ("block_id", "block_sha256", "start", "end"))
        if key not in allowed or key not in current:
            raise ValueError("model reference outside reviewed permission intersection")
        if key not in seen:
            result.append(allowed[key])
            seen.add(key)
    return result
