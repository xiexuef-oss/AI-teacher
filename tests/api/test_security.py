"""权限隔离（PRD §3、docs/02 §4、docs/09 验收）。

权限只来自 token。别人的资源一律 404，并且与"根本不存在"的响应完全一样，无法用来探测 ID。
"""

from __future__ import annotations

import re
import uuid

import pytest

from support.contract import iter_operations
from support.flows import begin, blank, choice, solve, tutor
from support.seeds import qid

SECURED = [
    (method.upper(), path)
    for path, method, op in iter_operations()
    if op.get("security") != [] and op["x-implementation-status"] == "implemented"
]


def _fill(template: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), template)


# ---------------------------------------------------------------- 未认证


@pytest.mark.parametrize(("method", "template"), SECURED, ids=[f"{m} {p}" for m, p in SECURED])
def test_every_secured_operation_rejects_requests_without_a_token(anon, method, template):
    body = {} if method in {"POST", "PUT"} else None
    error = anon.error(method, _fill(template), expect=401, json=body, auth=False)
    assert error["code"] == "unauthenticated"


@pytest.mark.parametrize(("method", "template"), SECURED, ids=[f"{m} {p}" for m, p in SECURED])
def test_every_secured_operation_rejects_a_forged_token(anon, method, template):
    body = {} if method in {"POST", "PUT"} else None
    headers = {"Authorization": "Bearer " + "A" * 43}
    assert (
        anon.error(method, _fill(template), expect=401, json=body, headers=headers)["code"]
        == "unauthenticated"
    )


def test_unauthenticated_response_does_not_depend_on_the_resource_existing(onboarded, anon):
    session, _ = begin(onboarded, "math-ineq-min")

    real = anon.error("GET", f"/sessions/{session['id']}", expect=401, auth=False)
    fake = anon.error("GET", f"/sessions/{uuid.uuid4()}", expect=401, auth=False)

    assert {k: v for k, v in real.items() if k != "request_id"} == {
        k: v for k, v in fake.items() if k != "request_id"
    }


# ---------------------------------------------------------------- 跨账号访问


@pytest.fixture
def alice_and_bob(new_student, clock):
    """Alice 有一个进行中的会话、一份已提交的作答和一个到期的复测项；Bob 是另一名学生。"""
    alice, bob = new_student(), new_student()
    open_session, open_attempt = begin(alice, "math-mono-quadratic")
    tutor(alice, open_session["id"], "request_hint")
    done_session, done_attempt, result = solve(alice, "math-ineq-min", blank("5"))
    clock.advance(days=1)
    return {
        "alice": alice,
        "bob": bob,
        "open_session": open_session["id"],
        "open_attempt": open_attempt["id"],
        "done_session": done_session["id"],
        "done_attempt": done_attempt["id"],
        "review": result["review_item"]["id"],
    }


def _foreign_calls(ids: dict) -> list[tuple[str, str, dict | None]]:
    return [
        ("GET", f"/sessions/{ids['open_session']}", None),
        ("GET", f"/sessions/{ids['open_session']}/events", None),
        ("POST", "/attempts", {"session_id": ids["done_session"]}),
        ("GET", f"/attempts/{ids['open_attempt']}", None),
        ("GET", f"/attempts/{ids['done_attempt']}", None),
        ("GET", f"/attempts/{ids['open_attempt']}/draft", None),
        (
            "PUT",
            f"/attempts/{ids['open_attempt']}/draft",
            {"base_revision": 0, "answer": choice("A")},
        ),
        ("POST", f"/attempts/{ids['open_attempt']}/submit", {"answer": choice("B")}),
        ("POST", f"/tutor/sessions/{ids['open_session']}/next", {"action": "request_hint"}),
        ("POST", f"/tutor/sessions/{ids['done_session']}/next", {"action": "request_standard"}),
        ("POST", f"/reviews/{ids['review']}/complete", {"attempt_id": ids["done_attempt"]}),
        (
            "POST",
            "/sessions",
            {
                "question_id": qid("math-ineq-min"),
                "origin": "review",
                "review_item_id": ids["review"],
            },
        ),
        (
            "POST",
            "/sessions",
            {
                "question_id": qid("math-ineq-min"),
                "origin": "variant",
                "parent_session_id": ids["done_session"],
            },
        ),
    ]


def test_another_students_resources_are_all_404(alice_and_bob):
    bob = alice_and_bob["bob"]
    for method, path, body in _foreign_calls(alice_and_bob):
        error = bob.error(method, path, expect=404, json=body)
        assert error["code"] == "not_found", (method, path)


