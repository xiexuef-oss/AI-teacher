"""Inspect durable cost alerts; resume only after reviewing the current attempt ID."""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services/api"), str(ROOT / "services/ai_gateway")]

from ai_gateway.invocation_state import InvocationTransitions  # noqa: E402
from tutor_api.db import create_session_factory, make_engine  # noqa: E402
from tutor_api.services.invocation_maintenance import report_invocations  # noqa: E402
from tutor_api.services.invocation_store import InvocationStore  # noqa: E402
from tutor_api.services.model_cost_gate import REVIEW_REASONS, ModelCostGate  # noqa: E402
from tutor_api.settings import CONTRACTS_DIR, Settings  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--resume-attempt")
    parser.add_argument("--reason", choices=sorted(REVIEW_REASONS))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--invocations", action="store_true", help="只读调用状态清单，不重发或退款")
    parser.add_argument("--after-invocation", help="按调用ID分页，不代表时间顺序")
    args = parser.parse_args(argv)
    review = (args.resume_attempt, args.reason, args.apply)
    if (args.after_invocation and not args.invocations) or (args.invocations and any(review)):
        parser.error("调用清单只读，不能组合恢复参数；游标需要 --invocations。")
    if any(review) and not all(review):
        parser.error("恢复必须同时指定 --resume-attempt、--reason 和 --apply；默认只读。")
    if args.resume_attempt and not re.fullmatch(r"[a-f0-9]{32}", args.resume_attempt):
        parser.error("事件ID必须为32位小写十六进制摘要。")
    if not 1 <= args.limit <= 200:
        parser.error("--limit 必须介于1和200。")
    engine = None
    try:
        settings = Settings()
        if settings.env == "prod":
            raise ValueError("Production cost maintenance is not enabled")
        engine = make_engine(settings.database_url, settings=settings)
        gate = ModelCostGate(create_session_factory(engine), lambda: datetime.now(UTC))
        invocation_report = {}
        if args.invocations:
            store = InvocationStore(
                gate.factory, InvocationTransitions(CONTRACTS_DIR / "model_invocation.schema.json")
            )
            invocation_report["invocations"] = report_invocations(
                store, limit=args.limit, after=args.after_invocation
            )
        if args.apply:
            gate.resume(args.resume_attempt, reason=args.reason)
        print(
            json.dumps(
                dict(resumed=args.apply, **gate.report(limit=args.limit), **invocation_report),
                ensure_ascii=False,
            )
        )
        return 0
    except Exception:
        parser.error("成本检查未完成；请核对环境、迁移和当前事件。未输出敏感连接信息。")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
