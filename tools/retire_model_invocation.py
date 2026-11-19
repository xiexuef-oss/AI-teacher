"""Preview one terminal account/session's intent; --apply retires metadata only."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services/api"), str(ROOT / "services/ai_gateway")]

from ai_gateway.invocation_state import InvocationTransitions  # noqa: E402
from tutor_api.db import create_session_factory, make_engine  # noqa: E402
from tutor_api.services.invocation_maintenance import retire_terminal_session  # noqa: E402
from tutor_api.services.invocation_store import InvocationStore  # noqa: E402
from tutor_api.settings import CONTRACTS_DIR, Settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student-id", type=UUID, required=True)
    parser.add_argument("--session-id", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = None
    try:
        settings = Settings()
        if settings.env == "prod" or not settings.pseudonym_secret:
            raise ValueError("Unsupported maintenance configuration")
        engine = make_engine(settings.database_url, settings=settings)
        store = InvocationStore(
            create_session_factory(engine),
            InvocationTransitions(CONTRACTS_DIR / "model_invocation.schema.json"),
        )
        count = retire_terminal_session(
            store,
            str(args.student_id),
            str(args.session_id),
            secret=settings.pseudonym_secret,
            apply=args.apply,
        )
        print(json.dumps(dict(eligible=count, applied=count if args.apply else 0)))
        return 0
    except Exception:
        parser.error("维护未完成；请检查环境、稳定密钥、迁移和目标。未输出敏感连接信息。")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
