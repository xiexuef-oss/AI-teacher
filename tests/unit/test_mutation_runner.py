"""Mutation evidence must distinguish failed assertions from broken test infrastructure."""

import subprocess
from pathlib import Path

import mutation_check as runner
import pytest


@pytest.fixture(autouse=True)
def isolated_evidence_root(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "DEFAULT_OUTPUT_ROOT", tmp_path / "artifacts")


@pytest.mark.parametrize(
    ("xml", "code", "expected"),
    [
        ("<testsuite><testcase/></testsuite>", 0, "passed"),
        ('<testsuite><testcase><failure message="assert"/></testcase></testsuite>', 1, "failed"),
        (
            '<testsuite><testcase><error message="ImportError"/></testcase></testsuite>',
            1,
            "invalid",
        ),
        ("<testsuite><testcase><skipped/></testcase></testsuite>", 0, "not_run"),
        ("<testsuite><testcase/><testcase><skipped/></testcase></testsuite>", 0, "not_run"),
        ("<testsuite><testcase><failure/></testcase></testsuite>", 2, "invalid"),
        ('<testsuite><testcase><failure type="ImportError"/></testcase></testsuite>', 1, "invalid"),
        ("not xml", 1, "invalid"),
        ("<testsuite/>", 5, "invalid"),
    ],
)
def test_run_requires_actual_assertion_evidence(monkeypatch, xml, code, expected):
    def fake_run(command, **kwargs):
        output = command[command.index("--junitxml") + 1]
        Path(output).write_text(xml, encoding="utf-8")
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._run(("tests/guard.py",)).status == expected


def test_missing_junit_is_invalid(monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1))
    assert runner._run(("tests/guard.py",)).status == "invalid"


def mutation(tmp_path, tests=("tests/guard.py",)):
    path = tmp_path / "guard.py"
    path.write_bytes(b"if guarded:\r\n    pass\r\n")
    return runner.Mutation("test guard", path, "if guarded:", "if False:", tests)


def test_baseline_failure_never_mutates(monkeypatch, tmp_path):
    item = mutation(tmp_path)
    before = item.path.read_bytes()
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.setattr("sys.argv", ["mutation_check", "--only", "test guard"])
    monkeypatch.setattr(runner, "_run", lambda tests: runner.TestRun("failed"))
    assert runner.main() == 1
    assert item.path.read_bytes() == before


def test_mutation_restores_exact_bytes_after_runner_exception(monkeypatch, tmp_path):
    item = mutation(tmp_path)
    before = item.path.read_bytes()
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.setattr("sys.argv", ["mutation_check"])
    calls = 0

    def run(tests):
        nonlocal calls
        calls += 1
        if calls == 1:
            return runner.TestRun("passed")
        raise RuntimeError("runner failed")

    monkeypatch.setattr(runner, "_run", run)
    with pytest.raises(RuntimeError, match="runner failed"):
        runner.main()
    assert item.path.read_bytes() == before


@pytest.mark.parametrize("configured", [False, True])
def test_infra_skip_never_counts_as_caught(monkeypatch, tmp_path, capsys, configured):
    item = mutation(tmp_path, ("tests/integration/test_redis_invite_limits.py",))
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.setattr("sys.argv", ["mutation_check"])
    monkeypatch.setenv("TUTOR_REDIS_RECEIPT_TEST_CONFIG", "credentials.json")
    if not configured:
        monkeypatch.delenv("TUTOR_REDIS_RECEIPT_TEST_CONFIG")
    monkeypatch.setattr(runner, "_run", lambda tests: runner.TestRun("not_run"))
    assert runner.main() == 1
    output = capsys.readouterr().out
    assert "0/1" in output
    assert ("preflight_failed" if configured else "not_run") in output


def test_allow_not_run_is_explicit_and_not_coverage(monkeypatch, tmp_path, capsys):
    item = mutation(tmp_path, ("tests/integration/test_redis_invite_limits.py",))
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.delenv("TUTOR_REDIS_RECEIPT_TEST_CONFIG", raising=False)
    monkeypatch.setattr("sys.argv", ["mutation_check", "--allow-not-run"])
    assert runner.main() == 0
    assert "0/1" in capsys.readouterr().out


@pytest.mark.parametrize(
    "status,exit_code", [("failed", 0), ("passed", 1), ("invalid", 1), ("not_run", 1)]
)
def test_only_assertion_failure_counts_as_caught(monkeypatch, tmp_path, capsys, status, exit_code):
    item = mutation(tmp_path)
    before = item.path.read_bytes()
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.setattr("sys.argv", ["mutation_check", "--only", "guard"])
    results = iter([runner.TestRun("passed"), runner.TestRun(status)])
    monkeypatch.setattr(runner, "_run", lambda tests: next(results))
    assert runner.main() == exit_code
    assert item.path.read_bytes() == before
    assert ("1/1" if status == "failed" else "0/1") in capsys.readouterr().out


