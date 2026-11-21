"""Run V1.4 paper, private material and weekly snapshot tasks outside the API."""

import argparse
import json
import logging
import os
import signal
import sys
from contextlib import ExitStack
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
    from tutor_api.learning_pack_pdf_store import local_pdf_store
    from tutor_api.s3_blob_store import S3BlobStore, local_s3_client
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
        with ExitStack() as resources:
            redis = resources.enter_context(
                Redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
            )
            pdf_store = None
            if settings.learning_pack_pdf_s3_config is not None:
                pdf_store = local_pdf_store(settings.learning_pack_pdf_s3_config)
                resources.callback(pdf_store.client.close)
            media_store = None
            if settings.learning_pack_media_s3_config is not None:
                config = json.loads(
                    settings.learning_pack_media_s3_config.read_text(encoding="utf-8-sig")
                )
                media_client = local_s3_client(
                    **{
                        name: config[name]
                        for name in ("endpoint", "region", "access_key", "secret_key")
                    }
                )
                resources.callback(media_client.close)
                media_store = S3BlobStore(
                    media_client,
                    bucket=config["bucket"],
                    prefix=config["prefix"],
                    max_bytes=settings.media_max_bytes,
                )
            queue = RedisPaperQueue(redis, namespace=args.namespace)
            worker = LearningPackWorker(
                create_session_factory(engine),
                lambda: datetime.now(UTC),
                settings,
                sample_font=settings.learning_pack_sample_font,
                queue=queue,
                pdf_store=pdf_store,
                media_store=media_store,
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
