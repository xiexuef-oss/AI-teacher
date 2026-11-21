"""Run the V1.4 paper and weekly snapshot worker separately from the API."""

import argparse
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from sqlalchemy.engine import make_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one paper task and exit")
    parser.add_argument("--namespace", required=True, help="Redis key prefix for this deployment")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for package in ("services/api", "services/ai_gateway"):
        sys.path.insert(0, str(root / package))
    from tutor_api.db import create_session_factory, make_engine
    from tutor_api.services.learning_pack_outbox import RedisPaperQueue
    from tutor_api.services.learning_pack_worker import LearningPackWorker
    from tutor_api.settings import Settings

    settings = Settings()
    redis_url = os.environ.get("TUTOR_LEARNING_PACK_REDIS_URL")
    if (
        settings.env not in {"dev", "staging"}
        or make_url(settings.database_url).drivername != "mysql+pymysql"
    ):
        parser.error("The worker requires dev/staging and an explicitly configured MySQL database")
    if not redis_url:
        parser.error("TUTOR_LEARNING_PACK_REDIS_URL is required")

    from redis import Redis

    logging.basicConfig(level=logging.INFO)
    engine = make_engine(settings.database_url, settings=settings)
    try:
        with Redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3) as redis:
            queue = RedisPaperQueue(redis, namespace=args.namespace)
            worker = LearningPackWorker(
                create_session_factory(engine),
                lambda: datetime.now(UTC),
                settings,
                sample_font=settings.learning_pack_sample_font,
                queue=queue,
            )
            if args.once:
                worker.process_paper_once()
                return
            stopped = Event()
            signal.signal(signal.SIGTERM, lambda *_: stopped.set())
            worker.start()
            try:
                stopped.wait()
            except KeyboardInterrupt:
                pass
            finally:
                worker.close()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