def test_foreign_and_missing_resources_are_indistinguishable(alice_and_bob):
    """防枚举：别人的资源和不存在的资源，响应除请求 ID 外逐字段相同。"""
    bob = alice_and_bob["bob"]
    missing = {key: str(uuid.uuid4()) for key in alice_and_bob if key not in {"alice", "bob"}}

    for (method, path, body), (_, ghost_path, ghost_body) in zip(
        _foreign_calls(alice_and_bob), _foreign_calls(missing), strict=True
    ):
        foreign = bob.error(method, path, expect=404, json=body)
        ghost = bob.error(method, ghost_path, expect=404, json=ghost_body)
        foreign.pop("request_id"), ghost.pop("request_id")
        assert foreign == ghost, (method, path)


def test_failed_cross_account_calls_leave_the_owners_data_untouched(alice_and_bob):
    alice, bob = alice_and_bob["alice"], alice_and_bob["bob"]
    before = (
        alice.data("GET", f"/sessions/{alice_and_bob['open_session']}"),
        alice.data("GET", f"/attempts/{alice_and_bob['open_attempt']}"),
        alice.data("GET", f"/attempts/{alice_and_bob['open_attempt']}/draft"),
        alice.data("GET", "/reviews/due"),
    )

    for method, path, body in _foreign_calls(alice_and_bob):
        bob.request(method, path, json=body)

    after = (
        alice.data("GET", f"/sessions/{alice_and_bob['open_session']}"),
        alice.data("GET", f"/attempts/{alice_and_bob['open_attempt']}"),
        alice.data("GET", f"/attempts/{alice_and_bob['open_attempt']}/draft"),
        alice.data("GET", "/reviews/due"),
    )
    assert after == before


def test_lists_and_summaries_only_show_the_callers_own_data(alice_and_bob):
    alice, bob = alice_and_bob["alice"], alice_and_bob["bob"]

    assert len(alice.data("GET", "/reviews/due")["items"]) == 1
    assert bob.data("GET", "/reviews/due", params={"scope": "all"})["items"] == []
    assert {t["kind"] for t in bob.data("GET", "/tasks/today")["items"]} == {"new_topic"}
    assert bob.data("GET", "/progress/summary")["independent"]["denominator"] == 0
    assert alice.data("GET", "/progress/summary")["independent"]["denominator"] == 1
    assert bob.data("GET", "/profile")["user_id"] == bob.user_id


# ---------------------------------------------------------------- 请求体里的身份字段不起作用


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/sessions", {"question_id": qid("math-ineq-min"), "origin": "practice"}),
        ("PUT", "/profile", {"region_code": "CN-51", "subjects": ["math"]}),
    ],
)
@pytest.mark.parametrize("field", ["student_id", "user_id", "role", "owner_id"])
def test_identity_fields_in_the_body_are_rejected_not_trusted(
    alice_and_bob, method, path, body, field
):
    """docs/09 验收：学生不可通过修改客户端参数访问其他学生数据。"""
    bob = alice_and_bob["bob"]
    forged = {**body, field: alice_and_bob["alice"].user_id if field != "role" else "admin"}

    assert bob.error(method, path, expect=422, json=forged)["code"] == "validation_error"


def test_resources_are_always_created_for_the_token_owner(alice_and_bob):
    alice, bob = alice_and_bob["alice"], alice_and_bob["bob"]

    session, attempt = begin(bob, "math-ineq-min")

    assert bob.data("GET", f"/sessions/{session['id']}")["id"] == session["id"]
    alice.error("GET", f"/sessions/{session['id']}", expect=404)
    alice.error("GET", f"/attempts/{attempt['id']}", expect=404)


def test_student_role_cannot_reach_admin_or_parent_endpoints(alice_and_bob):
    bob = alice_and_bob["bob"]
    alice_id = alice_and_bob["alice"].user_id

    # 家长周报本阶段未实现；即使将来实现，也不能凭路径里的 student_id 授权
    bob.error("GET", f"/parents/students/{alice_id}/weekly", expect=501)
    # 审核接口已经实现，学生一律 403——角色检查在校验请求体之前，空请求体也是 403 而不是 422
    error = bob.error(
        "POST", f"/admin/questions/{qid('math-ineq-min')}/review", expect=403, json={}
    )
    assert error["code"] == "forbidden"
