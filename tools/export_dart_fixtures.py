"""导出真实响应样例，供 Dart 契约包与 Flutter 端的测试共用。

    uv run python tools/export_dart_fixtures.py

在进程内启动后端（临时 SQLite、固定时钟、样题种子），走一遍主流程，把每个响应写成
packages/contracts/dart/test/fixtures/<name>.json：

    {"name", "method", "path", "status", "schema", "value", "body"}

`schema` 是响应里这份数据对应的契约类型名，`value` 是要解析成该类型的那部分（成功响应取 data，
错误响应取整个信封），`body` 是完整响应体。每个响应在写出之前都已按 contracts/openapi.yaml 校验。
样例里的 ID 每次导出都会变；tests/contract/test_dart_fixtures.py 只校验它们仍然符合契约。
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for sub in ("services/api", "services/ai_gateway", "tests"):
    sys.path.insert(0, str(REPO_ROOT / sub))

OUTPUT_DIR = REPO_ROOT / "packages" / "contracts" / "dart" / "test" / "fixtures"
API_PREFIX = "/api/v1"

STROKES = {
    "version": 1,
    "pages": [
        {
            "width": 800,
            "height": 1100,
            "strokes": [
                {"color": "#1A1A1A", "width": 2.5, "points": [10, 20, 0, 0.5, 14, 26, 16, 0.6]}
            ],
        }
    ],
}


def _schema_of(method: str, path: str, status: int) -> tuple[str, bool]:
    """返回 (契约类型名, 是否包在 data 里)。"""
    from support.contract import find_operation, resolve

    _, operation = find_operation(method, path)
    schema = resolve(operation["responses"][str(status)])["content"]["application/json"]["schema"]
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[1], False
    return schema["properties"]["data"]["$ref"].rsplit("/", 1)[1], True


class Recorder:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.count = 0

    def __call__(
        self, name: str, api: Any, method: str, path: str, *, expect: int = 200, **kwargs: Any
    ) -> Any:
        """发请求（客户端会按契约校验响应）、断言状态码、写样例，返回 data（错误时返回 error）。"""
        response = api.request(method, path, **kwargs)
        return self.record_response(name, response, method, path, expect=expect)

    def record_response(
        self, name: str, response: Any, method: str, path: str, *, expect: int
    ) -> Any:
        """同样接收AsyncClient真实ASGI传输返回的响应，不构造或伪造响应内容。"""
        from support.contract import validate_response

        assert response.status_code == expect, f"{name}: {response.status_code} {response.text}"
        body = response.json()
        url_path = API_PREFIX + path
        assert response.headers.get("x-request-id")
        validate_response(method, url_path, expect, body)
        schema, wrapped = _schema_of(method, url_path, expect)
        fixture = {
            "name": name,
            "method": method,
            "path": url_path,
            "status": expect,
            "schema": schema,
            "value": body["data"] if wrapped else body,
            "body": body,
        }
        target = self.directory / f"{name}.json"
        target.write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.count += 1
        return body["data"] if wrapped else body["error"]


def _choice(*keys: str) -> dict[str, Any]:
    return {"selected_options": list(keys)}


def _blank(value: str) -> dict[str, Any]:
    return {"blanks": [{"key": "b1", "value": value}]}


def _onboard(rec: Recorder, raw: Any, name_prefix: str = "") -> Any:
    from support.api import ApiClient

    anon = ApiClient(raw)
    if not name_prefix:
        rec("health", anon, "GET", "/health", auth=False)
        rec("launch_config", anon, "GET", "/meta/launch-config", auth=False)
        identity = rec(
            "local_identity",
            anon,
            "POST",
            "/dev/local-identities",
            expect=201,
            auth=False,
            key=False,
        )
    else:
        identity = anon.data("POST", "/dev/local-identities", expect=201, auth=False, key=False)
    return ApiClient(raw, token=identity["access_token"], user_id=identity["user_id"])


def export(directory: Path = OUTPUT_DIR) -> int:
    from starlette.testclient import TestClient

    from support.api import LOOPBACK, ApiClient
    from support.clock import FakeClock
    from support.gateway_fakes import ScriptedProvider, unavailable
    from support.seeds import qid
    from tutor_api.main import create_app
    from tutor_api.services.document_import_worker import process_next
    from tutor_api.settings import Settings

    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.json"):
        stale.unlink()
    rec = Recorder(directory)

    with tempfile.TemporaryDirectory() as tmp:

        def settings_for(name: str) -> Settings:
            return Settings(
                env="local",
                database_url=f"sqlite:///{(Path(tmp) / name).as_posix()}",
                local_identity_mock=True,
                seed_sample_content=True,
                pseudonym_secret="fixtures-only",
            )

        clock = FakeClock()
        app = create_app(settings_for("main.sqlite3"), clock=clock.now)
        with TestClient(app, client=LOOPBACK) as raw:
            student = _onboard(rec, raw)
            fresh = _onboard(rec, raw, "x")

            identity = ApiClient(raw).data(
                "POST",
                "/dev/local-identities",
                params={"role": "reviewer"},
                expect=201,
                key=False,
            )
            reviewer = ApiClient(raw, token=identity["access_token"], user_id=identity["user_id"])
            example = json.loads(
                (REPO_ROOT / "apps/admin_web/public/examples/question-import.json").read_text(
                    encoding="utf-8"
                )
            )
            imported_draft = rec(
                "admin_imported_draft",
                reviewer,
                "POST",
                "/admin/question-imports",
                expect=201,
                json=example,
            )
            other_identity = ApiClient(raw).data(
                "POST", "/dev/local-identities", params={"role": "reviewer"}, expect=201, key=False
            )
            other_reviewer = ApiClient(
                raw, token=other_identity["access_token"], user_id=other_identity["user_id"]
            )
            rec(
                "admin_batch_review",
                other_reviewer,
                "POST",
                "/admin/question-reviews/batch",
                json={
                    "items": [
                        {
                            "expected_review_revision": 1,
                            "question_id": imported_draft["id"],
                            "expected_version": 1,
                            "decision": "approve",
                            "confirmed": True,
                        },
                        {
                            "expected_review_revision": 1,
                            "question_id": qid("math-mono-quadratic"),
                            "expected_version": 1,
                            "decision": "approve",
                            "confirmed": True,
                        },
                    ]
                },
            )
            import hashlib

            from support.documents import png_image
            from tutor_api.blob_store import FilesystemBlobStore

            app.state.media_store = FilesystemBlobStore(
                Path(tmp) / "media", max_bytes=app.state.settings.media_max_bytes
            )
            media_bytes = png_image()
            school_upload = rec(
                "school_material_upload",
                student,
                "POST",
                "/school-materials/uploads",
                expect=201,
                json={
                    "mime": "image/png",
                    "size_bytes": len(media_bytes),
                    "sha256": hashlib.sha256(media_bytes).hexdigest(),
                },
            )
            rec(
                "school_material_source",
                student,
                "PUT",
                f"/school-materials/uploads/{school_upload['media_id']}/content",
                json={"content_base64": base64.b64encode(media_bytes).decode()},
            )
            school_job = rec(
                "school_material_submitted",
                student,
                "POST",
                "/school-materials",
                expect=202,
                json={"media_id": school_upload["media_id"]},
            )
            from tutor_api.services.school_material_worker import process_one

            assert process_one(
                app.state.session_factory, clock.now, app.state.settings, app.state.media_store
            )
            rec(
                "school_material_pages",
                student,
                "GET",
                f"/school-materials/{school_job['id']}/pages",
            )
            rec(
                "school_material_preview",
                student,
                "GET",
                f"/school-materials/{school_job['id']}/pages/1/preview",
            )
            rec(
                "school_material_corrected",
                student,
                "PUT",
                f"/school-materials/{school_job['id']}/pages/1/correction",
                json={"expected_revision": 0, "text": "自编校正样例"},
            )
            school_candidates = rec(
                "school_material_candidates",
                student,
                "GET",
                f"/school-materials/{school_job['id']}/candidates",
            )
            rec(
                "school_material_confirmed",
                student,
                "PUT",
                f"/school-materials/{school_job['id']}/confirmation",
                json={
                    "source_revision": school_candidates["source_revision"],
                    "items": [{"text": "自编确认样例", "pages": [1]}],
                },
            )
            app.state.settings.scan_mock_enabled = True
            scan_bytes = png_image()
            scan_upload = rec(
                "scan_upload",
                student,
                "POST",
                "/scans/uploads",
                expect=201,
                json={
                    "purpose": "scan",
                    "mime": "image/png",
                    "size_bytes": len(scan_bytes),
                    "sha256": hashlib.sha256(scan_bytes).hexdigest(),
                },
            )
            rec(
                "scan_content",
                student,
                "PUT",
                f"/scans/uploads/{scan_upload['media_id']}/content",
                json={"content_base64": base64.b64encode(scan_bytes).decode()},
            )
            scan = rec(
                "scan_candidate",
                student,
                "POST",
                "/scans",
                expect=202,
                json={"media_id": scan_upload["media_id"]},
            )
            rec("scan_get", student, "GET", f"/scans/{scan['id']}")
            rec(
                "scan_confirm",
                student,
                "POST",
                f"/scans/{scan['id']}/confirm",
                json={"stem_text": "手工录入：未匹配样题", "expressions": []},
            )
            app.state.settings.scan_mock_enabled = False
            rec("student_media_export", student, "GET", "/profile/media-export")
            media_sha = hashlib.sha256(media_bytes).hexdigest()
            from tutor_api.blob_store import BlobStorageUnavailable, BlobWriteConflict

            reserve = app.state.media_store.reserve
            try:
                for error_type, status in ((BlobStorageUnavailable, 503), (BlobWriteConflict, 409)):

                    def fail_reserve(*args, _error=error_type, **kwargs):
                        raise _error("private storage diagnostic")

                    app.state.media_store.reserve = fail_reserve
                    rec(
                        f"error_storage_{status}",
                        reviewer,
                        "POST",
                        "/media/uploads",
                        expect=status,
                        json={
                            "purpose": "question_attachment",
                            "mime": "image/png",
                            "size_bytes": len(media_bytes),
                            "sha256": media_sha,
                        },
                    )
            finally:
                app.state.media_store.reserve = reserve
            media_upload = rec(
                "media_upload",
                reviewer,
                "POST",
                "/media/uploads",
                expect=201,
                json={
                    "purpose": "question_attachment",
                    "mime": "image/png",
                    "size_bytes": len(media_bytes),
                    "sha256": media_sha,
                },
            )
            media_id = media_upload["media_id"]
            rec(
                "media_staged",
                reviewer,
                "PUT",
                f"/media/{media_id}/content",
                json={"content_base64": base64.b64encode(media_bytes).decode()},
            )
            rec(
                "media_confirmed",
                reviewer,
                "POST",
                f"/media/{media_id}/confirm",
                json={"sha256": media_sha},
            )
            rec("media_content", reviewer, "GET", f"/media/{media_id}/content")
            attached_payload = json.loads(json.dumps(example))
            attached_payload["question"]["content"]["attachments"] = [
                {"kind": "image", "media_id": media_id, "alt": "自编低风险题面图示"}
            ]
            image_question = rec(
                "image_question_draft",
                reviewer,
                "POST",
                "/admin/question-imports",
                expect=201,
                json=attached_payload,
            )
            rec(
                "image_question_preview",
                other_reviewer,
                "GET",
                f"/admin/questions/{image_question['id']}/media/{media_id}/content",
            )
            rec(
                "image_review_declaration",
                other_reviewer,
                "POST",
                f"/admin/questions/{image_question['id']}/media/{media_id}/review-confirmations",
                json={"expected_version": 1, "sha256": media_sha, "confirmed": True},
            )
            rec(
                "image_question_reviewed",
                other_reviewer,
                "POST",
                f"/admin/questions/{image_question['id']}/review",
                json={"expected_review_revision": 1, "expected_version": 1, "decision": "approve"},
            )
            rec(
                "image_question_published",
                other_reviewer,
                "POST",
                f"/admin/questions/{image_question['id']}/review",
                json={
                    "expected_review_revision": (1) + 1,
                    "expected_version": 1,
                    "decision": "publish",
                },
            )
            rec(
                "published_question_media",
                student,
                "GET",
                f"/questions/{image_question['id']}/media/{media_id}/content",
            )

            rec("media_deleted", reviewer, "POST", f"/media/{media_id}/delete", json={})
            import_options = rec(
                "document_import_options", reviewer, "GET", "/admin/import-options"
            )
            import_job = rec(
                "document_import_created",
                reviewer,
                "POST",
                "/admin/import-jobs",
                expect=201,
                json={
                    "title": "自编工程样题导入",
                    "creation_deadline": import_options["creation_deadline"],
                    "defaults": {
                        "subject": example["subject"],
                        "answer_mode": example["answer_mode"],
                        "source": example["source"],
                    },
                },
            )
            uploaded = rec(
                "document_import_uploaded",
                reviewer,
                "POST",
                f"/admin/import-jobs/{import_job['id']}/files",
                expect=201,
                json={
                    "expected_revision": 1,
                    "filename": "sample.json",
                    "content_base64": base64.b64encode(
                        json.dumps(example, ensure_ascii=False).encode()
                    ).decode(),
                },
            )
            rec("document_import_detail", reviewer, "GET", f"/admin/import-jobs/{import_job['id']}")
            rec("document_import_page", reviewer, "GET", "/admin/import-jobs")
            rec(
                "document_import_original",
                reviewer,
                "GET",
                f"/admin/import-jobs/{import_job['id']}/files/{uploaded['file']['id']}/content",
            )
            rec(
                "document_import_queued",
                reviewer,
                "POST",
                f"/admin/import-jobs/{import_job['id']}/process",
                json={"expected_revision": uploaded["job"]["revision"]},
            )
            process_next(app.state.session_factory, app.state.settings, clock.now)
            extracted = rec(
                "document_import_extracted",
                reviewer,
                "GET",
                f"/admin/import-jobs/{import_job['id']}",
            )
            candidate = extracted["candidates"][0]
            editable = {
                key: candidate[key]
                for key in (
                    "id",
                    "title",
                    "text",
                    "locations",
                    "payload",
                    "confirmed",
                )
            }
            editable["confirmed"] = True
            confirmed = rec(
                "document_import_confirmed",
                reviewer,
                "POST",
                f"/admin/import-jobs/{import_job['id']}/candidates",
                json={"expected_revision": extracted["job"]["revision"], "items": [editable]},
            )
            imported = rec(
                "document_import_batch",
                reviewer,
                "POST",
                f"/admin/import-jobs/{import_job['id']}/submit",
                json={
                    "expected_revision": confirmed["job"]["revision"],
                    "candidate_ids": [candidate["id"]],
                },
            )

            imported_id = imported["items"][0]["question_id"]
            formal = rec(
                "document_import_provenance",
                reviewer,
                "GET",
                f"/admin/questions/{imported_id}",
            )
            rec(
                "document_import_derived_provenance",
                reviewer,
                "POST",
                f"/admin/questions/{imported_id}/versions",
                expect=201,
                json={
                    **editable["payload"]["question"],
                    "title": formal["title"] + " derived metadata sample",
                    "expected_version": formal["version"],
                    "expected_review_revision": formal["review_revision"],
                },
            )
            rec(
                "document_import_initial_provenance",
                reviewer,
                "GET",
                f"/admin/questions/{imported_id}/versions/1",
            )

            rec("profile_empty", student, "GET", "/profile")
            rec("progress_empty", fresh, "GET", "/progress/summary")
            rec(
                "profile_saved",
                student,
                "PUT",
                "/profile",
                json={
                    "expected_revision": student.data("GET", "/profile")["revision"],
                    "region_code": "CN-51",
                    "grade": "G12",
                    "subjects": ["math", "physics", "chemistry"],
                },
            )
            rec("tasks_today", student, "GET", "/tasks/today")
            rec("questions_page", student, "GET", "/questions", params={"limit": 5})
            rec("question_topics", student, "GET", "/questions/topics")
            diagnostic_student = _onboard(rec, raw, "diagnostic")
            diagnostic_student.save_profile(
                json={"region_code": "CN-51", "grade": "G10", "subjects": ["math"]}
            )
            rec("diagnostic_empty", diagnostic_student, "GET", "/diagnostics")
            diagnostic = rec(
                "diagnostic_created",
                diagnostic_student,
                "POST",
                "/diagnostics",
                expect=201,
                json={"subject": "math", "expected_revision": 0, "expected_profile_revision": 1},
            )
            diagnostic_id = diagnostic["run"]["id"]
            rec(
                "diagnostic_session",
                diagnostic_student,
                "POST",
                f"/diagnostics/{diagnostic_id}/items/1/session",
                json={"expected_revision": 1},
            )
            rec("diagnostic_progress", diagnostic_student, "GET", f"/diagnostics/{diagnostic_id}")
            rec(
                "diagnostic_abandoned",
                diagnostic_student,
                "POST",
                f"/diagnostics/{diagnostic_id}/abandon",
                json={"expected_revision": 2},
            )
            rec("diagnostic_history", diagnostic_student, "GET", "/diagnostics/history")
            rec("diagnostic_learning_export", diagnostic_student, "GET", "/profile/learning-export")
            rec(
                "question_single_choice", student, "GET", f"/questions/{qid('math-mono-quadratic')}"
            )
            rec("question_multiple_choice", student, "GET", f"/questions/{qid('math-mono-judge')}")
            rec("question_fill", student, "GET", f"/questions/{qid('phys-incline-accel')}")
            rec(
                "error_question_version_conflict",
                student,
                "POST",
                "/sessions",
                expect=409,
                json={
                    "question_id": qid("math-mono-quadratic"),
                    "origin": "task",
                    "expected_question_version": 2,
                },
            )

            # 主线：一道有提示、图解、快速解法的单选题，答错
            session = rec(
                "session_created",
                student,
                "POST",
                "/sessions",
                expect=201,
                json={
                    "question_id": qid("math-mono-quadratic"),
                    "origin": "task",
                    "expected_question_version": 1,
                },
            )
            sid = session["id"]
            attempt = rec(
                "attempt_created",
                student,
                "POST",
                "/attempts",
                expect=201,
                json={"session_id": sid},
            )
            aid = attempt["id"]
            rec(
                "draft_synced",
                student,
                "PUT",
                f"/attempts/{aid}/draft",
                json={"base_revision": 0, "answer": _choice("A"), "strokes": STROKES},
            )
            rec(
                "draft_conflict",
                student,
                "PUT",
                f"/attempts/{aid}/draft",
                expect=409,
                json={"base_revision": 0, "answer": _choice("D")},
            )
            rec(
                "error_submit_draft_revision_conflict",
                student,
                "POST",
                f"/attempts/{aid}/submit",
                expect=409,
                json={"answer": _choice("A"), "expected_draft_revision": 0},
            )
            nxt = f"/tutor/sessions/{sid}/next"
            rec(
                "tutor_standard_needs_confirmation",
                student,
                "POST",
                nxt,
                expect=409,
                json={"action": "request_standard"},
            )
            rec("tutor_hint", student, "POST", nxt, json={"action": "request_hint"})
            rec("tutor_visual_blocked", student, "POST", nxt, json={"action": "request_visual"})
            rec(
                "submit_incorrect",
                student,
                "POST",
                f"/attempts/{aid}/submit",
                json={"answer": _choice("A")},
            )
            rec("tutor_visual", student, "POST", nxt, json={"action": "request_visual"})
            rec("tutor_standard", student, "POST", nxt, json={"action": "request_standard"})
            rec("tutor_fast", student, "POST", nxt, json={"action": "request_fast"})
            rec("tutor_understood", student, "POST", nxt, json={"action": "mark_understood"})
            rec("session_events", student, "GET", f"/sessions/{sid}/events")

            # 判定的另外几种结果
            s2 = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": qid("math-ineq-min"), "origin": "practice"},
            )
            a2 = student.data("POST", "/attempts", expect=201, json={"session_id": s2["id"]})
            rec(
                "submit_correct",
                student,
                "POST",
                f"/attempts/{a2['id']}/submit",
                json={"answer": _blank("4")},
            )
            s3 = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": qid("phys-incline-accel"), "origin": "practice"},
            )
            a3 = student.data("POST", "/attempts", expect=201, json={"session_id": s3["id"]})
            rec(
                "submit_uncertain",
                student,
                "POST",
                f"/attempts/{a3['id']}/submit",
                json={"answer": _blank("500 cm/s²")},
            )
            rec("session_after_submit", student, "GET", f"/sessions/{s3['id']}")

            # 解答题：不自动评分，提交之后对照要点自查
            written_id = qid("math-quadratic-param-written")
            rec("question_written", student, "GET", f"/questions/{written_id}")
            s8 = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": written_id, "origin": "practice"},
            )
            a8 = student.data("POST", "/attempts", expect=201, json={"session_id": s8["id"]})
            written = {
                "parts": [
                    {"key": "1", "text": "对称轴 $x=a$，开口向上，所以 $a\\le 1$。"},
                    {"key": "2", "text": "配方得 $(x-2)^2-1$，最小值 $-1$，最大值 $3$。"},
                ]
            }
            rec(
                "self_check_before_submit",
                student,
                "GET",
                f"/attempts/{a8['id']}/self-check",
                expect=409,
            )
            rec(
                "draft_synced_written",
                student,
                "PUT",
                f"/attempts/{a8['id']}/draft",
                json={"base_revision": 0, "answer": written, "strokes": STROKES},
            )
            rec(
                "submit_written",
                student,
                "POST",
                f"/attempts/{a8['id']}/submit",
                json={"answer": written},
            )
            checklist = rec(
                "self_check_pending", student, "GET", f"/attempts/{a8['id']}/self-check"
            )
            levels = ["done", "partial", "missed"]
            marks = [
                {"point_key": point["key"], "level": levels[index % 3]}
                for index, point in enumerate(checklist["points"])
            ]
            rec(
                "self_check_saved",
                student,
                "PUT",
                f"/attempts/{a8['id']}/self-check",
                json={"marks": marks},
            )

            # "没懂"的三级回退：没有审核文案的题走模型网关（Mock）
            s4 = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": qid("math-mono-quadratic-v1"), "origin": "practice"},
            )
            student.data("POST", "/attempts", expect=201, json={"session_id": s4["id"]})
            n4 = f"/tutor/sessions/{s4['id']}/next"
            rec("tutor_rephrase_model", student, "POST", n4, json={"action": "mark_confused"})
            rec("tutor_confused_ask", student, "POST", n4, json={"action": "mark_confused"})
            rec("tutor_needs_human_help", student, "POST", n4, json={"action": "mark_confused"})

            # 自编工程素材：真实API输出跨语言Unicode/原换行/TeX引用，不能只导空字段。
            reference_example = json.loads(json.dumps(example))
            reference_question = reference_example["question"]
            reference_text = "引用验证条件：甲😀e\u0301\n" + reference_question["content"]["stem"]
            reference_question["content"]["stem"] = reference_text
            reference_question["teaching"]["concept_rephrase"] = None
            reference_span = {
                "block_id": "stem",
                "block_sha256": hashlib.sha256(reference_text.encode("utf-8")).hexdigest(),
                "start": reference_text.index("甲"),
                "end": reference_text.index("甲") + len("甲😀e\u0301\n"),
            }
            reference_question["teaching"]["reference_links"] = [
                {"target_block_id": target, "source_span": reference_span, "independent_safe": True}
                for target in ("hint:1", "rephrase", "solution:standard:step:1")
            ]
            reference_draft = reviewer.data(
                "POST", "/admin/question-imports", expect=201, json=reference_example
            )
            reference_id = reference_draft["id"]
            for decision in ("approve", "publish"):
                reference_draft = other_reviewer.data(
                    "POST",
                    f"/admin/questions/{reference_id}/review",
                    json={
                        "expected_version": reference_draft["version"],
                        "expected_review_revision": reference_draft["review_revision"],
                        "decision": decision,
                    },
                )
            reference_session = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": reference_id, "origin": "practice"},
            )
            student.data(
                "POST", "/attempts", expect=201, json={"session_id": reference_session["id"]}
            )
            reference_next = f"/tutor/sessions/{reference_session['id']}/next"
            for name, action, extra in (
                ("tutor_reference_hint", "request_hint", {}),
                ("tutor_reference_model", "mark_confused", {}),
                ("tutor_reference_standard", "request_standard", {"confirm_end_independent": True}),
            ):
                reference_result = rec(
                    name, student, "POST", reference_next, json={"action": action, **extra}
                )
                emitted = reference_result["events"][0]
                assert emitted["references"][0]["block_text"] == reference_text
                assert emitted["references"][0]["start"] == reference_span["start"]
                assert emitted["references"][0]["end"] == reference_span["end"]
                if action == "mark_confused":
                    assert emitted["meta"]["source"] == "model"

            s5 = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": qid("phys-newton2-force"), "origin": "practice"},
            )
            student.data("POST", "/attempts", expect=201, json={"session_id": s5["id"]})
            rec(
                "tutor_fast_not_applicable",
                student,
                "POST",
                f"/tutor/sessions/{s5['id']}/next",
                json={"action": "request_fast"},
            )

            # 复测：第一个错题到期后做对
            rec("reviews_all", student, "GET", "/reviews/due", params={"scope": "all"})
            clock.advance(days=1)
            due = rec("reviews_due", student, "GET", "/reviews/due")
            item = next(
                entry
                for entry in due["items"]
                if entry["question_id"] == qid("math-mono-quadratic")
            )
            s6 = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={
                    "question_id": qid("math-mono-quadratic"),
                    "origin": "review",
                    "review_item_id": item["id"],
                },
            )
            a6 = student.data("POST", "/attempts", expect=201, json={"session_id": s6["id"]})
            student.data("POST", f"/attempts/{a6['id']}/submit", json={"answer": _choice("B")})
            rec(
                "review_completed",
                student,
                "POST",
                f"/reviews/{item['id']}/complete",
                json={"attempt_id": a6["id"]},
            )
            rec("progress_summary", student, "GET", "/progress/summary")
            rec("review_current_state", student, "GET", f"/reviews/{item['id']}/state")
            rec(
                "error_review_already_completed",
                student,
                "POST",
                f"/reviews/{item['id']}/complete",
                json={"attempt_id": a6["id"]},
                expect=409,
            )
            rec("tasks_today_next_day", student, "GET", "/tasks/today")

            # 家长：学生明确授权（生成邀请码）→ 家长输入 → 看周报 → 学生撤销
            # 本地身份 Mock 的家长角色：监护授权方案（Q-03）没有冻结，这不是真实的家长账号
            parent_identity = ApiClient(raw).data(
                "POST",
                "/dev/local-identities",
                expect=201,
                auth=False,
                key=False,
                params={"role": "parent"},
            )
            parent = ApiClient(
                raw,
                token=parent_identity["access_token"],
                user_id=parent_identity["user_id"],
            )
            rec("parent_links_none", student, "GET", "/me/parent-links")
            rec("parent_students_none", parent, "GET", "/parents/students")
            invite = rec(
                "parent_invite",
                student,
                "POST",
                "/me/parent-invites",
                json={
                    "expected_parent_invite_revision": student.data("GET", "/me/parent-links")[
                        "parent_invite_revision"
                    ]
                },
                expect=201,
            )
            rec("parent_links_pending", student, "GET", "/me/parent-links")
            rec(
                "error_invite_invalid",
                parent,
                "POST",
                "/parents/links",
                expect=404,
                json={"code": "ZZZZZZZZZZ"},
            )
            rec(
                "parent_link_created",
                parent,
                "POST",
                "/parents/links",
                expect=201,
                json={"code": invite["code"]},
            )
            rec("parent_students", parent, "GET", "/parents/students")
            links = rec("parent_links", student, "GET", "/me/parent-links")
            rec("parent_weekly", parent, "GET", f"/parents/students/{student.user_id}/weekly")
            rec(
                "parent_weekly_last_week",
                parent,
                "GET",
                f"/parents/students/{student.user_id}/weekly",
                params={"week_start": "2026-11-02"},
            )
            rec(
                "error_weekly_not_a_monday",
                parent,
                "GET",
                f"/parents/students/{student.user_id}/weekly",
                expect=422,
                params={"week_start": "2026-11-10"},
            )
            rec(
                "error_weekly_not_linked",
                parent,
                "GET",
                f"/parents/students/{fresh.user_id}/weekly",
                expect=404,
            )
            rec(
                "parent_link_revoked",
                student,
                "POST",
                f"/me/parent-links/{links['links'][0]['id']}/revoke",
                json={
                    "expected_authorization_revision": links["links"][0]["authorization_revision"]
                },
            )
            rec(
                "error_weekly_revoked",
                parent,
                "GET",
                f"/parents/students/{student.user_id}/weekly",
                expect=404,
            )

            # 实验题：带数据表和安全提示，不自动评分，提交之后对照要点和参考数据自查。
            # 放在家长周报之后导出：它们不能改变前面那些样例里的计数
            tape_id = qid("phys-tape-experiment")
            rec("question_experiment", student, "GET", f"/questions/{tape_id}")
            rec(
                "question_experiment_titration",
                student,
                "GET",
                f"/questions/{qid('chem-titration-experiment')}",
            )
            s9 = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": tape_id, "origin": "practice"},
            )
            a9 = student.data("POST", "/attempts", expect=201, json={"session_id": s9["id"]})
            experiment = {
                "cells": [
                    {"table": "t1", "row": "r1", "col": "v", "value": "0.400"},
                    {"table": "t1", "row": "r2", "col": "v", "value": "0.600"},
                    {"table": "t1", "row": "r3", "col": "v", "value": "0.800"},
                    {"table": "t1", "row": "r4", "col": "v", "value": "1.00"},
                    {"table": "t2", "row": "r1", "col": "val", "value": "2.00"},
                ],
                "parts": [
                    {"key": "1", "text": "$T=0.10\\ \\text{s}$，平均速度等于距离除以 $T$。"},
                    {"key": "2", "text": "用逐差法，$a=2.00\\ \\text{m/s}^2$。"},
                ],
            }
            rec(
                "self_check_experiment_before_submit",
                student,
                "GET",
                f"/attempts/{a9['id']}/self-check",
                expect=409,
            )
            rec(
                "draft_synced_experiment",
                student,
                "PUT",
                f"/attempts/{a9['id']}/draft",
                json={"base_revision": 0, "answer": experiment, "strokes": STROKES},
            )
            rec(
                "submit_experiment",
                student,
                "POST",
                f"/attempts/{a9['id']}/submit",
                json={"answer": experiment},
            )
            checklist = rec(
                "self_check_experiment_pending", student, "GET", f"/attempts/{a9['id']}/self-check"
            )
            levels = ["done", "partial", "missed"]
            marks = [
                {"point_key": point["key"], "level": levels[index % 3]}
                for index, point in enumerate(checklist["points"])
            ]
            rec(
                "self_check_experiment_saved",
                student,
                "PUT",
                f"/attempts/{a9['id']}/self-check",
                json={"marks": marks},
            )

            # 证明题：有已知和求证，学生把证明写成一步一步（每步带依据），不自动评分，
            # 提交之后对照参考证明和要点自查。同样放在最后导出，不改变前面样例里的计数
            mono_id = qid("math-mono-def-proof")
            rec("question_proof", student, "GET", f"/questions/{mono_id}")
            rec(
                "question_proof_physics",
                student,
                "GET",
                f"/questions/{qid('phys-work-energy-proof')}",
            )
            s10 = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": mono_id, "origin": "practice"},
            )
            a10 = student.data("POST", "/attempts", expect=201, json={"session_id": s10["id"]})
            proof = {
                "steps": [
                    {
                        "text": "任取 $x_1,x_2\\in[1,+\\infty)$，且 $x_1<x_2$。",
                        "reason": "单调性的定义",
                    },
                    {
                        "text": "$f(x_1)-f(x_2)=\\dfrac{(x_1-x_2)(x_1x_2-1)}{x_1x_2}$。",
                        "reason": "作差，通分，提公因式",
                    },
                    {
                        "text": "$x_1-x_2<0$，$x_1x_2>1$，所以 $f(x_1)<f(x_2)$，$f(x)$ 在 $[1,+\\infty)$ 上单调递增。",
                        "reason": "",
                    },
                ]
            }
            rec(
                "self_check_proof_before_submit",
                student,
                "GET",
                f"/attempts/{a10['id']}/self-check",
                expect=409,
            )
            rec(
                "draft_synced_proof",
                student,
                "PUT",
                f"/attempts/{a10['id']}/draft",
                json={"base_revision": 0, "answer": proof, "strokes": STROKES},
            )
            rec(
                "submit_proof",
                student,
                "POST",
                f"/attempts/{a10['id']}/submit",
                json={"answer": proof},
            )
            checklist = rec(
                "self_check_proof_pending", student, "GET", f"/attempts/{a10['id']}/self-check"
            )
            marks = [
                {"point_key": point["key"], "level": levels[index % 3]}
                for index, point in enumerate(checklist["points"])
            ]
            rec(
                "self_check_proof_saved",
                student,
                "PUT",
                f"/attempts/{a10['id']}/self-check",
                json={"marks": marks},
            )

            # SUBJECT302/303: complete textual givens, diagrams only after phase gate.
            for diagram_name, diagram_key, diagram_answer in (
                ("chemical_process", "chem-process-reading", _choice("B")),
                (
                    "circle_schematic",
                    "math-circle-radius-proof",
                    {"steps": [{"text": "我使用题设圆方程进行比较。", "reason": "两点间距离公式"}]},
                ),
                (
                    "triangle_schematic",
                    "math-triangle-coordinate-proof",
                    {"steps": [{"text": "按给定坐标比较三边。", "reason": "两点间距离公式"}]},
                ),
            ):
                rec(f"question_{diagram_name}", student, "GET", f"/questions/{qid(diagram_key)}")
                diagram_session = student.data(
                    "POST",
                    "/sessions",
                    expect=201,
                    json={"question_id": qid(diagram_key), "origin": "practice"},
                )
                diagram_attempt = student.data(
                    "POST", "/attempts", expect=201, json={"session_id": diagram_session["id"]}
                )
                diagram_next = f"/tutor/sessions/{diagram_session['id']}/next"
                rec(
                    f"tutor_{diagram_name}_blocked",
                    student,
                    "POST",
                    diagram_next,
                    json={"action": "request_visual", "confirm_end_independent": True},
                )
                rec(
                    f"submit_{diagram_name}",
                    student,
                    "POST",
                    f"/attempts/{diagram_attempt['id']}/submit",
                    json={"answer": diagram_answer},
                )
                rec(
                    f"tutor_{diagram_name}",
                    student,
                    "POST",
                    diagram_next,
                    json={"action": "request_visual"},
                )

            # Independent copies share a session but keep both draft payloads.
            copy_session = student.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": qid("math-ineq-min"), "origin": "practice"},
            )
            copy_source = student.data(
                "POST", "/attempts", expect=201, json={"session_id": copy_session["id"]}
            )
            student.data(
                "PUT",
                f"/attempts/{copy_source['id']}/draft",
                json={"base_revision": 0, "answer": _blank("云端草稿")},
            )
            copy_payload = {"source_revision": 1, "answer": _blank("本机草稿"), "strokes": STROKES}
            copy_path = f"/attempts/{copy_source['id']}/copies"
            saved_copy = rec(
                "draft_copied",
                student,
                "POST",
                copy_path,
                expect=201,
                json=copy_payload,
                key="fixture-draft-copy-once",
            )
            rec(
                "draft_copy_replayed",
                student,
                "POST",
                copy_path,
                expect=201,
                json=copy_payload,
                key="fixture-draft-copy-once",
            )
            refs = rec(
                "question_drafts",
                student,
                "GET",
                f"/questions/{qid('math-ineq-min')}/drafts",
                params={"limit": 1},
            )
            rec(
                "question_drafts_next",
                student,
                "GET",
                f"/questions/{qid('math-ineq-min')}/drafts",
                params={"limit": 1, "cursor": refs["next_cursor"]},
            )
            rec(
                "session_pinned_question",
                student,
                "GET",
                f"/sessions/{copy_session['id']}/question",
            )
            rec("draft_copy_attempt", student, "GET", f"/attempts/{saved_copy['attempt']['id']}")
            rec("draft_copy_body", student, "GET", f"/attempts/{saved_copy['attempt']['id']}/draft")
            rec(
                "draft_copy_source_conflict",
                student,
                "POST",
                copy_path,
                expect=409,
                json={**copy_payload, "source_revision": 0},
            )
            rec(
                "submit_copy_first",
                student,
                "POST",
                f"/attempts/{saved_copy['attempt']['id']}/submit",
                json={"answer": _blank("4")},
            )
            rec(
                "tutor_copy_keep_source",
                student,
                "POST",
                f"/tutor/sessions/{copy_session['id']}/next",
                json={"action": "mark_understood"},
            )

            # 错误
            rec("error_not_implemented", student, "POST", "/scans", expect=501, json={})
            rec("error_unauthenticated", ApiClient(raw), "GET", "/profile", expect=401)
            rec(
                "error_validation",
                student,
                "PUT",
                "/profile",
                expect=422,
                json={
                    "expected_revision": student.data("GET", "/profile")["revision"],
                    "region_code": "CN-11",
                    "subjects": ["math"],
                },
            )
            rec(
                "error_not_found",
                student,
                "GET",
                f"/sessions/{'0' * 8}-0000-4000-8000-{'0' * 12}",
                expect=404,
            )
            body = {"question_id": qid("math-ineq-min"), "origin": "practice"}
            student.data("POST", "/sessions", expect=201, json=body, key="fixture-key-0001")
            rec(
                "error_idempotency_conflict",
                student,
                "POST",
                "/sessions",
                expect=409,
                json={"question_id": qid("math-ineq-rect"), "origin": "practice"},
                key="fixture-key-0001",
            )
            rec(
                "error_missing_idempotency_key",
                student,
                "POST",
                "/sessions",
                expect=400,
                json=body,
                key=False,
            )

            rec("student_learning_export", student, "GET", "/profile/learning-export")

        # 模型不可用：另起一个应用，把 Mock 适配器换成总是失败的
        broken = create_app(
            settings_for("broken.sqlite3"),
            clock=clock.now,
            gateway_adapters={"mock": ScriptedProvider(unavailable())},
        )
        with TestClient(broken, client=LOOPBACK) as raw:
            learner = _onboard(rec, raw, "x")
            s7 = learner.data(
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": qid("math-mono-quadratic-v1"), "origin": "practice"},
            )
            learner.data("POST", "/attempts", expect=201, json={"session_id": s7["id"]})
            rec(
                "tutor_fallback",
                learner,
                "POST",
                f"/tutor/sessions/{s7['id']}/next",
                json={"action": "mark_confused"},
            )

        http_app = create_app(
            settings_for("http_limits.sqlite3").model_copy(
                update={
                    "http_limits_enabled": True,
                    "http_max_body_bytes": 1024,
                    "http_limit_per_peer": 1,
                }
            ),
            clock=clock.now,
        )
        with TestClient(http_app, client=LOOPBACK) as raw:
            api = ApiClient(raw)
            rec(
                "error_http_payload_large",
                api,
                "PUT",
                "/profile",
                expect=413,
                content=b" " * 2048,
                auth=False,
            )
            rec("error_http_rate_limited", api, "GET", "/profile", expect=429, auth=False)

        import asyncio

        import httpx

        timeout_app = create_app(
            settings_for("http_timeout.sqlite3").model_copy(
                update={
                    "http_limits_enabled": True,
                    "http_body_timeout_seconds": 0.005,
                }
            ),
            clock=clock.now,
        )

        async def timeout_response():
            async def body():
                await asyncio.sleep(0.05)
                yield b"{}"

            async with (
                timeout_app.router.lifespan_context(timeout_app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=timeout_app), base_url="http://127.0.0.1:8000"
                ) as api,
            ):
                return await api.put("/api/v1/profile", content=body())

        rec.record_response(
            "error_http_body_timeout",
            asyncio.run(timeout_response()),
            "PUT",
            "/profile",
            expect=408,
        )

    return rec.count


MATH_SNIPPETS_PATH = (
    REPO_ROOT / "apps" / "flutter_student" / "test" / "fixtures" / "math_snippets.json"
)


def export_math_snippets(path: Path = MATH_SNIPPETS_PATH) -> int:
    """导出样题里出现的全部 `$...$` 公式片段，让 Flutter 端检查渲染器都能解析。"""
    import re

    from tutor_api.services.content_seed import load_seed

    def strings(node: Any):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for value in node.values():
                yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)

    snippets: set[str] = set()
    bundle = load_seed()
    for question in bundle.questions:
        for text in strings(question):
            snippets.update(re.findall(r"\$([^$]+)\$", text))
    for node in bundle.nodes:
        for text in strings(node):
            snippets.update(re.findall(r"\$([^$]+)\$", text))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sorted(snippets), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return len(snippets)


def main() -> None:
    count = export()
    print(f"已导出 {count} 个样例到 {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    formulas = export_math_snippets()
    print(f"已导出 {formulas} 个公式片段到 {MATH_SNIPPETS_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
