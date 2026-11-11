"""API 测试夹具：每个测试一个独立的 SQLite 文件、一个可拨动的时钟、显式开启的本地身份 Mock。

样题种子只在整个测试会话里真正写入一次（生成模板库），每个测试拿到的是模板的一份拷贝；
应用启动时发现题库非空就不再重复写入。
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from support.api import LOOPBACK, ApiClient
from support.clock import FakeClock


def _settings(database: Path, **overrides):
    from tutor_api.settings import Settings

    values = {
        "env": "local",
        "database_url": f"sqlite:///{database.as_posix()}",
        "local_identity_mock": True,
        "seed_sample_content": True,
        "pseudonym_secret": "test-only-secret",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory) -> Path:
    """走一遍真实的应用启动流程，得到一份已写入样题的模板库。"""
    from tutor_api.main import create_app

    path = tmp_path_factory.mktemp("template") / "seeded.sqlite3"
    app = create_app(_settings(path), clock=FakeClock().now)
    with TestClient(app, client=LOOPBACK):
        pass
    assert not path.with_name(path.name + "-wal").exists(), "模板库应已完成 checkpoint"
    return path


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(tmp_path, seeded_template):
    database = tmp_path / "tutor.sqlite3"
    shutil.copyfile(seeded_template, database)
    return _settings(database)


@pytest.fixture
def app(settings, clock):
    from tutor_api.main import create_app

    return create_app(settings, clock=clock.now)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app, client=LOOPBACK) as test_client:
        yield test_client


@pytest.fixture
def anon(client) -> ApiClient:
    return ApiClient(client)


@pytest.fixture
def new_student(client) -> Callable[[], ApiClient]:
    """每次调用创建一个新的本地学生身份。"""

    def create() -> ApiClient:
        identity = ApiClient(client).data(
            "POST", "/dev/local-identities", expect=201, auth=False, key=False
        )
        return ApiClient(client, token=identity["access_token"], user_id=identity["user_id"])

    return create


@pytest.fixture
def student(new_student) -> ApiClient:
    return new_student()


@pytest.fixture
def onboarded(student) -> ApiClient:
    """已完成引导的四川高三学生，三科全选。考试年份按夹具时钟估算为 2027。"""
    student.data(
        "PUT",
        "/profile",
        json={"region_code": "CN-51", "grade": "G12", "subjects": ["math", "physics", "chemistry"]},
    )
    return student


@pytest.fixture
def db(app, client):
    """直接访问测试库的会话，用于准备数据或核对落库结果。"""
    with app.state.session_factory() as session:
        yield session


@pytest.fixture
def custom_student(settings, clock) -> Iterator[Callable[..., tuple[object, ApiClient]]]:
    """用自定义参数另起一个应用（例如替换模型网关的适配器），返回 (应用, 已完成引导的四川高三学生)。"""
    from contextlib import ExitStack

    from tutor_api.main import create_app

    with ExitStack() as stack:

        def factory(**kwargs) -> tuple[object, ApiClient]:
            custom_app = create_app(kwargs.pop("settings", settings), clock=clock.now, **kwargs)
            raw = stack.enter_context(TestClient(custom_app, client=LOOPBACK))
            identity = ApiClient(raw).data(
                "POST", "/dev/local-identities", expect=201, auth=False, key=False
            )
            learner = ApiClient(raw, token=identity["access_token"], user_id=identity["user_id"])
            learner.data(
                "PUT",
                "/profile",
                json={
                    "region_code": "CN-51",
                    "grade": "G12",
                    "subjects": ["math", "physics", "chemistry"],
                },
            )
            return custom_app, learner

        yield factory
