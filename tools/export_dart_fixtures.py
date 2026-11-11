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
        assert response.status_code == expect, f"{name}: {response.status_code} {response.text}"
        body = response.json()
        url_path = API_PREFIX + path
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

            rec("profile_empty", student, "GET", "/profile")
            rec("progress_empty", fresh, "GET", "/progress/summary")
            rec(
                "profile_saved",
                student,
                "PUT",
                "/profile",
                json={
                    "region_code": "CN-51",
                    "grade": "G12",
                    "subjects": ["math", "physics", "chemistry"],
                },
            )
            rec("tasks_today", student, "GET", "/tasks/today")
            rec("questions_page", student, "GET", "/questions", params={"limit": 5})
            rec(
                "question_single_choice", student, "GET", f"/questions/{qid('math-mono-quadratic')}"
            )
            rec("question_multiple_choice", student, "GET", f"/questions/{qid('math-mono-judge')}")
            rec("question_fill", student, "GET", f"/questions/{qid('phys-incline-accel')}")

            # 主线：一道有提示、图解、快速解法的单选题，答错
            session = rec(
                "session_created",
                student,
                "POST",
                "/sessions",
                expect=201,
                json={"question_id": qid("math-mono-quadratic"), "origin": "task"},
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
            rec("tutor_visual", student, "POST", nxt, json={"action": "request_visual"})
            rec(
                "submit_incorrect",
                student,
                "POST",
                f"/attempts/{aid}/submit",
                json={"answer": _choice("A")},
            )
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
            rec("tasks_today_next_day", student, "GET", "/tasks/today")

            # 错误
            rec("error_not_implemented", student, "POST", "/scans", expect=501, json={})
            rec("error_unauthenticated", ApiClient(raw), "GET", "/profile", expect=401)
            rec(
                "error_validation",
                student,
                "PUT",
                "/profile",
                expect=422,
                json={"region_code": "CN-11", "subjects": ["math"]},
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
