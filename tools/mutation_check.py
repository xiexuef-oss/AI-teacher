"""变异检查：故意把关键的安全与教学规则改坏，确认测试会失败。

用途：有些测试是在实现写完之后才第一次运行的，没有亲眼见过它们失败。这里逐条把实现改坏
（去掉归属校验、放开泄题门控、把"判不出来"改成直接判错……），每改一处就跑对应的测试，
测试必须变红；如果某处改坏了测试仍然全绿，说明那条规则没有被测试守住。

    uv run python tools/mutation_check.py                # 全部，约 5 分钟
    uv run python tools/mutation_check.py --only 归属     # 只跑名称里带"归属"的几条

脚本会临时改动源码并在结束时（包括中途出错时）恢复原样。运行期间不要同时跑别的测试，也不要启动服务。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API = REPO_ROOT / "services" / "api" / "tutor_api"
GATEWAY = REPO_ROOT / "services" / "ai_gateway" / "ai_gateway"


@dataclass(frozen=True)
class Mutation:
    name: str
    path: Path
    original: str
    mutated: str
    tests: tuple[str, ...]


MUTATIONS = [
    Mutation(
        "会话不再校验归属",
        API / "services" / "session_service.py",
        "    if session is None or session.student_id != student_id:\n        raise not_found()\n    return session",
        "    if session is None:\n        raise not_found()\n    return session",
        ("tests/api/test_security.py",),
    ),
    Mutation(
        "作答不再校验归属",
        API / "services" / "session_service.py",
        "    if attempt is None or session is None or session.student_id != student_id:\n        raise not_found()\n    return attempt, session",
        "    if attempt is None or session is None:\n        raise not_found()\n    return attempt, session",
        ("tests/api/test_security.py",),
    ),
    Mutation(
        "复测项不再校验归属",
        API / "services" / "review_scheduler.py",
        "    if item is None or item.student_id != student_id:",
        "    if item is None:",
        ("tests/api/test_security.py", "tests/api/test_reviews.py"),
    ),
    Mutation(
        "未发布的题也能取到",
        API / "services" / "question_service.py",
        '    if question is None or question.status != "published":',
        "    if question is None:",
        ("tests/api/test_questions.py", "tests/api/test_attempt_flow.py"),
    ),
    Mutation(
        "地区标签不再检查考试年份",
        API / "services" / "question_service.py",
        "    return lower_ok and upper_ok",
        "    return True",
        ("tests/api/test_questions.py",),
    ),
    Mutation(
        "未审核的地区标签也参与推荐",
        API / "services" / "question_service.py",
        '            QuestionRegionApplicability.review_status == "approved",',
        "",
        ("tests/api/test_questions.py",),
    ),
    Mutation(
        "提交前看解析不再需要确认",
        API / "services" / "orchestrator.py",
        "    if not turn.body.confirm_end_independent:",
        "    if False:",
        ("tests/api/test_tutor_flow.py",),
    ),
    Mutation(
        "复测会话提交前也给辅助",
        API / "services" / "orchestrator.py",
        '    if turn.session.origin == "review" and turn.submitted == 0:',
        "    if False:",
        ("tests/api/test_tutor_flow.py",),
    ),
    Mutation(
        "没懂之后无限重复生成",
        API / "services" / "orchestrator.py",
        "    if session.needs_human_help:\n        return []",
        "    if False:\n        return []",
        ("tests/api/test_tutor_flow.py",),
    ),
    Mutation(
        "看过提示仍算独立作答",
        API / "services" / "session_service.py",
        "        attempt.attempt_no == 1\n        and not session.assisted",
        "        attempt.attempt_no == 1\n        and True",
        ("tests/api/test_tutor_flow.py",),
    ),
    Mutation(
        "同一会话的重试也算独立作答",
        API / "services" / "session_service.py",
        "        attempt.attempt_no == 1\n        and not session.assisted",
        "        True\n        and not session.assisted",
        ("tests/api/test_attempt_flow.py",),
    ),
    Mutation(
        "认不出的单位直接按数值判对错",
        API / "services" / "grading.py",
        '    if unit_status == "unknown":',
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_attempt_flow.py"),
    ),
    Mutation(
        "判不出来的作答也安排复测",
        API / "services" / "session_service.py",
        '    needs_review = result.state == "verified" and (not result.is_correct or not independent)',
        "    needs_review = not result.is_correct or not independent",
        ("tests/api/test_attempt_flow.py",),
    ),
    Mutation(
        "判不出来的作答进了正确率分母",
        API / "services" / "progress_service.py",
        '        if attempt.evaluation_state == "verified"\n    ]',
        "        if True\n    ]",
        ("tests/api/test_progress.py",),
    ),
    Mutation(
        "幂等键不再去重",
        API / "idempotency.py",
        "    if existing is not None:\n        return _replay(existing, fingerprint)",
        "    if False:\n        return _replay(existing, fingerprint)",
        ("tests/api/test_idempotency.py", "tests/api/test_attempt_flow.py"),
    ),
    Mutation(
        "草稿版本冲突时静默覆盖",
        API / "services" / "session_service.py",
        "    if body.base_revision != draft.revision:",
        "    if False:",
        ("tests/api/test_attempt_flow.py",),
    ),
    Mutation(
        "复测结果不看是否独立",
        API / "services" / "review_scheduler.py",
        "    passed = bool(first.is_correct) and bool(first.independent)",
        "    passed = True",
        ("tests/api/test_reviews.py",),
    ),
    Mutation(
        "回环限制失效",
        API / "middleware.py",
        '        if self.loopback_only and not is_loopback(scope.get("client")):',
        "        if False:",
        ("tests/api/test_foundation.py",),
    ),
    Mutation(
        "网关不再校验模型输出的结构",
        GATEWAY / "validation.py",
        "        if error is not None:\n            location",
        "        if False:\n            location",
        ("tests/gateway/test_validation.py",),
    ),
    Mutation(
        "网关不再拦截泄题输出",
        GATEWAY / "validation.py",
        "            if any(item in folded for item in forbidden):",
        "            if False:",
        ("tests/gateway/test_validation.py", "tests/api/test_tutor_flow.py"),
    ),
    Mutation(
        "未过合规核验的外部供应商也可用",
        GATEWAY / "gateway.py",
        '            if not provider.compliance_approved:\n                return None, "not_compliance_approved"',
        '            if False:\n                return None, "not_compliance_approved"',
        ("tests/gateway/test_routing.py",),
    ),
    # ---- 内容审核（P0 第 9 条）
    Mutation(
        "学生也能调用审核接口",
        API / "deps.py",
        "    if principal.role not in REVIEW_ROLES:\n        raise ApiError(403",
        "    if False:\n        raise ApiError(403",
        ("tests/api/test_admin_review.py", "tests/api/test_security.py"),
    ),
    Mutation(
        "提交者可以审核自己的题",
        API / "services" / "review_service.py",
        "        and question.created_by == actor_id\n",
        "        and False\n",
        ("tests/api/test_admin_review.py",),
    ),
    Mutation(
        "草稿不经二审也能直接上线",
        API / "services" / "review_service.py",
        '    "publish": (frozenset({"reviewed"}), "published"),',
        '    "publish": (frozenset({"draft", "reviewed"}), "published"),',
        ("tests/api/test_admin_review.py",),
    ),
    Mutation(
        "程序校验有问题也能通过审核",
        API / "services" / "review_service.py",
        "        problems = check_problems(db, question)\n        if problems:\n",
        "        problems = check_problems(db, question)\n        if False:\n",
        ("tests/api/test_admin_review.py",),
    ),
    Mutation(
        "标准解法没审核也能上线",
        API / "services" / "review_service.py",
        "        if standard is None or not standard.reviewed:\n",
        "        if standard is None:\n",
        ("tests/api/test_admin_review.py",),
    ),
    # ---- 修改题目、产生新版本
    Mutation(
        "已上线的题也能直接修改",
        API / "services" / "review_service.py",
        'EDITABLE_FROM = frozenset({"draft", "reviewed", "withdrawn"})',
        'EDITABLE_FROM = frozenset({"draft", "reviewed", "withdrawn", "published"})',
        ("tests/api/test_admin_versions.py",),
    ),
    Mutation(
        "修改之后解法的审核标记还留着",
        API / "services" / "review_service.py",
        "                reviewed=False,  # 新版本的解法一律重新审核\n",
        "                reviewed=True,\n",
        ("tests/api/test_admin_versions.py",),
    ),
    Mutation(
        "改的人可以自己二审自己的修改",
        API / "services" / "review_service.py",
        "    question.created_by = actor_id  # 改的人成为新版本的提交者，不能自己二审\n",
        "    pass\n",
        ("tests/api/test_admin_versions.py",),
    ),
    Mutation(
        "没有任何改动也产生新版本",
        API / "services" / "review_service.py",
        "    if not changes:\n",
        "    if False:\n",
        ("tests/api/test_admin_versions.py",),
    ),
    Mutation(
        "复测列表里还列着已下线的题",
        API / "services" / "review_scheduler.py",
        '            Question.status == "published",\n',
        "",
        ("tests/api/test_admin_versions.py",),
    ),
    # ---- 回看与对比旧版本
    Mutation(
        "修改时没有把旧版本的难度、年级、知识点记下来",
        API / "services" / "review_service.py",
        "    previous.content_json = {**snapshot_keys, **previous.content_json}\n",
        "    pass\n",
        ("tests/api/test_admin_version_snapshots.py",),
    ),
    Mutation(
        "取某一版时总是返回当前版本",
        API / "services" / "review_service.py",
        "            QuestionVersion.question_id == question.id, QuestionVersion.version == version_no\n",
        "            QuestionVersion.question_id == question.id, QuestionVersion.version == question.version\n",
        ("tests/api/test_admin_version_snapshots.py",),
    ),
    # ---- 解答题（主观题）：不自动评分、提交后对照要点自查
    Mutation(
        "解答题被系统判成了正确",
        API / "services" / "grading.py",
        '    return GradeResult(\n        "pending",\n        "undetermined",\n        None,\n        (),\n        "解答题不自动评分，作答已保存。',
        '    return GradeResult(\n        "verified",\n        "correct",\n        True,\n        (),\n        "解答题不自动评分，作答已保存。',
        ("tests/unit/test_grading.py", "tests/api/test_subjective.py"),
    ),
    Mutation(
        "解答题什么都没写也能提交",
        API / "services" / "grading.py",
        '    if not any(part["text"].strip() for part in submitted) and not has_ink:',
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_subjective.py"),
    ),
    Mutation(
        "解答题提交时不看草稿里的笔迹",
        API / "services" / "session_service.py",
        "            has_ink=_has_ink(get_draft(db, attempt.id)),",
        "            has_ink=False,",
        ("tests/api/test_subjective.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "只有空白页也算写过笔迹",
        API / "services" / "session_service.py",
        '    return any(page.get("strokes") for page in pages)',
        "    return bool(pages)",
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "选择题接受解答题的分小问作答",
        API / "services" / "grading.py",
        '        or answer.get("text") is not None\n        or answer.get("parts") is not None\n        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        '        or answer.get("text") is not None\n        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        ("tests/unit/test_grading.py", "tests/api/test_subjective.py"),
    ),
    Mutation(
        "提交之前就能拿到自查要点",
        API / "services" / "self_check_service.py",
        '    if attempt.status != "submitted":\n        raise conflict("attempt_not_submitted", "提交之后才能对照要点自查")',
        '    if False:\n        raise conflict("attempt_not_submitted", "提交之后才能对照要点自查")',
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查要点取的是题目当前版本而不是学生做题时的版本",
        API / "services" / "self_check_service.py",
        "    rubric = question_service.get_rubric(db, question.id, session.question_version)",
        "    rubric = question_service.get_rubric(db, question.id, question.version)",
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查接口不再校验作答归属",
        API / "services" / "session_service.py",
        "    if attempt is None or session is None or session.student_id != student_id:\n        raise not_found()\n    return attempt, session",
        "    if attempt is None or session is None:\n        raise not_found()\n    return attempt, session",
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查可以漏评要点",
        API / "services" / "self_check_service.py",
        '    if set(keys) - set(given):\n        raise unprocessable("marks", "每个要点都要评一次，还有要点没有评")',
        '    if False:\n        raise unprocessable("marks", "每个要点都要评一次，还有要点没有评")',
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查可以把同一个要点评两次",
        API / "services" / "self_check_service.py",
        '    if len(set(given)) != len(given):\n        raise unprocessable("marks", "同一个要点只能评一次")',
        '    if False:\n        raise unprocessable("marks", "同一个要点只能评一次")',
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查可以评不存在的要点",
        API / "services" / "self_check_service.py",
        '    if not set(given) <= set(keys):\n        raise unprocessable("marks", "包含不存在的要点")',
        '    if False:\n        raise unprocessable("marks", "包含不存在的要点")',
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "解答题和实验题被算进了没能判定的次数",
        API / "services" / "progress_service.py",
        '        if mode not in grading.SUBJECTIVE_MODES and attempt.evaluation_state != "verified"',
        '        if attempt.evaluation_state != "verified"',
        ("tests/api/test_subjective.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "第一道新题可能就是解答题或实验题",
        API / "services" / "task_planner.py",
        "    return [q for q in questions if q.answer_mode not in grading.SUBJECTIVE_MODES] + [\n        q for q in questions if q.answer_mode in grading.SUBJECTIVE_MODES\n    ]",
        "    return questions",
        (
            "tests/api/test_subjective.py",
            "tests/api/test_experiment.py",
            "tests/api/test_tasks.py",
        ),
    ),
    Mutation(
        "自查要点带分值也能通过校验",
        API / "services" / "content_seed.py",
        "        if not isinstance(point, dict) or set(point) != _POINT_FIELDS:",
        "        if not isinstance(point, dict):",
        ("tests/content/test_seed_content.py", "tests/api/test_admin_written.py"),
    ),
    Mutation(
        "解答题有小问没有自查要点也能通过校验",
        API / "services" / "content_seed.py",
        '    problems += [\n        f"{key}: rubric.points 没有覆盖{where_name} {part}"\n        for part in required_parts\n        if part not in covered\n    ]',
        "    problems += []",
        (
            "tests/content/test_seed_content.py",
            "tests/api/test_admin_written.py",
            "tests/content/test_experiment_content.py",
        ),
    ),
    Mutation(
        "解答题可以没有泄题标记",
        API / "services" / "content_seed.py",
        '        or not markers\n        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)\n    ):\n        problems.append(\n            f"{key}: teaching.leak_markers 不能为空（解答题',
        '        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)\n    ):\n        problems.append(\n            f"{key}: teaching.leak_markers 不能为空（解答题',
        ("tests/content/test_seed_content.py",),
    ),
    # ---- 实验题：数据表 + 安全提示；不自动评分，提交后对照参考数据和要点自查
    Mutation(
        "实验题被系统判成了正确",
        API / "services" / "grading.py",
        '    return GradeResult(\n        "pending",\n        "undetermined",\n        None,\n        (),\n        "实验题不自动评分，作答已保存。',
        '    return GradeResult(\n        "verified",\n        "correct",\n        True,\n        (),\n        "实验题不自动评分，作答已保存。',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题什么都没填也能提交",
        API / "services" / "grading.py",
        "    if not filled and not written and not has_ink:",
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题可以填题目已经给定的格子",
        API / "services" / "grading.py",
        "    if not set(seen) <= set(blank_cell_keys(content)):",
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题同一个格子可以填两次",
        API / "services" / "grading.py",
        '    if len(set(seen)) != len(seen):\n        raise AnswerShapeError("answer.cells", "同一个格子只能填一次")',
        '    if False:\n        raise AnswerShapeError("answer.cells", "同一个格子只能填一次")',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题把题目没有留空的格子也当成要学生填的",
        API / "services" / "grading.py",
        '        for cell in row["cells"]\n        if cell["text"] is None\n    ]',
        '        for cell in row["cells"]\n    ]',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题接受填空题的作答形状",
        API / "services" / "grading.py",
        '        or answer.get("blanks") is not None\n        or answer.get("text") is not None\n    ):\n        raise AnswerShapeError("answer", "实验题只需要提交 cells',
        '        or answer.get("text") is not None\n    ):\n        raise AnswerShapeError("answer", "实验题只需要提交 cells',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "选择题接受实验题的格子作答",
        API / "services" / "grading.py",
        '        or answer.get("parts") is not None\n        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        '        or answer.get("parts") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "解答题接受实验题的格子作答",
        API / "services" / "grading.py",
        '        or answer.get("text") is not None\n        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "解答题只需要按小问提交 parts")',
        '        or answer.get("text") is not None\n    ):\n        raise AnswerShapeError("answer", "解答题只需要按小问提交 parts")',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "客观题也能对照要点自查",
        API / "services" / "self_check_service.py",
        '    if question.answer_mode not in grading.SUBJECTIVE_MODES:\n        raise conflict("self_check_not_applicable", "这道题不需要对照要点自查")',
        '    if False:\n        raise conflict("self_check_not_applicable", "这道题不需要对照要点自查")',
        ("tests/api/test_subjective.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "参考数据取的是题目当前版本而不是学生做题时的版本",
        API / "services" / "self_check_service.py",
        "    version = question_service.get_version(db, question.id, session.question_version)",
        "    version = question_service.get_version(db, question.id, question.version)",
        ("tests/api/test_admin_experiment.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "数值型的参考数据没有自动加进泄题标记",
        API / "services" / "content_seed.py",
        '            if cell_key.count(".") == 2 and len(text) >= 3 and _NUMBER_LIKE.match(text):\n                markers.append(text)',
        "            if False:\n                markers.append(text)",
        ("tests/content/test_experiment_content.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "高风险实验也能通过校验",
        API / "services" / "content_seed.py",
        '    if level == "high":\n        problems.append(\n            f"{key}: content.safety.level 是 high：高风险实验现在不收录，还没有专项审核流程"\n        )\n    elif level not in _SAFETY_LEVELS:\n',
        '    if level not in (*_SAFETY_LEVELS, "high"):\n',
        (
            "tests/content/test_experiment_content.py",
            "tests/api/test_admin_experiment.py",
        ),
    ),
    Mutation(
        "实验题可以没有安全提示",
        API / "services" / "content_seed.py",
        '    if not isinstance(safety, dict) or set(safety) != {"level", "notes"}:\n        return [\n',
        '    if not isinstance(safety, dict):\n        return []\n    if set(safety) != {"level", "notes"}:\n        return [\n',
        (
            "tests/content/test_experiment_content.py",
            "tests/api/test_admin_experiment.py",
        ),
    ),
    Mutation(
        "实验题有留空格子的数据表没有自查要点也能通过校验",
        API / "services" / "content_seed.py",
        '        key, question, [*part_keys, *table_keys], [*part_keys, *tables_with_blanks], "小问或数据表"',
        '        key, question, [*part_keys, *table_keys], part_keys, "小问或数据表"',
        (
            "tests/content/test_experiment_content.py",
            "tests/api/test_admin_experiment.py",
        ),
    ),
    Mutation(
        "实验题的留空格子没有参考值也能通过校验",
        API / "services" / "content_seed.py",
        "        or set(values) != set(expected)\n",
        "",
        (
            "tests/content/test_experiment_content.py",
            "tests/api/test_admin_experiment.py",
        ),
    ),
    Mutation(
        "选择题、填空题、解答题也能带数据表和安全提示",
        API / "services" / "content_seed.py",
        '    if content.get("data_tables") or content.get("safety"):\n        return [f"{key}: 只有实验题才能有 content.data_tables 和 content.safety"]',
        '    if False:\n        return [f"{key}: 只有实验题才能有 content.data_tables 和 content.safety"]',
        ("tests/content/test_experiment_content.py",),
    ),
    Mutation(
        "修改实验题之后新版本丢了数据表",
        API / "services" / "review_service.py",
        '                "data_tables": [item.model_dump() for item in content.data_tables],',
        '                "data_tables": [],',
        ("tests/api/test_admin_experiment.py",),
    ),
    Mutation(
        "修改实验题之后新版本丢了安全提示",
        API / "services" / "review_service.py",
        '                "safety": content.safety.model_dump() if content.safety else None,',
        '                "safety": None,',
        ("tests/api/test_admin_experiment.py",),
    ),
    Mutation(
        "审核后台看到的当前版本没有数据表",
        API / "services" / "review_service.py",
        '            "data_tables": content.get("data_tables") or [],\n            "safety": content.get("safety"),\n        },\n        "answer": {',
        '            "data_tables": [],\n            "safety": content.get("safety"),\n        },\n        "answer": {',
        ("tests/api/test_admin_experiment.py",),
    ),
    Mutation(
        "题面里没有安全提示",
        API / "services" / "question_service.py",
        '        safety=content.get("safety"),',
        "        safety=None,",
        ("tests/api/test_experiment.py",),
    ),
    Mutation(
        "题面里没有数据表",
        API / "services" / "question_service.py",
        '        data_tables=content.get("data_tables") or [],',
        "        data_tables=[],",
        ("tests/api/test_experiment.py",),
    ),
    Mutation(
        "实验题的预计用时和解答题一样",
        API / "services" / "task_planner.py",
        "        return 10 + 2 * question.difficulty",
        "        return 8 + 2 * question.difficulty",
        ("tests/api/test_experiment.py",),
    ),
    Mutation(
        "学情页不统计实验题的提交",
        API / "services" / "progress_service.py",
        "    written = [attempt for attempt, _, _, mode, _ in records if mode in grading.SUBJECTIVE_MODES]",
        '    written = [attempt for attempt, _, _, mode, _ in records if mode == "written"]',
        ("tests/api/test_experiment.py",),
    ),
    Mutation(
        "家长周报不统计实验题的提交",
        API / "services" / "weekly_service.py",
        "        written_attempts=sum(1 for _, _, _, mode, _ in records if mode in grading.SUBJECTIVE_MODES),",
        '        written_attempts=sum(1 for _, _, _, mode, _ in records if mode == "written"),',
        ("tests/api/test_experiment.py",),
    ),
    # ---- 家长周报：学生明确授权、可撤销；家长只看汇总
    Mutation(
        "家长不检查角色就能进家长接口",
        API / "deps.py",
        '    if principal.role != "parent":\n        raise ApiError(403, "forbidden", "当前角色无权访问")',
        '    if False:\n        raise ApiError(403, "forbidden", "当前角色无权访问")',
        ("tests/api/test_parent_consent.py", "tests/api/test_security.py"),
    ),
    Mutation(
        "授权撤销之后家长仍然能看周报",
        API / "services" / "parent_service.py",
        '            ParentStudentLink.student_id == student_id,\n            ParentStudentLink.revoked_at.is_(None),\n            User.status == "active",\n        )\n    ).first()',
        '            ParentStudentLink.student_id == student_id,\n            User.status == "active",\n        )\n    ).first()',
        ("tests/api/test_parent_consent.py", "tests/api/test_parent_weekly.py"),
    ),
    Mutation(
        "家长能看别的家长绑定的学生",
        API / "services" / "parent_service.py",
        "            ParentStudentLink.parent_id == parent_id,\n            ParentStudentLink.student_id == student_id,",
        "            ParentStudentLink.student_id == student_id,",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "家长的学生列表里还有已经撤销授权的",
        API / "services" / "parent_service.py",
        "            ParentStudentLink.parent_id == parent_id,\n            ParentStudentLink.revoked_at.is_(None),\n",
        "            ParentStudentLink.parent_id == parent_id,\n",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "学生的授权列表里还有已经撤销的",
        API / "services" / "parent_service.py",
        ".where(ParentStudentLink.student_id == student_id, ParentStudentLink.revoked_at.is_(None))",
        ".where(ParentStudentLink.student_id == student_id)",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "别的学生也能撤销这个授权",
        API / "services" / "parent_service.py",
        "    if link is None or link.student_id != student_id or link.revoked_at is not None:",
        "    if link is None or link.revoked_at is not None:",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "邀请码可以重复使用",
        API / "services" / "parent_service.py",
        "        or invite.redeemed_at is not None\n",
        "",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "过期的邀请码仍然能用",
        API / "services" / "parent_service.py",
        "        or invite.expires_at <= now",
        "        or False",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "新的邀请码不作废学生之前没用掉的",
        API / "services" / "parent_service.py",
        "        old.revoked_at = now  # 再生成一个，旧的立刻作废",
        "        pass",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "邀请码明文落了库",
        API / "services" / "parent_service.py",
        "        code_hash=_hash(code),",
        "        code_hash=code,",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "授权时间记成了家长输入的时间",
        API / "services" / "parent_service.py",
        "            consent_at=invite.created_at,",
        "            consent_at=now,",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "已经绑定着还能再兑换一次",
        API / "services" / "parent_service.py",
        '        raise conflict("already_linked", "已经绑定着这位学生了")',
        "        pass",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "没授权的家长也能问日期合不合法",
        API / "services" / "weekly_service.py",
        "    _, student = parent_service.require_link(db, parent_id, student_id)\n    start_date, start, end, offset = _window(settings, week_start, now)",
        "    start_date, start, end, offset = _window(settings, week_start, now)\n    _, student = parent_service.require_link(db, parent_id, student_id)",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "一周的末尾把下周一零点也算进来",
        API / "services" / "progress_service.py",
        "        query = query.where(Attempt.submitted_at < until)",
        "        query = query.where(Attempt.submitted_at <= until)",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "周按 UTC 划分而不是配置的时区",
        API / "services" / "weekly_service.py",
        "    offset = timezone(timedelta(minutes=settings.report_utc_offset_minutes))",
        "    offset = UTC",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "趋势的临界值不算变了",
        API / "services" / "weekly_service.py",
        "    if delta >= TREND_THRESHOLD:",
        "    if delta > TREND_THRESHOLD:",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "有一周样本不足也硬比趋势",
        API / "services" / "weekly_service.py",
        '    if previous is None or current is None:\n        return "unknown"',
        "    if previous is None:\n        previous = 0.0\n    if current is None:\n        current = 0.0",
        ("tests/api/test_parent_weekly.py",),
    ),
]


def _run(tests: tuple[str, ...]) -> bool:
    """返回测试是否通过。"""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="变异检查")
    parser.add_argument("--only", help="只跑名称里包含这段文字的变异，例如 --only 归属")
    args = parser.parse_args()
    selected = [m for m in MUTATIONS if not args.only or args.only in m.name]
    if not selected:
        print(f"没有名称包含 {args.only!r} 的变异")
        return 1

    survived: list[str] = []
    broken: list[str] = []
    for mutation in selected:
        source = mutation.path.read_text(encoding="utf-8")
        if source.count(mutation.original) != 1:
            broken.append(mutation.name)
            print(f"[跳过] {mutation.name}：源码里找不到唯一的匹配片段，变异定义需要更新")
            continue
        try:
            mutation.path.write_text(
                source.replace(mutation.original, mutation.mutated), encoding="utf-8"
            )
            passed = _run(mutation.tests)
        finally:
            mutation.path.write_text(source, encoding="utf-8")
        if passed:
            survived.append(mutation.name)
            print(f"[漏网] {mutation.name}：实现被改坏后测试仍然全绿")
        else:
            print(f"[抓到] {mutation.name}")

    total = len(selected)
    print(f"\n{total - len(survived) - len(broken)}/{total} 处变异被测试抓到")
    return 1 if survived or broken else 0


if __name__ == "__main__":
    sys.exit(main())