def test_shared_baseline_is_cached_without_skipping_mutations(monkeypatch, tmp_path):
    item = mutation(tmp_path)
    monkeypatch.setattr(runner, "MUTATIONS", [item, item])
    monkeypatch.setattr("sys.argv", ["mutation_check"])
    results = iter([runner.TestRun("passed"), runner.TestRun("failed"), runner.TestRun("failed")])
    monkeypatch.setattr(runner, "_run", lambda tests: next(results))
    assert runner.main() == 0
    assert next(results, None) is None


def test_multiline_matching_accepts_crlf_and_restores_bytes(monkeypatch, tmp_path):
    item = mutation(tmp_path)
    item = runner.Mutation(
        item.name, item.path, "if guarded:\n    pass", "if False:\n    pass", item.tests
    )
    before = item.path.read_bytes()
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.setattr("sys.argv", ["mutation_check"])
    results = iter([runner.TestRun("passed"), runner.TestRun("failed")])
    monkeypatch.setattr(runner, "_run", lambda tests: next(results))
    assert runner.main() == 0
    assert item.path.read_bytes() == before


def test_guard_collection_failure_is_preflight_failure(monkeypatch, tmp_path, capsys):
    item = mutation(tmp_path)
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.setattr("sys.argv", ["mutation_check"])
    monkeypatch.setattr(runner, "_run", lambda tests: runner.TestRun("invalid"))
    assert runner.main() == 1
    assert "preflight_failed=1" in capsys.readouterr().out


def test_shared_http_limit_mutation_requires_explicit_redis_configuration():
    tests = (
        "tests/integration/test_http_limit_redis.py::"
        "test_authenticated_limits_shared_between_two_instances",
    )
    assert runner._required_environment(tests) == ("TUTOR_REDIS_RECEIPT_TEST_CONFIG",)


def test_linux_doc_mutations_require_explicit_sandbox_configuration():
    assert runner._required_environment(
        (
            "tests/integration/test_linux_parser_sandbox.py::test_host_files_environment_and_network_are_not_available",
        )
    ) == ("TUTOR_LINUX_SANDBOX_CONFIG",)


def test_draft_copy_concurrency_mutations_require_explicit_services():
    assert runner._required_environment(
        ("tests/integration/test_submission_statistics_mysql.py",)
    ) == ("TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS", "TUTOR_REDIS_RECEIPT_TEST_CONFIG")


def test_session_version_concurrency_mutations_require_explicit_services():
    assert runner._required_environment(
        ("tests/integration/test_session_version_guard_mysql.py",)
    ) == ("TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS", "TUTOR_REDIS_RECEIPT_TEST_CONFIG")


def test_session_copy_review_locks_require_explicit_services():
    assert runner._required_environment(
        ("tests/integration/test_session_create_copy_review_locks_mysql.py",)
    ) == ("TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS", "TUTOR_REDIS_RECEIPT_TEST_CONFIG")


def test_submit_revision_mutations_require_explicit_services():
    assert runner._required_environment(
        ("tests/integration/test_submit_revision_guard_mysql.py",)
    ) == ("TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS", "TUTOR_REDIS_RECEIPT_TEST_CONFIG")


def test_first_submission_pointer_requires_explicit_services():
    assert runner._required_environment(
        ("tests/integration/test_first_submitted_attempt_mysql.py",)
    ) == ("TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS", "TUTOR_REDIS_RECEIPT_TEST_CONFIG")


def test_profile_revision_requires_explicit_mysql():
    assert runner._required_environment(("tests/integration/test_profile_revision_mysql.py",)) == (
        "TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS",
    )


def test_parent_revision_requires_explicit_mysql():
    assert runner._required_environment(("tests/integration/test_parent_revision_mysql.py",)) == (
        "TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS",
    )


@pytest.mark.parametrize(
    "target,required",
    [
        ("tests/integration/test_s3_blob_service.py", True),
        ("tests/integration/test_managed_runtime.py", True),
        (
            "tests/integration/test_managed_runtime.py::test_managed_mysql_redis_s3_startup_lists_without_writes_or_client_ownership",
            True,
        ),
        (
            "tests/integration/test_managed_runtime.py::test_managed_s3_startup_failure_is_redacted_and_does_not_fall_back",
            True,
        ),
        (
            "tests/integration/test_managed_runtime.py::test_managed_startup_is_read_only_and_ping_does_not_charge",
            False,
        ),
    ],
)
def test_s3_mutations_require_explicit_storage_config_only_when_used(target, required):
    assert ("TUTOR_S3_BLOB_TEST_CONFIG" in runner._required_environment((target,))) is required


