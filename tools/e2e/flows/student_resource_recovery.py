"""Real tutor/review resource journal recovery; never edits storage or due dates."""

from __future__ import annotations

import json
import time
from uuid import uuid4

from e2e import data
from e2e.api_client import Api
from e2e.browser import all_text, onboard, open_flutter, reopen, stored, stored_all, tap
from e2e.checks import say
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _record, _selected, _wait
from e2e.flows.student_write_recovery import HoldWriteResponse
from e2e.servers import API_URL

KEY = "math-mono-quadratic"


def review_records_first_submission(requests, state, current_stage, source_id, draft_id):
    # The API accepts any attempt belonging to S, including its active draft B;
    # the persisted completion must still use S's first real submission C.
    return (
        len(requests) == 1
        and requests[0][1]["attempt_id"] in {source_id, draft_id}
        and state["last_attempt_id"] == source_id
        and current_stage == 1
    )


def rendered_title_count(diagnostic):
    # Native heading semantics expose an accessible name without a text node.
    # Two real headings (or two named visible nodes) remain a failure.
    if diagnostic["heading_count"]:
        return diagnostic["heading_count"]
    if "semantic_texts" in diagnostic:
        # CanvasKit merges a whole card into one span. Count exact title lines
        # in each node's own text, never its ancestors' descendant text.
        return sum(
            line.strip() == diagnostic["title"]
            for text in diagnostic["semantic_texts"]
            for line in text.splitlines()
        )
    return sum(node["visible"] for node in diagnostic["named_nodes"])


def title_evidence(ctx, page, title, name):
    diagnostic = {
        "title": title,
        "rendered_text": all_text(page),
        "aria_snapshot": page.locator("body").aria_snapshot(),
        "semantic_texts": page.evaluate(
            """() => Array.from(document.querySelectorAll('flt-semantics'))
            .filter(e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden')
            .map(e => (e.getAttribute('aria-label') || '') || Array.from(e.childNodes)
              .filter(n => n.nodeType === 3 || n.tagName === 'SPAN')
              .map(n => n.textContent).join(''))"""
        ),
        "matching_semantics": page.evaluate(
            """title => Array.from(document.querySelectorAll('flt-semantics,flt-semantics-host *'))
            .filter(e => ((e.getAttribute('aria-label') || '') + e.textContent).includes(title))
            .map(e => ({tag:e.tagName,role:e.getAttribute('role'),label:e.getAttribute('aria-label'),
                html:e.outerHTML.slice(0,6000)}))""",
            title,
        ),
        "text_locator_count": page.get_by_text(title, exact=True).count(),
        "heading_count": page.get_by_role("heading", name=title, exact=True).count(),
        "button_count": page.get_by_role("button", name=title, exact=True).count(),
        "controls": page.get_by_role("button").evaluate_all(
            "nodes => nodes.map(e => ({tag:e.tagName,role:e.getAttribute('role'),label:e.getAttribute('aria-label'),text:e.textContent.slice(0,200)}))"
        ),
        "named_nodes": page.evaluate(
            """(title) => Array.from(document.querySelectorAll('[aria-label]'))
            .filter(e => e.getAttribute('aria-label') === title).map(e => ({
                tag: e.tagName, role: e.getAttribute('role'), label: e.getAttribute('aria-label'),
                visible: e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden',
                html: e.outerHTML.slice(0, 2000)
            }))""",
            title,
        ),
        "heading_nodes": page.get_by_role("heading", name=title, exact=True).evaluate_all(
            "nodes => nodes.map(e => ({tag:e.tagName,role:e.getAttribute('role'),html:e.outerHTML.slice(0,2000)}))"
        ),
    }
    directory = ctx.out_dir / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-{uuid4().hex}.json"
    path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    return rendered_title_count(diagnostic), str(path)


def recovery_storage(values, owner, question_id, session_id, review_id):
    """Allowlist raw records needed to reproduce this one student's recovery."""
    resources = {
        f"resource-journal/session/{session_id}",
        f"resource-journal/review/{review_id}",
        f"draft-bundle/{question_id}",
        f"active/{question_id}",
    }
    question_records = [
        f"{kind}/{question_id}"
        for kind in ("draft", "draft-recovery", "question", "workspace-context")
    ]
    selected = {}
    for key, value in values.items():
        normalized = key.removeprefix("flutter.")
        prefix = f"u/{owner}/"
        if not owner or not normalized.startswith(prefix):
            continue
        relative = normalized[len(prefix) :]
        if relative in resources or any(
            relative == record or relative.startswith(record + "/") for record in question_records
        ):
            selected[key] = value
    return selected


