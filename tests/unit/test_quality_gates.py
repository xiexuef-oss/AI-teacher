import json
import subprocess
import sys
from pathlib import Path

import pytest
import run_quality_gates as quality


def test_plan_covers_project_gates():
    gates = quality.plan("uv", "npm", "flutter", "dart")
    assert {gate.name for gate in gates} == {
        "pytest",
        "ruff",
        "dart-generated",
        "flutter-test",
        "dart-analyze",
        "dart-test",
        "admin-test",
        "admin-typecheck",
        "admin-api",
    }
    assert all("analyze" not in gate.command or gate.command[0] == "dart" for gate in gates)


def test_failure_is_recorded_and_later_gates_still_run(tmp_path):
    gates = [
        quality.Gate("bad", (sys.executable, "-c", "raise SystemExit(7)"), "."),
        quality.Gate("good", (sys.executable, "-c", "print('done')"), "."),
    ]
    assert quality.run(gates, tmp_path, tmp_path / "report", timeout=10) == 1
    report = json.loads((tmp_path / "report/status.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert [item["status"] for item in report["gates"]] == ["failed", "passed"]
    assert report["gates"][0]["returncode"] == 7
    assert "done" in (tmp_path / "report/good.log").read_text(encoding="utf-8")


def test_missing_tool_and_timeout_are_failures(tmp_path):
    gates = [
        quality.Gate("missing", (str(tmp_path / "absent-tool"),), "."),
        quality.Gate("timeout", (sys.executable, "-c", "import time; time.sleep(5)"), "."),
    ]
    assert quality.run(gates, tmp_path, tmp_path / "report", timeout=0.1) == 1
    report = json.loads((tmp_path / "report/status.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in report["gates"]] == ["error", "timeout"]


def test_list_does_not_execute_or_create_report(tmp_path):
    script = Path(__file__).resolve().parents[2] / "tools/run_quality_gates.py"
    result = subprocess.run(
        [sys.executable, str(script), "--list", "--output", str(tmp_path / "report")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0
    assert "flutter-test" in result.stdout
    assert not (tmp_path / "report").exists()


def test_existing_output_is_not_overwritten(tmp_path):
    report = tmp_path / "report"
    report.mkdir()
    sentinel = report / "status.json"
    sentinel.write_text("old")
    with pytest.raises(FileExistsError):
        quality.run([], tmp_path, report, timeout=10)
    assert sentinel.read_text(encoding="utf-8") == "old"
