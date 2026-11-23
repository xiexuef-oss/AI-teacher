"""Run the independent Content Factory analysis queue."""

import argparse
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import monotonic

from sqlalchemy.engine import make_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one available job and exit")
    parser.add_argument(
        "--mock-ocr", action="store_true", help="Exercise OCR without external calls"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for package in ("services/api", "services/ai_gateway"):
        sys.path.insert(0, str(root / package))
    from tutor_api.db import create_session_factory, make_engine
    from tutor_api.services.content_factory_jobs import process_one
    from tutor_api.services.content_factory_originals import purge_expired
    from tutor_api.settings import Settings

    settings = Settings()
    if (
        settings.env not in {"dev", "staging"}
        or make_url(settings.database_url).drivername != "mysql+pymysql"
    ):
        parser.error("The worker requires dev/staging and an explicitly configured MySQL database")
    if args.mock_ocr and settings.env != "dev":
        parser.error("Mock OCR is available in dev only")
    engine = make_engine(settings.database_url, settings=settings)
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    try:
        factory = create_session_factory(engine)
        mock_gateway = None
        if args.mock_ocr:
            from ai_gateway import build_gateway
            from tutor_api.gateway_io import DbAuditSink, DbBudgetStore
            from tutor_api.settings import EVENT_SCHEMA_PATH, VISUAL_REGISTRY_PATH

            mock_gateway = build_gateway(
                settings.model_routes_path,
                env={},
                environment=settings.env,
                allow_external_calls=False,
                event_schema_path=EVENT_SCHEMA_PATH,
                visual_registry_path=VISUAL_REGISTRY_PATH,
                audit=DbAuditSink(factory),
                budget_store=DbBudgetStore(
                    factory, lambda: datetime.now(UTC), namespace="content_factory"
                ),
            )
        next_purge = 0.0
        while not stopped.is_set():
            if monotonic() >= next_purge:
                with factory.begin() as db:
                    purge_expired(db, datetime.now(UTC))
                next_purge = monotonic() + 60
            processed = process_one(
                factory, lambda: datetime.now(UTC), settings, mock_gateway=mock_gateway
            )
            if args.once:
                return
            if not processed:
                stopped.wait(1)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