def review_recovery_evidence(ctx, page, api, question_id, session_id, attempt_id, review_id):
    owner = stored(page, "auth.userId")
    diagnostic = {
        "storage": recovery_storage(stored_all(page), owner, question_id, session_id, review_id),
        "rendered_text": all_text(page),
        "responses": [],
    }
    endpoints = [f"/sessions/{session_id}", f"/attempts/{attempt_id}"]
    endpoints.append(
        f"/reviews/{review_id}/state" if review_id else f"/sessions/{session_id}/events"
    )
    for endpoint in endpoints:
        try:
            diagnostic["responses"].append(
                {"path": endpoint, "status": 200, "data": api.get(endpoint)}
            )
        except Exception as error:
            diagnostic["responses"].append(
                {
                    "path": endpoint,
                    "status": getattr(error, "status", None),
                    "error_type": type(error).__name__,
                }
            )
    directory = ctx.out_dir / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"review-recovery-state-{uuid4().hex}.json"
    path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def student(ctx):
    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    return page, Api(stored(page, "auth.token"))


def trace(page, path):
    requests = []
    responses = []

    def request_seen(request):
        if request.method == "POST" and request.url == API_URL + path:
            requests.append((request.headers.get("idempotency-key"), request.post_data_json))

    def response_seen(response):
        if (
            response.request.method == "POST"
            and response.url == API_URL + path
            and response.status == 200
        ):
            responses.append(
                (response.json()["data"], response.headers.get("idempotency-replayed"))
            )

    page.on("request", request_seen)
    page.on("response", response_seen)
    return requests, responses


def seed_review(ctx):
    page, api = student(ctx)
    session = api.post("/sessions", {"question_id": data.question_id(KEY), "origin": "practice"})
    attempt = api.post("/attempts", {"session_id": session["id"]})
    submitted = api.post(
        f"/attempts/{attempt['id']}/submit", {"answer": data.answer_for(KEY, "wrong")}
    )
    return page, api, submitted["review_item"]


def wait_due(ctx, case):
    page, api, item = case
    deadline = time.monotonic() + 90
    notice = 0
    while time.monotonic() < deadline:
        items = api.get("/reviews/due")["items"]
        if any(row["id"] == item["id"] for row in items):
            return True
        if time.monotonic() > notice:
            say("等待真实配置的一分钟复测到期（不修改数据库/时钟）")
            notice = time.monotonic() + 15
        page.wait_for_timeout(1000)
    return ctx.check("真实复测项在配置时间内到期", False)


def review_route(qid, session, attempt, item):
    return (
        f"#/questions/{qid}/solve?origin=review&review={item}&session={session}&attempt={attempt}"
    )


def prepare_review(ctx, case):
    if not wait_due(ctx, case):
        return None
    page, api, item = case
    session = api.post(
        "/sessions",
        {"question_id": data.question_id(KEY), "origin": "review", "review_item_id": item["id"]},
    )
    attempt = api.post("/attempts", {"session_id": session["id"]})
    return page, api, item, session, attempt


def stage(api, id):
    return next(row for row in api.get("/reviews/due?scope=all")["items"] if row["id"] == id)[
        "stage"
    ]


