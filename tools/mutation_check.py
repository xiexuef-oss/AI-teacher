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
