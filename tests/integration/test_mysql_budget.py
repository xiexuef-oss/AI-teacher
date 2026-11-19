"""显式开启的真实MySQL回归；仅写入专用本机测试库的独立scope。"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import URL, create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from tutor_api.gateway_io import DbBudgetStore
from tutor_api.models import ModelBudgetUsage


def test_mysql_atomic_budget_creation_and_increment():
    config_path = os.environ.get("TUTOR_MYSQL_TEST_CONFIG")
    if not config_path:
        pytest.skip("需要显式配置独立MySQL测试库")
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if (
        config.get("allow_test_writes") is not True
        or config.get("host") != "127.0.0.1"
        or not config.get("database", "").startswith("tutor_migration_")
    ):
        pytest.fail("仅允许显式授权的本机独立迁移测试库")
    engine = create_engine(
        URL.create(
            "mysql+pymysql",
            username=config["user"],
            password=config["password"],
            host=config["host"],
            port=config["port"],
            database=config["database"],
        ),
        hide_parameters=True,
    )
    factory = sessionmaker(engine)
    def now():
        return datetime.now(UTC)
    store, key = DbBudgetStore(factory, now), "regression-" + uuid4().hex
    day = now().date()
    try:
        for _ in range(2):
            barrier = Barrier(8)

            def increment(_, barrier=barrier):
                barrier.wait(timeout=10)
                store.add("student", key, day, requests=1, cost_micros=3)

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(increment, range(8)))
        with factory() as db:
            rows = list(
                db.scalars(select(ModelBudgetUsage).where(ModelBudgetUsage.scope_key == key))
            )
            assert len(rows) == 1
            assert rows[0].request_count == 16
            assert rows[0].estimated_cost_micros == 48
    finally:
        with factory() as db:
            db.execute(delete(ModelBudgetUsage).where(ModelBudgetUsage.scope_key == key))
            db.commit()
        engine.dispose()