def tutor_replay(ctx):
    page, api = student(ctx)
    check = ctx.check
    tap(page, "练习", wait=2500)
    tap(page, data.title_of(KEY), wait=2200)
    qid = data.question_id(KEY)
    if not check(
        "辅导原稿已关联", _wait(page, lambda: bool(_record(page, "draft", qid).get("sessionId")))
    ):
        return
    local = _record(page, "draft", qid)
    session = local["sessionId"]
    path = f"/tutor/sessions/{session}/next"
    requests, responses = trace(page, path)
    hold = HoldWriteResponse()
    page.context.route(API_URL + path, hold, times=1)
    tap(page, "给点提示", wait=800)
    if not check("提示实际成功但回执未交付", _wait(page, lambda: hold.result is not None)):
        return
    first = hold.result
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    route = (
        f"#/questions/{qid}/solve?origin=practice&session={session}&attempt={local['attemptId']}"
    )
    reopen(page, route)
    page.wait_for_timeout(13500)
    check("刷新不自动重发辅导POST", len(requests) == 1)
    tap(page, "恢复原辅导动作", exact=True, wait=1600)
    if not check("明确恢复收到真实重放回执", _wait(page, lambda: bool(responses))):
        return
    check(
        "提示恢复原key原body且不重复层级",
        all(k == hold.key and b == hold.body for k, b in requests)
        and responses[-1] == (first, "true")
        and api.get(f"/sessions/{session}")["hint_level_revealed"] == 1,
    )
    total = first["session"]["hint_levels_total"]
    title_count, evidence = title_evidence(ctx, page, f"提示 第 1/{total} 层", "hint-recovered")
    check("恢复提示事件只显示一次", title_count == 1, evidence)
    tap(page, "给点提示", wait=1400)
    check(
        "下一次明确提示使用新intent",
        _wait(page, lambda: len(requests) >= 3)
        and requests[-1][0] != hold.key
        and api.get(f"/sessions/{session}")["hint_level_revealed"] == 2,
    )
    ctx.shot(page, "tutor_01_replay_and_new_intent")


def tutor_stale(ctx):
    page, api = student(ctx)
    check = ctx.check
    tap(page, "练习", wait=2300)
    tap(page, data.title_of(KEY), wait=2200)
    qid = data.question_id(KEY)
    if not check(
        "旧hint竞争会话已建立",
        _wait(page, lambda: bool(_record(page, "draft", qid).get("sessionId"))),
    ):
        return
    session = _record(page, "draft", qid)["sessionId"]
    path = f"/tutor/sessions/{session}/next"
    hold = HoldWriteResponse()
    page.context.route(API_URL + path, hold, times=1)
    tap(page, "给点提示", wait=700)
    if not check("旧hint回执仍在途", _wait(page, lambda: hold.result is not None)):
        return
    source_id = _record(page, "draft", qid)["attemptId"]
    submitted = api.post(
        f"/attempts/{source_id}/submit", {"answer": data.answer_for(KEY, "correct")}
    )
    check("另一端先真实提交原作答", submitted["attempt"]["status"] == "submitted")
    check("完成前没有未提交草稿", api.get(f"/sessions/{session}")["active_attempt_id"] is None)
    api.post(path, {"action": "request_standard", "confirm_end_independent": True})
    api.post(path, {"action": "mark_understood"})
    latest = api.get(f"/sessions/{session}")
    check("另一端真实解析后完成会话", latest["state"] == "DONE" and latest["used_solution"] is True)
    hold.release()
    page.context.unroute(API_URL + path, hold)
    review_recovery_evidence(ctx, page, api, qid, session, source_id, "")
    check(
        "迟到hint后UI保留完成状态",
        _wait(
            page,
            lambda: (
                "再试一次" not in all_text(page)
                and page.get_by_role("button", name="给点提示").count() == 0
            ),
        ),
    )
    check("迟到hint不能回退服务器flags与阶段", api.get(f"/sessions/{session}") == latest)
    events = api.get(f"/sessions/{session}/events")["items"]
    seq = [event["seq_no"] for event in events]
    check("事件序号不重复", len(seq) == len(set(seq)))
    total = latest["hint_levels_total"]
    title_count, evidence = title_evidence(ctx, page, f"提示 第 1/{total} 层", "hint-stale")
    check("旧提示事件UI不重复", title_count == 1, evidence)
    ctx.shot(page, "tutor_02_late_reply_done")


