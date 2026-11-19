"""Operator reports are bounded, metadata-only and never authorize recovery."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from ai_gateway.invocation_state import InvocationTransitions
from support.cost_cases import record
from tutor_api.services import invocation_maintenance
from tutor_api.services.invocation_store import InvocationStore, intents, metadata


@pytest.fixture
def store():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    result = InvocationStore(
        sessionmaker(engine), InvocationTransitions(Path("contracts/model_invocation.schema.json"))
    )
    for key in ("a", "b", "c"):
        result.prepare(record(key))
    yield result
    engine.dispose()


def test_report_pages_and_preserves_all_stored_bytes(store):
    with store.factory() as db:
        before = deepcopy(list(db.execute(select(intents)).mappings()))
    first = invocation_maintenance.report_invocations(store, limit=2)
    assert [row["invocation_id"] for row in first["items"]] == ["a" * 32, "b" * 32]
    assert first["next_cursor"] == "b" * 32
    assert first["items"][0] == dict(
        invocation_id="a" * 32,
        context_kind="tutor_session",
        state="prepared",
        fence=1,
        quota_day="2026-11-17",
        attempts=[],
    )
    second = invocation_maintenance.report_invocations(store, limit=2, after=first["next_cursor"])
    assert [row["invocation_id"] for row in second["items"]] == ["c" * 32]
    assert second["next_cursor"] is None
    with store.factory() as db:
        assert list(db.execute(select(intents)).mappings()) == before
    text = json.dumps(first)
    for field in ("actor_digest", "budget_key", "session_digest", "fingerprint", "context_digest"):
        assert field not in text


@pytest.mark.parametrize("change", ["unknown_field", "identity", "state", "fence"])
def test_corrupt_records_fail_without_returning_a_partial_report(store, change):
    value = record("b")
    if change == "unknown_field":
        value["prompt"] = "private-unexpected-content"
    elif change == "identity":
        value["invocation_id"] = "d" * 32
    elif change == "state":
        value["state"] = "applied"
    else:
        value["fence"] = 2
    with store.factory.begin() as db:
        db.execute(update(intents).where(intents.c.id == "b" * 32).values(metadata_json=value))
    with pytest.raises(ValueError):
        invocation_maintenance.report_invocations(store)


@pytest.mark.parametrize(
    "options",
    [{"limit": 0}, {"limit": 201}, {"limit": True}, {"after": "private"}, {"after": False}],
)
def test_invalid_report_bounds_are_rejected(store, options):
    with pytest.raises(ValueError):
        invocation_maintenance.report_invocations(store, **options)


def test_cli_invocation_report_reuses_existing_tool_and_cannot_resume(store, monkeypatch, capsys):
    import model_cost_report as cli

    monkeypatch.setattr(
        cli, "Settings", lambda: SimpleNamespace(env="local", database_url="unused")
    )
    monkeypatch.setattr(cli, "make_engine", lambda *args, **kwargs: store.factory.kw["bind"])
    assert cli.main(["--invocations", "--limit", "2"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["invocations"]["items"]) == 2
    assert result["resumed"] is False
    connections = []

    def unexpected_connection(*args, **kwargs):
        connections.append(True)
        raise RuntimeError("Must reject mixed operations before connecting")

    monkeypatch.setattr(cli, "make_engine", unexpected_connection)
    with pytest.raises(SystemExit) as error:
        cli.main(
            [
                "--invocations",
                "--resume-attempt",
                "a" * 32,
                "--reason",
                "pricing_corrected",
                "--apply",
            ]
        )
    assert error.value.code == 2
    assert connections == []


def test_document_unknown_attempt_is_visible_without_resource_identifiers(store):
    value = record("d")
    del value["session_digest"], value["question_version"]
    value.update(
        schema_version=2,
        context_kind="document_ocr",
        resource_digest="e" * 64,
        file_digest="f" * 64,
        page=1,
    )
    store.prepare(value)
    value = store.transitions.dispatch(
        value, expected_fence=1, attempt_id="f" * 32, estimated_cost_micros=23
    )
    value = store.transitions.mark_unknown(value, expected_fence=1)
    with store.factory.begin() as db:
        db.execute(
            update(intents)
            .where(intents.c.id == "d" * 32)
            .values(state=value["state"], metadata_json=value)
        )
    report = invocation_maintenance.report_invocations(store, after="c" * 32)
    assert report["items"] == [
        dict(
            invocation_id="d" * 32,
            context_kind="document_ocr",
            state="outcome_unknown",
            fence=1,
            quota_day="2026-11-17",
            attempts=[dict(attempt_id="f" * 32, state="outcome_unknown", estimated_cost_micros=23)],
        )
    ]
    assert store.read("d" * 32, "b" * 64) == value
    assert "resource_digest" not in json.dumps(report)
    assert "file_digest" not in json.dumps(report)


def test_cli_corrupt_metadata_does_not_leak_a_partial_report(store, monkeypatch, capsys):
    import model_cost_report as cli

    value = record("b")
    value["prompt"] = "unexpected-private-text"
    with store.factory.begin() as db:
        db.execute(update(intents).where(intents.c.id == "b" * 32).values(metadata_json=value))
    monkeypatch.setattr(
        cli, "Settings", lambda: SimpleNamespace(env="local", database_url="private-connection")
    )
    monkeypatch.setattr(cli, "make_engine", lambda *args, **kwargs: store.factory.kw["bind"])
    with pytest.raises(SystemExit) as error:
        cli.main(["--invocations"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert "unexpected-private-text" not in output.err
    assert "private-connection" not in output.err
