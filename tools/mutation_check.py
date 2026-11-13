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
        ("tests/api/test_subjective.py",),
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
        '        or answer.get("text") is not None\n        or answer.get("parts") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        '        or answer.get("text") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
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
        "解答题被算进了没能判定的次数",
        API / "services" / "progress_service.py",
        '        if mode != "written" and attempt.evaluation_state != "verified"',
        '        if attempt.evaluation_state != "verified"',
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "第一道新题可能就是解答题",
        API / "services" / "task_planner.py",
        '    return [q for q in questions if q.answer_mode != "written"] + [\n        q for q in questions if q.answer_mode == "written"\n    ]',
        "    return questions",
        ("tests/api/test_subjective.py", "tests/api/test_tasks.py"),
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
        '    problems += [\n        f"{key}: rubric.points 没有覆盖小问 {part}" for part in part_keys if part not in covered\n    ]',
        "    problems += []",
        ("tests/content/test_seed_content.py", "tests/api/test_admin_written.py"),
    ),
    Mutation(
        "解答题可以没有泄题标记",
        API / "services" / "content_seed.py",
        "        or not markers\n",
        "",
        ("tests/content/test_seed_content.py",),
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