def review_replay(ctx, case):
    prepared = prepare_review(ctx, case)
    if prepared is None:
        return
    page, api, item, session, attempt = prepared
    check = ctx.check
    qid = data.question_id(KEY)
    id = item["id"]
    path = f"/reviews/{id}/complete"
    requests, responses = trace(page, path)
    hold = HoldWriteResponse()
    route = review_route(qid, session["id"], attempt["id"], id)
    reopen(page, route)
    page.context.route(API_URL + path, hold, times=1)
    answer = data.answer_for(KEY, "correct")["selected_options"][0]
    tap(page, f"选项 {answer}", wait=700)
    tap(page, "提交", exact=True, wait=1000)
    if not check("复测记录真实成功但回执丢失", _wait(page, lambda: hold.result is not None)):
        return
    first = hold.result
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    check("首次复测完成实际进一阶段", stage(api, id) == 1)
    reopen(page, route)
    page.wait_for_timeout(13500)
    check("刷新不自动重发复测完成", len(requests) == 1)
    _, evidence = title_evidence(ctx, page, "恢复复测记录", "review-recover-button")
    recovery_button_count = page.get_by_role("button", name="恢复复测记录", exact=True).count()
    store_evidence = None
    if recovery_button_count != 1:
        store_evidence = review_recovery_evidence(
            ctx, page, api, qid, session["id"], attempt["id"], id
        )
    if not check(
        "待确认复测明确恢复入口存在",
        recovery_button_count == 1,
        {"dom": evidence, "recovery": store_evidence},
    ):
        return
    tap(page, "恢复复测记录", exact=True, wait=1500)
    if not check("明确恢复同一复测完成回执", _wait(page, lambda: bool(responses))):
        return
    check(
        "复测恢复原key原body原结果",
        all(key == hold.key and body == hold.body for key, body in requests)
        and responses[-1] == (first, "true"),
    )
    check("恢复后stage只推进一次", stage(api, id) == 1)
    ctx.shot(page, "review_01_replayed_once")


def review_foreign_submission(ctx, case):
    prepared = prepare_review(ctx, case)
    if prepared is None:
        return
    page, api, item, session, first = prepared
    check = ctx.check
    id = item["id"]
    sid = session["id"]
    cid = first["id"]
    api.post(f"/attempts/{cid}/submit", {"answer": data.answer_for(KEY, "correct")})
    original = api.get(f"/attempts/{cid}")
    second = api.post("/attempts", {"session_id": sid})
    bid = second["id"]
    check(
        "最新会话明确给出首个真实提交C",
        api.get(f"/sessions/{sid}")["first_submitted_attempt_id"] == cid,
    )
    requests, responses = trace(page, f"/reviews/{id}/complete")
    reopen(page, review_route(data.question_id(KEY), sid, bid, id))
    page.wait_for_timeout(1500)
    check(
        "进入B不会自动记录他端C或提交B",
        not requests and api.get(f"/attempts/{bid}")["status"] == "draft",
    )
    local_option = data.answer_for(KEY, "wrong")["selected_options"][0]
    tap(page, f"选项 {local_option}", wait=800)
    check(
        "B的不同作答先保存在本机",
        _wait(
            page, lambda: _selected(_record(page, "draft", data.question_id(KEY))) == [local_option]
        ),
    )
    tap(page, "记录已提交复测", exact=True, wait=600)
    check("确认前没有复测POST", not requests)
    tap(page, "取消", exact=True, wait=300)
    check("取消确认不推进stage", not requests and stage(api, id) == 0)
    tap(page, "记录已提交复测", exact=True, wait=300)
    tap(page, "确认记录", exact=True, wait=1500)
    if not check("明确确认后记录实际首提交C", _wait(page, lambda: bool(responses))):
        return
    check(
        "复测实际来源是首提交C且只推进一阶段",
        review_records_first_submission(
            requests, api.get(f"/reviews/{id}/state"), stage(api, id), cid, bid
        ),
    )
    check(
        "C未改写而B仍未提交",
        api.get(f"/attempts/{cid}") == original
        and api.get(f"/attempts/{bid}")["status"] == "draft"
        and not any(
            method == "POST" and path.endswith("/submit") for method, path, _ in page.responses
        ),
    )
    check(
        "记录C后B的不同输入仍独立保留",
        _selected(_record(page, "draft", data.question_id(KEY))) == [local_option]
        and _record(page, "draft", data.question_id(KEY)).get("attemptId") == bid
        and _wait(
            page,
            lambda: (
                (api.get(f"/attempts/{bid}/draft").get("answer") or {}).get("selected_options")
                == [local_option]
            ),
        ),
    )
    ctx.shot(page, "review_02_explicit_other_submission")


def run(ctx):
    first = seed_review(ctx)
    second = seed_review(ctx)
    tutor_replay(ctx)
    tutor_stale(ctx)
    review_replay(ctx, first)
    review_foreign_submission(ctx, second)
    for page in ctx.pages:
        ctx.check("资源恢复页面没有未捕获异常", not page.errors, page.errors)


FLOW = Flow(
    name="student_resource_recovery",
    title="辅导与复测真实丢响应恢复、迟到提示及明确记录首提交",
    needs=frozenset({"flutter"}),
    run=run,
    review_minutes=(1, 2, 3),
)