def test_subprocess_evidence_survives_run_and_includes_no_environment(monkeypatch, tmp_path):
    import json

    def fake(command, **kwargs):
        Path(command[command.index("--junitxml") + 1]).write_text(
            "<testsuite><testcase><failure/></testcase></testsuite>", encoding="utf-8"
        )
        return subprocess.CompletedProcess(
            command, 1, stdout="assertion output", stderr="diagnostic stderr"
        )

    monkeypatch.setattr(runner.subprocess, "run", fake)
    monkeypatch.setattr(runner, "DEFAULT_OUTPUT_ROOT", tmp_path)
    monkeypatch.setenv("TUTOR_TEST_PRIVATE_SECRET", "never-write-environment")
    result = runner._run(("tests/guard.py",))
    artifact = Path(result.artifact)
    assert (artifact / "stdout.log").read_text() == "assertion output"
    assert (artifact / "stderr.log").read_text() == "diagnostic stderr"
    assert (artifact / "junit.xml").is_file()
    metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed" and metadata["returncode"] == 1
    assert metadata["tests"] == ["tests/guard.py"]
    assert "never-write-environment" not in json.dumps(metadata)
    second = runner._run(("tests/guard.py",))
    assert second.artifact != result.artifact and artifact.is_dir()


def test_failed_baseline_summary_links_persistent_evidence(monkeypatch, tmp_path, capsys):
    import json

    item = mutation(tmp_path)
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.setattr("sys.argv", ["mutation_check", "--output", str(tmp_path / "evidence")])

    def fake(command, **kwargs):
        Path(command[command.index("--junitxml") + 1]).write_text(
            "<testsuite><testcase><failure/></testcase></testsuite>"
        )
        return subprocess.CompletedProcess(command, 1, stdout="baseline failed", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake)
    assert runner.main() == 1
    summary_path = next((tmp_path / "evidence").glob("mutation-evidence-*/summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    target = summary["targets"][0]
    assert target["status"] == "preflight_failed"
    assert Path(target["baseline"]["artifact"]).is_dir()
    assert str(summary_path) in capsys.readouterr().out


@pytest.mark.parametrize("failed_file", ["metadata.json", "summary.json"])
def test_evidence_write_error_restores_source_and_resets_context(
    monkeypatch, tmp_path, failed_file
):
    item = mutation(tmp_path)
    original = item.path.read_bytes()
    monkeypatch.setattr(runner, "MUTATIONS", [item])
    monkeypatch.setattr("sys.argv", ["mutation_check", "--output", str(tmp_path / "evidence")])
    runs = 0

    def fake(command, **kwargs):
        nonlocal runs
        runs += 1
        xml = (
            "<testsuite><testcase/></testsuite>"
            if runs == 1
            else "<testsuite><testcase><failure/></testcase></testsuite>"
        )
        Path(command[command.index("--junitxml") + 1]).write_text(xml, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0 if runs == 1 else 1, stdout=None, stderr=None)

    monkeypatch.setattr(runner.subprocess, "run", fake)
    write = Path.write_text

    def fail(path, *args, **kwargs):
        if runs == 2 and path.name == failed_file:
            raise OSError("evidence disk failure")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail)
    previous = runner._EVIDENCE_ROOT.get()
    with pytest.raises(OSError, match="evidence disk failure"):
        runner.main()
    assert item.path.read_bytes() == original
    assert runner._EVIDENCE_ROOT.get() is previous


def test_summary_reuses_baseline_and_keeps_each_mutation_evidence(monkeypatch, tmp_path):
    import json

    item = mutation(tmp_path)
    monkeypatch.setattr(runner, "MUTATIONS", [item, item])
    monkeypatch.setattr("sys.argv", ["mutation_check", "--output", str(tmp_path / "evidence")])
    runs = 0

    def fake(command, **kwargs):
        nonlocal runs
        runs += 1
        code = 0 if runs == 1 else 1
        xml = (
            "<testsuite><testcase/></testsuite>"
            if code == 0
            else "<testsuite><testcase><failure/></testcase></testsuite>"
        )
        Path(command[command.index("--junitxml") + 1]).write_text(xml, encoding="utf-8")
        return subprocess.CompletedProcess(
            command, code, stdout="persisted test output", stderr=None
        )

    monkeypatch.setattr(runner.subprocess, "run", fake)
    assert runner.main() == 0
    summary_path = next((tmp_path / "evidence").glob("mutation-evidence-*/summary.json"))
    original_summary = summary_path.read_bytes()
    summary = json.loads(original_summary)
    first, second = summary["targets"]
    assert summary["counts"]["caught"] == 2 and runs == 3
    assert first["baseline"]["artifact"] == second["baseline"]["artifact"]
    assert first["result"]["artifact"] != second["result"]["artifact"]
    assert all(
        Path(target["result"]["artifact"], "stdout.log").is_file() for target in summary["targets"]
    )
    runs = 0
    assert runner.main() == 0
    assert len(list((tmp_path / "evidence").glob("mutation-evidence-*/summary.json"))) == 2
    assert summary_path.read_bytes() == original_summary
