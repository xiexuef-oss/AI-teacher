"""联调工具（tools/e2e）里不需要浏览器的那部分：检查汇总、构建是否过期、端口、从样题里取数。

联调脚本本身要真实的浏览器、后端和 Web 构建，不在 pytest 里跑（见 tools/e2e/README.md）。
这里守的是它们依赖的数据不会悄悄走样：样题改了标题、答案、数据表，或者周报的最小样本数变了，
先在这里变红，而不是等到有人跑联调时才发现脚本对不上。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from e2e import data, servers
from e2e.checks import Checks
from e2e.flows import FLOWS, parent_weekly, student_proof
from support.seeds import EXPERIMENT_KEYS, OBJECTIVE_KEYS, PROOF_KEYS, qid
from tutor_api.services import grading
from tutor_api.services.content_seed import load_seed
from tutor_api.settings import Settings


@pytest.mark.parametrize("enabled", [False, True])
def test_scan_browser_service_explicitly_controls_mock_and_temporary_media(
    monkeypatch, tmp_path, enabled
):
    from types import SimpleNamespace

    captured = {}
    service = SimpleNamespace(process=None, log_path=tmp_path / "api.log")

    def spawn(*args, **kwargs):
        captured.update(kwargs["env"])
        return service

    monkeypatch.setenv("TUTOR_SCAN_MOCK_ENABLED", "true")
    monkeypatch.setattr(servers, "_spawn", spawn)
    monkeypatch.setattr(servers, "wait_for_url", lambda *args, **kwargs: None)
    assert servers.start_api(tmp_path, scan_enabled=enabled) is service
    assert captured["TUTOR_SCAN_MOCK_ENABLED"] == ("true" if enabled else "false")
    assert captured["TUTOR_MEDIA_LOCAL_ENABLED"] == ("true" if enabled else "false")


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestChecks:
    def test_counts_lines_and_exit_code(self):
        lines: list[str] = []
        checks = Checks(echo=lines.append)

        assert checks.check("通过的", True) is True
        assert checks.check("失败的", 0, "原因") is False

        assert checks.failed() == ["失败的"]
        assert checks.summary() == "共 2 项检查，通过 1 项，失败 1 项"
        assert checks.exit_code() == 1
        assert lines[0].startswith("  ✓ ") and "通过的" in lines[0]
        assert lines[1].startswith("  ✗ ") and "失败的" in lines[1] and "原因" in lines[1]

    def test_all_passing_exits_zero(self):
        checks = Checks(echo=lambda line: None)
        checks.check("a", 1)
        checks.check("b", "非空")
        assert checks.exit_code() == 0
        assert checks.failed() == []

    def test_a_passing_check_does_not_print_its_detail(self):
        lines: list[str] = []
        Checks(echo=lines.append).check("好的", True, "不该出现")
        assert "不该出现" not in lines[0]

    def test_a_long_detail_is_cut(self):
        lines: list[str] = []
        Checks(echo=lines.append).check("x", False, "字" * 2000)
        assert len(lines[0]) < 600

    def test_checks_can_be_merged_for_the_final_summary(self):
        first, second = Checks(echo=lambda line: None), Checks(echo=lambda line: None)
        first.check("a", True)
        second.check("b", False)
        first.extend(second)
        assert first.summary() == "共 2 项检查，通过 1 项，失败 1 项"
        assert first.failed() == ["b"]


class TestNeedsRebuild:
    @staticmethod
    def _tree(tmp_path: Path) -> tuple[Path, Path, Path]:
        built = tmp_path / "build" / "web" / "main.dart.js"
        built.parent.mkdir(parents=True)
        built.write_text("compiled")
        lib = tmp_path / "lib"
        (lib / "nested").mkdir(parents=True)
        source = lib / "nested" / "page.dart"
        source.write_text("source")
        return built, lib, source

    def test_a_missing_build_needs_a_build(self, tmp_path):
        reason = servers.needs_rebuild(tmp_path / "nope" / "main.dart.js", [tmp_path])
        assert reason and "没有" in reason

    def test_up_to_date_when_every_source_is_older(self, tmp_path):
        built, lib, source = self._tree(tmp_path)
        os.utime(source, (1_000, 1_000))
        os.utime(built, (2_000, 2_000))
        assert servers.needs_rebuild(built, [lib]) is None

    def test_a_newer_source_makes_it_stale_and_names_the_file(self, tmp_path):
        built, lib, source = self._tree(tmp_path)
        os.utime(built, (1_000, 1_000))
        os.utime(source, (2_000, 2_000))
        reason = servers.needs_rebuild(built, [lib])
        assert reason and "page.dart" in reason

    def test_sources_can_be_single_files(self, tmp_path):
        built, _, _ = self._tree(tmp_path)
        pubspec = tmp_path / "pubspec.yaml"
        pubspec.write_text("name: x")
        os.utime(built, (1_000, 1_000))
        os.utime(pubspec, (2_000, 2_000))
        assert servers.needs_rebuild(built, [pubspec])

    def test_a_source_that_does_not_exist_is_skipped(self, tmp_path):
        built, lib, source = self._tree(tmp_path)
        os.utime(source, (1_000, 1_000))
        os.utime(built, (2_000, 2_000))
        assert servers.needs_rebuild(built, [tmp_path / "no-such-dir", lib]) is None


def test_port_in_use_tells_a_listening_port_from_a_free_one():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert servers.port_in_use(port) is True
    assert servers.port_in_use(port) is False


class TestSeedData:
    def test_titles_come_from_the_seed(self):
        assert data.title_of("phys-tape-experiment") == "用纸带数据测小车的加速度"
        with pytest.raises(KeyError):
            data.title_of("no-such-question")

    def test_question_ids_are_the_ones_the_api_serves(self):
        assert data.question_id("math-mono-judge") == qid("math-mono-judge")

    def test_blank_cells_and_their_reference_values_line_up(self):
        cells = data.blank_cells("chem-titration-experiment")
        refs = data.reference_values("chem-titration-experiment")
        assert len(cells) == 5 and ("t1", "r1", "dv") in cells
        assert set(refs) == set(cells)
        assert refs[("t1", "r1", "dv")] == "20.05"
        assert refs[("t2", "r2", "val")] == "0.1004"

    @pytest.mark.parametrize("key", sorted(EXPERIMENT_KEYS))
    def test_every_experiment_seed_has_what_the_flows_look_at(self, key):
        question = data.question(key)
        assert question["content"]["safety"]["notes"]
        assert question["content"]["data_tables"]
        assert data.blank_cells(key)
        assert data.points_of(key)

    @pytest.mark.parametrize("key", sorted(PROOF_KEYS))
    def test_every_proof_seed_has_what_the_flows_look_at(self, key):
        question = data.question(key)
        statement = question["content"]["proof"]
        assert statement["claim"] and statement["givens"]
        steps = question["answer"]["value"]["steps"]
        assert steps[-1]["stage"] == "conclusion"
        assert data.points_of(key)

    def test_published_counts_follow_the_seed(self):
        questions = load_seed().questions
        assert data.published_count() == len(questions)
        experiments = [q for q in questions if q["answer_mode"] == "experiment"]
        assert data.published_count("experiment") == len(experiments) == len(EXPERIMENT_KEYS)
        proofs = [q for q in questions if q["answer_mode"] == "proof"]
        assert data.published_count("proof") == len(proofs) == len(PROOF_KEYS)

    @pytest.mark.parametrize("key", ["math-circle-radius-proof", "math-triangle-coordinate-proof"])
    def test_visible_proof_matching_requires_all_math_and_claim(self, key):
        from e2e.flows.subject_diagrams import _proof_text_visible

        proof = data.question(key)["content"]["proof"]
        required = [*proof["givens"], proof["claim"]]
        rendered = "\n".join(required).replace("$", "")
        assert _proof_text_visible(proof, rendered)
        for item in required:
            assert not _proof_text_visible(proof, rendered.replace(item.replace("$", ""), ""))
        if key == "math-circle-radius-proof":
            assert not _proof_text_visible(proof, rendered.replace("x^2+y^2=1", ""))

    @pytest.mark.parametrize("key", sorted(PROOF_KEYS))
    def test_a_proof_answer_is_a_list_of_steps_with_reasons(self, key):
        answer = data.answer_for(key, "proof")
        assert set(answer) == {"steps"}
        assert all(set(step) == {"text", "reason"} for step in answer["steps"])

    @pytest.mark.parametrize("key", sorted(OBJECTIVE_KEYS))
    def test_the_correct_and_the_wrong_answer_grade_as_named(self, key):
        question = data.question(key)
        for kind, expected in (("correct", True), ("wrong", False)):
            result = grading.grade(
                answer_mode=question["answer_mode"],
                content=question["content"],
                answer_key=question["answer"],
                rubric=question.get("rubric") or {},
                teaching=question.get("teaching") or {},
                answer=data.answer_for(key, kind),
            )
            assert result.is_correct is expected, (key, kind)


class TestParentWeeklyPlan:
    def test_the_plan_only_uses_questions_the_seed_has(self):
        for key, kind in parent_weekly.PLAN:
            assert data.question(key)
            if kind == "written":
                assert data.question(key)["answer_mode"] == "written"
            else:
                assert data.question(key)["answer_mode"] != "written"
                assert kind in ("correct", "wrong")

    def test_the_expected_figures_follow_from_the_plan(self):
        expected = parent_weekly.expected_weekly()
        objective = [kind for _, kind in parent_weekly.PLAN if kind != "written"]
        assert expected["attempts"] == len(parent_weekly.PLAN)
        assert expected["written"] == len(parent_weekly.PLAN) - len(objective)
        assert expected["independent_total"] == len(objective)
        assert expected["independent_correct"] == objective.count("correct")
        assert expected["rate"] == round(100 * objective.count("correct") / len(objective))

    def test_there_are_enough_samples_for_the_weekly_report_to_show_percentages(self):
        # 周报在样本不足时只给计数、不显示百分比：联调要看百分比，计划里的客观题就得够数
        assert (
            parent_weekly.expected_weekly()["independent_total"] >= Settings().progress_min_samples
        )


class TestStudentProofFlow:
    """学生端证明题联调要用到的题和学生写的步骤，对得上样题。"""

    def test_the_flow_uses_a_proof_question_that_exists(self):
        question = data.question(student_proof.KEY)
        assert question["answer_mode"] == "proof"
        assert data.title_of(student_proof.KEY)

    def test_the_flow_moves_the_third_step_up_by_one(self):
        # 写的顺序是 甲、乙、丙，上移第 3 步之后是 甲、丙、乙：提交的就是这个顺序
        a, b, c = student_proof.STEP_A, student_proof.STEP_B, student_proof.STEP_C
        assert [a, c, b] == student_proof.SUBMITTED
        assert c[1] == "", "第 3 步故意没写依据"

    def test_there_are_reasons_without_formulas_to_look_for_on_the_page(self):
        # 参考证明里没有公式的依据在页面上能直接按文字找到：联调靠它们判断参考证明显示出来了
        steps = data.question(student_proof.KEY)["answer"]["value"]["steps"]
        assert [step for step in steps if "$" not in step["reason"]]

    def test_the_typed_steps_do_not_contain_the_reference_reasons(self):
        # 提交之前页面上不能有参考证明里的依据：学生自己打的字不能恰好撞上它们，否则这项检查会误报
        steps = data.question(student_proof.KEY)["answer"]["value"]["steps"]
        typed = " ".join(text + reason for text, reason in student_proof.SUBMITTED)
        assert not [step["reason"] for step in steps if step["reason"] in typed]


class TestFlowRegistry:
    def test_the_flows_are_registered_in_order(self):
        assert len(FLOWS) == 23
        assert list(FLOWS) == [
            "student_experiment",
            "student_proof",
            "student_draft_recovery",
            "student_draft_copies",
            "student_creation_recovery",
            "student_write_recovery",
            "student_resource_recovery",
            "student_profile_recovery",
            "local_draft_export",
            "student_topic_choice",
            "student_diagnostic",
            "subject_diagrams",
            "student_scan",
            "student_scan_recovery",
            "admin_experiment",
            "admin_write_recovery",
            "admin_question_recovery",
            "parent_weekly",
            "parent_write_recovery",
            "document_import",
            "admin_batch_write_recovery",
            "admin_media_write_recovery",
            "admin_document_write_recovery",
        ]

    def test_every_flow_says_what_it_is_and_what_it_needs(self):
        for name, flow in FLOWS.items():
            assert flow.name == name
            assert flow.title
            assert flow.needs and flow.needs <= {"flutter", "admin"}

    def test_importing_the_flows_does_not_need_a_browser(self):
        # --list 和这些测试都不该因为没装 playwright 而失败
        probe = "import sys; import e2e.flows; sys.exit(1 if 'playwright' in sys.modules else 0)"
        paths = [REPO_ROOT / "tools", REPO_ROOT / "tests", REPO_ROOT / "services" / "api"]
        paths.append(REPO_ROOT / "services" / "ai_gateway")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in paths)}
        done = subprocess.run(
            [sys.executable, "-c", probe],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=REPO_ROOT,
        )
        assert done.returncode == 0, done.stderr


class TestDraftRecoveryFixtures:
    def test_engineering_question_has_three_distinct_single_choice_options(self):
        from e2e.flows.student_draft_recovery import KEY

        question = data.question(KEY)
        assert KEY in OBJECTIVE_KEYS
        assert question["answer_mode"] == "single_choice"
        options = question["content"]["options"]
        assert len({option["key"] for option in options}) >= 3
        assert data.title_of(KEY)
        assert data.question_id(KEY) == qid(KEY)


class TestDocumentImportFixtures:
    def test_self_authored_json_contains_one_deliberate_batch_failure(self):
        import json

        from e2e.flows.document_import import sample_payload, upload_fixtures
        from tutor_api.schemas import AdminQuestionImportIn

        sample = sample_payload()
        assert sample["source"]["source_type"] == "self_authored"
        assert sample["source"]["source_license"]
        AdminQuestionImportIn.model_validate(sample)
        entries = json.loads(upload_fixtures()[0]["buffer"])
        assert len(entries) == 2
        assert entries[0] == sample
        assert entries[1]["question"]["knowledge"] == ["missing-e2e-knowledge"]
        assert (
            entries[0]["question"]["content"]["stem"] == entries[1]["question"]["content"]["stem"]
        )

    def test_multifile_fixtures_are_small_and_have_the_expected_text(self):
        import io
        import zipfile

        from pypdf import PdfReader

        from e2e.flows.document_import import DOCX_TEXT, PDF_TEXT, upload_fixtures

        files = upload_fixtures()
        assert [f["name"].rsplit(".", 1)[1] for f in files] == ["json", "pdf", "pdf", "pdf", "docx"]
        assert all(0 < len(f["buffer"]) < Settings().import_max_file_bytes for f in files)
        assert PDF_TEXT in PdfReader(io.BytesIO(files[1]["buffer"])).pages[0].extract_text()
        with zipfile.ZipFile(io.BytesIO(files[4]["buffer"])) as doc:
            assert DOCX_TEXT in doc.read("word/document.xml").decode()


def test_server_copy_browser_seed_supports_three_distinct_choices():
    from e2e.flows.student_draft_copies import KEY

    question = data.question(KEY)
    assert question["answer_mode"] == "single_choice"
    assert len({option["key"] for option in question["content"]["options"]}) >= 3


@pytest.mark.parametrize("double_encoded", [False, True])
def test_draft_browser_evidence_reads_scoped_active_and_explicit_copy(monkeypatch, double_encoded):
    import json

    from e2e.flows import student_draft_recovery as flow

    def encode(value):
        raw = json.dumps(value)
        return json.dumps(raw) if double_encoded else raw

    values = {
        "flutter.u/user/active/q": encode({"attemptId": "copy"}),
        "flutter.u/user/draft-bundle/q": encode(
            {
                "drafts": {
                    "attempt/source": {"attemptId": "source", "answer": {"selected": ["A"]}},
                    "attempt/copy": {"attemptId": "copy", "answer": {"selected": ["B"]}},
                }
            }
        ),
        "flutter.u/user/draft/q": encode({"attemptId": "source", "answer": {"selected": ["old"]}}),
        "flutter.u/user/draft-recovery/q/attempt/copy": encode(
            {"pending": True, "copies": [{"answer": {"selected": ["B"]}}]}
        ),
    }
    before = dict(values)
    monkeypatch.setattr(flow, "stored_all", lambda page: values)
    assert flow._record(None, "draft", "q")["attemptId"] == "copy"
    assert flow._record(None, "draft", "q", "source")["answer"]["selected"] == ["A"]
    assert flow._record(None, "draft-recovery", "q")["pending"] is True
    assert values == before


def test_draft_browser_evidence_keeps_legacy_and_does_not_cross_attempt(monkeypatch):
    import json

    from e2e.flows import student_draft_recovery as flow

    values = {"flutter.u/user/draft/q": json.dumps({"attemptId": "original"})}
    monkeypatch.setattr(flow, "stored_all", lambda page: values)
    assert flow._record(None, "draft", "q")["attemptId"] == "original"
    assert flow._record(None, "draft", "q", "different") == {}


@pytest.mark.parametrize("active", [{"attemptId": "new"}, None])
def test_draft_browser_bundle_active_overrides_stale_legacy_pointer(monkeypatch, active):
    import json

    from e2e.flows import student_draft_recovery as flow

    values = {
        "flutter.u/user/active/q": json.dumps({"attemptId": "old"}),
        "flutter.u/user/draft-bundle/q": json.dumps(
            {
                "active": active,
                "drafts": {
                    "attempt/old": {"attemptId": "old"},
                    "attempt/new": {"attemptId": "new"},
                },
            }
        ),
        "flutter.u/user/draft-recovery/q/attempt/old": json.dumps({"pending": True, "old": True}),
        "flutter.u/user/draft-recovery/q/attempt/new": json.dumps({"pending": True, "new": True}),
    }
    original = dict(values)
    monkeypatch.setattr(flow, "stored_all", lambda page: values)
    assert flow._record(None, "draft", "q") == ({"attemptId": "new"} if active else {})
    assert flow._record(None, "draft-recovery", "q") == (
        {"pending": True, "new": True} if active else {}
    )
    assert flow._record(None, "draft", "q", "old") == {"attemptId": "old"}
    assert values == original


class TestLostCopyResponseHarness:
    def test_executes_real_request_before_aborting_only_success(self):
        from e2e.flows.student_draft_copies import LostCopyResponse

        calls = []

        class Response:
            status = 201

            def json(self):
                return {"data": {"attempt": {"id": "created-by-server"}}}

        class Request:
            method = "POST"
            headers = {"idempotency-key": "stable-copy-key"}

        class Route:
            request = Request()

            def fetch(self):
                calls.append("fetch")
                return Response()

            def abort(self, reason):
                calls.append(("abort", reason))

        harness = LostCopyResponse()
        harness(Route())
        assert calls == ["fetch", ("abort", "connectionclosed")]
        assert harness.result["attempt"]["id"] == "created-by-server"
        assert harness.key == "stable-copy-key"

    def test_server_failure_is_forwarded_instead_of_fabricating_a_lost_success(self):
        from e2e.flows.student_draft_copies import LostCopyResponse

        calls = []

        class Response:
            status = 409

        response = Response()

        class Route:
            def fetch(self):
                calls.append("fetch")
                return response

            def fulfill(self, **kwargs):
                calls.append(("fulfill", kwargs["response"]))

        harness = LostCopyResponse()
        harness(Route())
        assert calls == ["fetch", ("fulfill", response)]
        assert harness.result is None and harness.key is None


@pytest.mark.parametrize(
    "drafts,cleared,expected",
    [
        ({"attempt/current": {"attemptId": "current"}}, [], False),
        ({"attempt/other": {"attemptId": "other"}}, ["attempt/current"], True),
        ({"attempt/current": {"attemptId": "current"}}, ["attempt/current"], False),
        ({}, [], False),
    ],
)
def test_subject_browser_proves_specific_slot_cleared_not_legacy_key_absence(
    monkeypatch, drafts, cleared, expected
):
    from e2e.flows import student_proof

    monkeypatch.setattr(
        student_proof, "_record", lambda page, kind, qid: {"drafts": drafts, "cleared": cleared}
    )
    assert student_proof._draft_cleared(None, "question", "current") is expected


def test_experiment_browser_filters_before_opening_seed_title(monkeypatch):
    from e2e.flows import student_experiment as flow

    calls = []
    monkeypatch.setattr(
        flow, "has", lambda page, label, **kw: label == "实验题" and kw["role"] == "checkbox"
    )
    monkeypatch.setattr(flow, "tap", lambda page, label, **kw: calls.append((label, kw)))
    title = data.title_of(flow.KEY)
    flow._open_experiment_questions(None, title)
    assert [label for label, _ in calls] == ["练习", "实验题", title]
    assert calls[1][1]["role"] == "checkbox"


def test_creation_recovery_harness_forwards_real_post_before_losing_response():
    from e2e.flows.student_creation_recovery import LostCreationResponse

    calls = []

    class Request:
        headers = {"idempotency-key": "persisted-create-key"}
        post_data_json = {"question_id": "q", "origin": "practice", "expected_question_version": 1}

    class Response:
        status = 201

        def json(self):
            return {"data": {"id": "real-server-id"}}

    class Route:
        request = Request()

        def fetch(self):
            calls.append("fetch")
            return Response()

        def abort(self, reason):
            calls.append(("abort", reason))

    lost = LostCreationResponse()
    lost(Route())
    assert calls == ["fetch", ("abort", "connectionclosed")]
    assert lost.result == {"id": "real-server-id"}
    assert lost.body == Request.post_data_json and lost.key == "persisted-create-key"


def test_creation_recovery_reads_current_command_history_and_keeps_storage_unchanged():
    import copy

    from e2e.flows.student_creation_recovery import creation_command, local_choice

    command = {
        "intentId": "intent",
        "sessionKey": "session-key",
        "attemptKey": "attempt-key",
        "phase": "session_prepared",
    }
    bundle = {
        "creationIntents": {
            "local/workspace": {"current": "intent", "history": {"intent": command}}
        },
        "drafts": {"local/workspace": {"answer": {"selected": ["chosen"]}}},
    }
    before = copy.deepcopy(bundle)
    assert creation_command(bundle, "session-key") == command
    assert creation_command(bundle, "attempt-key") == command
    assert creation_command(bundle, "unknown") == {}
    assert local_choice(bundle, "chosen") is True
    assert bundle == before


def test_unsent_creation_blocks_without_calling_server():
    from e2e.flows.student_creation_recovery import UnsentSessionCreation

    calls = []

    class Request:
        headers = {"idempotency-key": "original-version-key"}
        post_data_json = {"expected_question_version": 1}

    class Route:
        request = Request()

        def fetch(self):
            raise AssertionError("Offline creation must never reach server")

        def abort(self, reason):
            calls.append(reason)

    block = UnsentSessionCreation()
    block(Route())
    assert calls == ["internetdisconnected"]
    assert block.requests == [("original-version-key", {"expected_question_version": 1})]


def test_creation_recovery_distinguishes_explicit_and_canonical_workspace_routes():
    from e2e.flows.student_creation_recovery import bound_route_ids

    assert bound_route_ids(
        "http://localhost/#/questions/q/solve?session=S1&attempt=A1&origin=practice"
    ) == ("S1", "A1")
    assert bound_route_ids("http://localhost/#/questions/q/solve?origin=practice") == (None, None)


def test_write_recovery_hold_executes_actual_request_but_releases_only_explicitly():
    from e2e.flows.student_write_recovery import HoldWriteResponse

    calls = []

    class Request:
        headers = {"idempotency-key": "write-intent-key"}
        post_data_json = {"answer": {"selected_options": ["A"]}, "expected_draft_revision": 1}

    class Response:
        status = 200

        def json(self):
            return {"data": {"attempt": {"id": "real-attempt"}}}

    class Route:
        request = Request()

        def fetch(self):
            calls.append("fetch")
            return Response()

        def fulfill(self, **kwargs):
            calls.append(("fulfill", kwargs["response"]))

    hold = HoldWriteResponse()
    hold(Route())
    assert calls == ["fetch"]
    assert hold.body == Request.post_data_json and hold.result["attempt"]["id"] == "real-attempt"
    hold.release()
    assert len(calls) == 2 and calls[1][0] == "fulfill"


@pytest.mark.parametrize("minutes", [None, (1, 2, 3)])
def test_review_flow_passes_optional_real_due_intervals(monkeypatch, tmp_path, minutes):
    from types import SimpleNamespace

    captured = {}
    service = SimpleNamespace(process=None, log_path=tmp_path / "api.log")

    def spawn(name, command, **kwargs):
        captured["command"] = command
        return service

    monkeypatch.setattr(servers, "_spawn", spawn)
    monkeypatch.setattr(servers, "wait_for_url", lambda *args, **kwargs: None)
    servers.start_api(tmp_path, review_minutes=minutes)
    command = captured["command"]
    assert ("--review-minutes" in command) == (minutes is not None)
    if minutes:
        assert command[-2:] == ["--review-minutes", "1,2,3"]


def test_resource_recovery_only_flow_changes_real_review_timing():
    assert FLOWS["student_resource_recovery"].review_minutes == (1, 2, 3)
    assert all(
        flow.review_minutes is None
        for key, flow in FLOWS.items()
        if key != "student_resource_recovery"
    )


def test_resource_flow_seed_has_two_hint_levels_and_verified_review_answers():
    from e2e.flows.student_resource_recovery import KEY

    assert len(data.question(KEY)["teaching"]["hints"]) >= 2
    assert data.answer_for(KEY, "correct") != data.answer_for(KEY, "wrong")


@pytest.mark.parametrize("minutes", [(), (0,), (True,), ("1",)])
def test_review_interval_tool_rejects_invalid_values_without_launch(monkeypatch, tmp_path, minutes):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid interval must not start process")

    monkeypatch.setattr(servers, "_spawn", forbidden)
    with pytest.raises(ValueError, match="review_minutes"):
        servers.start_api(tmp_path, review_minutes=minutes)


def test_resource_hold_uses_fetched_reply_and_loses_only_transport_response():
    from e2e.flows.student_resource_recovery import HoldWriteResponse

    calls = []

    class Request:
        headers = {"idempotency-key": "resource-key"}
        post_data_json = {"action": "request_hint"}

    class Reply:
        status = 200

        def json(self):
            return {"data": {"session": {"hint_level_revealed": 1}}}

    class Route:
        request = Request()

        def fetch(self):
            calls.append("fetch")
            return Reply()

        def abort(self, reason):
            calls.append(("abort", reason))

    hold = HoldWriteResponse()
    hold(Route())
    assert calls == ["fetch"] and hold.result["session"]["hint_level_revealed"] == 1
    hold.lose()
    assert calls == ["fetch", ("abort", "connectionclosed")]


@pytest.mark.parametrize(
    "diagnostic,expected",
    [
        ({"heading_count": 1, "named_nodes": [{"visible": True}, {"visible": True}]}, 1),
        ({"heading_count": 2, "named_nodes": [{"visible": True}]}, 2),
        ({"heading_count": 0, "named_nodes": [{"visible": True}, {"visible": False}]}, 1),
        ({"heading_count": 0, "named_nodes": [{"visible": True}, {"visible": True}]}, 2),
    ],
)
def test_resource_hint_count_uses_actual_semantics_and_keeps_real_duplicates(diagnostic, expected):
    from e2e.flows.student_resource_recovery import rendered_title_count

    assert rendered_title_count(diagnostic) == expected


@pytest.mark.parametrize(
    "texts,expected",
    [
        (["提示 第 1/3 层\n审核内容\n正文"], 1),
        (["提示 第 1/3 层\n审核内容", "提示 第 1/3 层\n正文"], 2),
        (["提示 第 1/3 层\n正文\n提示 第 1/3 层\n正文"], 2),
        (["正文引用了提示 第 1/3 层", "提示 第 2/3 层"], 0),
    ],
)
def test_resource_hint_counts_exact_title_lines_inside_flutter_merged_card(texts, expected):
    from e2e.flows.student_resource_recovery import rendered_title_count

    diagnostic = {
        "title": "提示 第 1/3 层",
        "heading_count": 0,
        "named_nodes": [],
        "semantic_texts": texts,
    }
    assert rendered_title_count(diagnostic) == expected


def test_resource_recovery_storage_filter_is_owner_question_and_resource_scoped():
    from e2e.flows.student_resource_recovery import recovery_storage

    values = {
        "flutter.auth.token": "SECRET",
        "flutter.auth.userId": "owner",
        "flutter.u/owner/profile": "PRIVATE_PROFILE",
        "flutter.u/other/draft-bundle/q": "FOREIGN",
        "flutter.u/owner/draft-bundle/other-q": "OTHER_QUESTION",
        "flutter.u/owner/draft-bundle/q": "RAW_BUNDLE",
        "flutter.u/owner/resource-journal/session/S": "RAW_SESSION",
        "flutter.u/owner/resource-journal/review/R": "RAW_REVIEW",
        "flutter.u/owner/resource-journal/session/other-S": "OTHER_SESSION",
        "flutter.u/owner/draft/q/attempt/A": "RAW_DRAFT",
        "flutter.u/owner/question/q/attempt/A": "RAW_CONTEXT",
    }
    selected = recovery_storage(values, "owner", "q", "S", "R")
    assert set(selected.values()) == {
        "RAW_BUNDLE",
        "RAW_SESSION",
        "RAW_REVIEW",
        "RAW_DRAFT",
        "RAW_CONTEXT",
    }
    assert values["flutter.auth.token"] == "SECRET"


@pytest.mark.parametrize(
    "wire_id,last_id,stage,expected",
    [
        ("B", "C", 1, True),
        ("C", "C", 1, True),
        ("other", "C", 1, False),
        ("B", "B", 1, False),
        ("C", "C", 0, False),
    ],
)
def test_review_browser_accepts_current_draft_wire_only_when_real_record_uses_first_submission(
    wire_id, last_id, stage, expected
):
    from e2e.flows.student_resource_recovery import review_records_first_submission

    assert (
        review_records_first_submission(
            [("key", {"attempt_id": wire_id})], {"last_attempt_id": last_id}, stage, "C", "B"
        )
        is expected
    )


def test_review_diagnostics_are_read_only_and_save_three_real_get_results(monkeypatch, tmp_path):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from e2e.flows import student_resource_recovery as flow

    monkeypatch.setattr(flow, "stored", lambda page, key: "owner" if key == "auth.userId" else None)
    monkeypatch.setattr(
        flow,
        "stored_all",
        lambda page: {"flutter.auth.token": "SECRET", "flutter.u/owner/draft-bundle/q": "RAW"},
    )
    monkeypatch.setattr(flow, "all_text", lambda page: "所选草稿已经提交，请重新选择")

    class ReadApi:
        def __init__(self):
            self.calls = []

        def get(self, path):
            self.calls.append(path)
            return {"from": path}

    api = ReadApi()
    path = flow.review_recovery_evidence(
        SimpleNamespace(out_dir=tmp_path), None, api, "q", "S", "A", "R"
    )
    diagnostic = json.loads(Path(path).read_text(encoding="utf-8"))
    assert api.calls == ["/sessions/S", "/attempts/A", "/reviews/R/state"]
    assert all(
        item["status"] == 200 and item["data"]["from"] == item["path"]
        for item in diagnostic["responses"]
    )
    assert diagnostic["storage"] == {"flutter.u/owner/draft-bundle/q": "RAW"}
    assert "SECRET" not in json.dumps(diagnostic)
    assert "所选草稿已经提交" in diagnostic["rendered_text"]
