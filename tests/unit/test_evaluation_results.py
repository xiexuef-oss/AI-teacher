import json
import subprocess
import sys

import pytest
from summarize_evaluation import summarize


def row(**changes):
    return {
        "request_id": "req-1",
        "item_id": "self-authored-1",
        "task_type": "ocr_extract",
        "answer_mode": "single_choice",
        "provider": "fixture-provider",
        "model": "fixture-model",
        "status": "ok",
        "verdict": "correct",
        "review_required": False,
        "latency_ms": 10,
        "input_tokens": 2,
        "output_tokens": 3,
        "image_units": None,
        "estimated_cost_micros": 5,
        **changes,
    }


def write(tmp_path, rows):
    path = tmp_path / "self-authored.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in rows), encoding="utf-8")
    return path


def test_uncertain_pending_missing_usage_and_latency(tmp_path):
    records = [
        row(),
        row(request_id="req-2", verdict="incorrect", latency_ms=20),
        row(
            request_id="req-3",
            verdict="uncertain",
            status="error",
            latency_ms=100,
            input_tokens=None,
        ),
        row(
            request_id="req-4",
            answer_mode="proof",
            verdict="pending",
            review_required=True,
            latency_ms=30,
        ),
    ]
    report = summarize(write(tmp_path, records))
    assert report["valid"]
    summary = report["overall"]
    assert summary["success_rate"] == 0.75
    assert summary["accuracy"] == 0.5 and summary["decidable_count"] == 2
    assert summary["review_rate"] == 0.25
    assert summary["latency_ms"] == {"average": 40.0, "p95": 100}
    assert summary["input_tokens"] == {"total": None, "known_total": 6, "unknown_count": 1}
    assert summary["estimated_cost_micros"]["total"] == 20


@pytest.mark.parametrize(
    "changes",
    [
        {"latency_ms": -1},
        {"latency_ms": True},
        {"input_tokens": -1},
        {"input_tokens": 2.5},
        {"status": "successful"},
        {"verdict": "maybe"},
        {"task_type": "fake"},
        {"answer_mode": "proof", "verdict": "correct"},
        {"answer_mode": "experiment", "verdict": "incorrect"},
        {"answer_mode": "written", "verdict": "uncertain"},
        {"status": "error", "verdict": "correct"},
        {"review_required": "false"},
        {"student_id": "private"},
        {"text": "private"},
        {"request_id": ""},
    ],
)
def test_reject_invalid_records_without_echoing_payload(tmp_path, changes):
    report = summarize(write(tmp_path, [row(**changes)]))
    assert not report["valid"] and report["groups"] == []
    assert "private" not in json.dumps(report)


def test_duplicate_requests_fail_but_repeated_items_allowed(tmp_path):
    assert not summarize(write(tmp_path, [row(), row()]))["valid"]
    report = summarize(write(tmp_path, [row(), row(request_id="req-2", model="other-model")]))
    assert report["valid"] and len(report["groups"]) == 2


def test_cli_exit_codes_and_no_empty_metrics(tmp_path):
    path = write(tmp_path, [])
    command = [sys.executable, "tools/summarize_evaluation.py", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1 and not json.loads(result.stdout)["valid"]
    write(tmp_path, [row()])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0 and json.loads(result.stdout)["valid"]


@pytest.mark.parametrize(
    "raw",
    ["not JSON", "{}", "[]", "\n", '{"request_id":"one","request_id":"two"}', '{"latency_ms":NaN}'],
)
def test_malformed_json_and_duplicate_keys_fail_closed(tmp_path, raw):
    path = tmp_path / "invalid.jsonl"
    path.write_text(raw, encoding="utf-8")
    assert not summarize(path)["valid"]


def test_all_unknown_usage_and_pending_are_not_zero_accuracy(tmp_path):
    record = row(answer_mode="written", verdict="pending", provider=None, model=None)
    for field in ("input_tokens", "output_tokens", "image_units", "estimated_cost_micros"):
        record.pop(field)
    report = summarize(write(tmp_path, [record]))
    assert report["valid"]
    assert report["overall"]["accuracy"] is None
    assert report["overall"]["input_tokens"] == {
        "total": None,
        "known_total": 0,
        "unknown_count": 1,
    }
    assert report["groups"][0]["provider"] is None


def test_p95_uses_nearest_rank_and_groups_do_not_mix_models(tmp_path):
    records = [row(request_id=f"req-{n}", latency_ms=n, model="first") for n in range(1, 21)]
    records += [row(request_id="req-other", latency_ms=1000, model="second")]
    report = summarize(write(tmp_path, records))
    first, second = report["groups"]
    assert first["latency_ms"]["p95"] == 19
    assert first["requests"] == 20 and second["requests"] == 1


def test_unreadable_and_resource_limited_files(tmp_path, monkeypatch):
    import summarize_evaluation as module

    assert not summarize(tmp_path / "absent.jsonl")["valid"]
    path = write(tmp_path, [row()])
    monkeypatch.setattr(module, "MAX_LINE_BYTES", 10)
    assert summarize(path)["errors"][0]["code"] == "resource_limit"


def test_record_limit_and_extreme_integers_fail_closed(tmp_path, monkeypatch):
    import summarize_evaluation as module

    path = write(tmp_path, [row(), row(request_id="req-2")])
    monkeypatch.setattr(module, "MAX_RECORDS", 1)
    assert summarize(path)["errors"][0]["code"] == "resource_limit"
    assert not summarize(write(tmp_path, [row(latency_ms=2**63)]))["valid"]


def test_deep_json_is_reported_as_invalid_not_a_traceback(tmp_path):
    path = tmp_path / "deep.jsonl"
    path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    assert summarize(path)["errors"][0]["code"] == "invalid_record"
