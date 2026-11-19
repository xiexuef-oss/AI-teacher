"""Real submit recovery, in-flight continuation, and self-check intent isolation.

Reads product storage only; every intercepted success is fetched from the API.
No synthetic HTTP success, product storage write or forced DOM edit is used.
"""

from __future__ import annotations

import re

from e2e import data
from e2e.api_client import Api
from e2e.browser import all_text, labels, onboard, open_flutter, reopen, stored, tap, type_into
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _record, _selected, _wait
from e2e.flows.student_proof import _open_proof_questions
from e2e.servers import API_URL

KEY = "math-mono-quadratic"
PROOF = "math-mono-def-proof"


class HoldWriteResponse:
    def __init__(self):
        self.route = None
        self.response = None
        self.result = None
        self.key = None
        self.body = None

    def __call__(self, route):
        response = route.fetch()
        if response.status not in (200, 201):
            route.fulfill(response=response)
            return
        self.route, self.response = route, response
        self.result = response.json()["data"]
        self.key = route.request.headers.get("idempotency-key")
        self.body = route.request.post_data_json

    def release(self):
        self.route.fulfill(response=self.response)
        self.route = None

    def lose(self):
        self.route.abort("connectionclosed")
        self.route = None


def _objective(ctx):
    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    tap(page, "练习", wait=2500)
    tap(page, data.title_of(KEY), wait=2500)
    options = [o["key"] for o in data.question(KEY)["content"]["options"]]
    tap(page, f"选项 {options[0]}", wait=1000)
    if not ctx.check(
        "客观题原稿已关联云端",
        _wait(page, lambda: bool(_record(page, "draft", data.question_id(KEY)).get("attemptId"))),
    ):
        return None
    return page, Api(stored(page, "auth.token")), options


def _lost_submit(ctx):
    prepared = _objective(ctx)
    if prepared is None:
        return
    page, api, options = prepared
    check = ctx.check
    qid = data.question_id(KEY)
    local = _record(page, "draft", qid)
    id, session = local["attemptId"], local["sessionId"]
    path = f"/attempts/{id}/submit"
    hold = HoldWriteResponse()
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
    page.context.route(API_URL + path, hold, times=1)
    tap(page, "提交", exact=True, wait=1000)
    if not check("真实提交已到服务端而响应尚未交付", _wait(page, lambda: hold.result is not None)):
        return
    first = hold.result
    check(
        "提交绑定同步快照revision及固定elapsed",
        isinstance(hold.body.get("expected_draft_revision"), int) and "elapsed_ms" in hold.body,
    )
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    ctx.shot(page, "submit_01_response_lost")
    reopen(page, f"#/questions/{qid}/solve?session={session}&attempt={id}&origin=practice")
    # Unchanged input can recover automatically; an explicit recovery action is
    # also valid if the product requires confirmation for an unknown response.
    if page.get_by_role("button", name="恢复原提交，当前修改保留", exact=True).count():
        tap(page, "恢复原提交，当前修改保留", exact=True, wait=1200)
    if not check("刷新恢复原提交实际幂等回执", _wait(page, lambda: bool(responses))):
        return
    check(
        "恢复复用原key及完整body包括elapsed",
        len(requests) >= 2 and all(k == hold.key and b == hold.body for k, b in requests),
    )
    check(
        "服务器重放同一提交而非重判",
        all(body == first and replay == "true" for body, replay in responses),
    )
    check(
        "提交序号及计数只增加一次",
        api.get(f"/attempts/{id}")["submission_no"] == 1
        and api.get(f"/sessions/{session}")["submitted_attempts"] == 1,
    )
    check("原A提交答案未变", api.get(f"/attempts/{id}")["answer"] == hold.body["answer"])
    check("恢复页面无未捕获异常", not page.errors, page.errors)
    ctx.shot(page, "submit_02_recovered")


def _continuation(ctx):
    prepared = _objective(ctx)
    if prepared is None:
        return
    page, api, options = prepared
    check = ctx.check
    qid = data.question_id(KEY)
    local = _record(page, "draft", qid)
    id, session = local["attemptId"], local["sessionId"]
    # An explicit real hint establishes assistance which a continuation must retain.
    tap(page, "给点提示", wait=1500)
    if not check(
        "原会话已有实际辅助状态", _wait(page, lambda: api.get(f"/sessions/{session}")["assisted"])
    ):
        return
    hold = HoldWriteResponse()
    path = f"/attempts/{id}/submit"
    page.context.route(API_URL + path, hold, times=1)
    tap(page, "提交", exact=True, wait=700)
    if not check("A提交已完成但回执在途", _wait(page, lambda: hold.result is not None)):
        return
    tap(page, f"选项 {options[1]}", wait=1000)
    if not check(
        "回执在途修改B已先存本机",
        _wait(page, lambda: _selected(_record(page, "draft", qid)) == [options[1]]),
    ):
        return
    hold.release()
    page.context.unroute(API_URL + path, hold)
    if not check(
        "A回执与未提交B续稿分别可见",
        _wait(page, lambda: "未提交续稿（与上次提交分别保存）" in all_text(page)),
    ):
        return
    check(
        "A评估只关联原A提交",
        api.get(f"/attempts/{id}")["answer"] == hold.body["answer"]
        and hold.body["answer"]["selected_options"] == [options[0]],
    )
    tap(page, "查看与继续续稿", exact=True, wait=700)
    # The continuation exposes its rendered answer with an explicit semantics
    # label, which Flutter Web emits as a text span. SelectableText alone on
    # this SDK creates an empty disabled textbox in both DOM and accessibility.
    dialog = page.get_by_role("alertdialog")
    readonly_answer = dialog.get_by_text(f"选项：{options[1]}", exact=True)
    visible_b = _wait(
        page,
        lambda: readonly_answer.count() == 1,
    )
    if not visible_b:
        (ctx.out_dir / "continuation_dialog_semantics.txt").write_text(
            "\n".join(labels(page)), encoding="utf-8"
        )
        (ctx.out_dir / "continuation_dialog_dom.html").write_text(
            page.locator("flt-semantics-host").inner_html(), encoding="utf-8"
        )
    check("真实续稿对话框显示B", visible_b)
    ctx.shot(page, "continuation_01_visible_B")
    tap(page, "在原会话继续此稿", exact=True, wait=2000)
    if not check(
        "明确继续B创建同会话新作答",
        _wait(page, lambda: _record(page, "draft", qid).get("attemptId") not in (None, id)),
    ):
        return
    fresh = _record(page, "draft", qid)
    new = api.get(f"/attempts/{fresh['attemptId']}")
    check(
        "继续B没有另开会话或自动提交",
        fresh["sessionId"] == session
        and new["session_id"] == session
        and new["status"] == "draft"
        and _selected(fresh) == [options[1]],
    )
    check(
        "继续B继承共享辅助状态",
        new["assisted"] is True and api.get(f"/sessions/{session}")["assisted"] is True,
    )
    check(
        "原A序号及答案不受B继续影响",
        api.get(f"/attempts/{id}")["submission_no"] == 1
        and api.get(f"/attempts/{id}")["answer"] == hold.body["answer"],
    )
    check("续稿页面没有未捕获异常", not page.errors, page.errors)
    ctx.shot(page, "continuation_02_same_session")


def _self_check(ctx):
    check = ctx.check
    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    _open_proof_questions(page, data.title_of(PROOF))
    seed = data.question(PROOF)
    step = seed["answer"]["value"]["steps"][0]
    type_into(
        page, page.get_by_role("textbox", name=re.compile("第 1 步：这一步写什么")), step["text"]
    )
    tap(page, "提交", exact=True, wait=2500)
    api = Api(stored(page, "auth.token"))
    submits = [
        path
        for method, path, status in page.responses
        if method == "POST" and path.endswith("/submit") and status == 200
    ]
    if not check("证明题实际提交后才出现自查", bool(submits) and "对照要点自查" in all_text(page)):
        return
    id = submits[-1].split("/attempts/")[1].split("/")[0]
    saved = []

    def response_seen(response):
        if (
            response.request.method == "PUT"
            and response.url.endswith(f"/attempts/{id}/self-check")
            and response.status == 200
        ):
            saved.append(
                (
                    response.request.headers.get("idempotency-key"),
                    response.request.post_data_json,
                    response.json()["data"],
                )
            )

    page.on("response", response_seen)
    for index, label in enumerate(("做到了", "没做到", "做到了")):
        lines = [line for line in labels(page) if line.endswith("| " + label)]
        role = re.match(r"([a-z]+)", lines[0]).group(1) if lines else "button"
        buttons = page.get_by_role(role, name=label, exact=True)
        count = buttons.count()
        check(f"自查第{index + 1}次要点数来自工程样题", count == len(data.points_of(PROOF)))
        for offset in range(count):
            buttons.nth(offset).click()
            page.wait_for_timeout(100)
        tap(page, "保存自查" if index == 0 else "更新自查", exact=True, wait=1400)
        if not check(
            f"第{index + 1}次自查实际保存",
            _wait(page, lambda expected=index: len(saved) > expected),
        ):
            return
    check("自查A到B到A每次使用独立intent键", len({key for key, _, _ in saved}) == 3)
    check("自查第三次A不重放第一次回执", saved[0][1] == saved[2][1] and saved[1][1] != saved[0][1])
    latest = api.get(f"/attempts/{id}/self-check")
    check(
        "实际服务端最终自查为A",
        latest["marks"] == saved[2][2]["marks"]
        and all(mark["level"] == "done" for mark in latest["marks"]),
    )
    check(
        "自查仍不自动判主观题对错", api.get(f"/attempts/{id}")["evaluation"]["state"] == "pending"
    )
    check("自查页面没有未捕获异常", not page.errors, page.errors)
    ctx.shot(page, "selfcheck_01_A_B_A")


def _revision_conflict(ctx):
    prepared = _objective(ctx)
    if prepared is None:
        return
    page, api, options = prepared
    check = ctx.check
    qid = data.question_id(KEY)
    local = _record(page, "draft", qid)
    attempt_id = local["attemptId"]
    result = {}
    # A tiny engineering stroke, uploaded by the real API as the other device.
    ink = {
        "version": 1,
        "pages": [
            {
                "width": 100,
                "height": 100,
                "strokes": [
                    {"color": "#000000", "width": 2, "points": [1, 2, 0, 0.5, 3, 4, 1, 0.5]}
                ],
            }
        ],
    }

    def concurrent_edit(route):
        result["body"] = route.request.post_data_json
        draft_path = f"/attempts/{attempt_id}/draft"
        before = api.get(draft_path)
        result["cloud"] = api.request(
            "PUT",
            draft_path,
            {
                "base_revision": before["revision"],
                "answer": {"selected_options": [options[1]]},
                "strokes": ink,
            },
        )
        actual = route.fetch()
        result["status"] = actual.status
        result["response"] = actual.json()
        route.fulfill(response=actual)

    path = API_URL + f"/attempts/{attempt_id}/submit"
    page.context.route(path, concurrent_edit, times=1)
    tap(page, "提交", exact=True, wait=1400)
    if not check("提交在真实他端更新后收到响应", _wait(page, lambda: "status" in result)):
        return
    page.context.unroute(path, concurrent_edit)
    check(
        "服务器实际拒绝旧快照提交",
        result["status"] == 409
        and result["response"]["error"]["code"] == "submission_draft_revision_conflict",
    )
    if result["status"] != 409:
        return
    details = result["response"]["error"]["details"]
    check(
        "冲突同时包含本人新revision与原提交期望",
        details["expected_draft_revision"] == result["body"]["expected_draft_revision"]
        and details["server_revision"] == result["cloud"]["revision"]
        and details["server_draft"]["strokes"] == result["cloud"]["strokes"],
    )
    attempt = api.get(f"/attempts/{attempt_id}")
    check(
        "未把A答案与B笔迹作为提交或评估",
        attempt["status"] == "draft"
        and attempt["submission_no"] is None
        and attempt["evaluation"] is None,
    )
    check(
        "云端保留他端B而原A提交体未变",
        api.get(f"/attempts/{attempt_id}/draft") == result["cloud"]
        and result["body"]["answer"]["selected_options"] == [options[0]],
    )
    check("修订竞争页面没有未捕获异常", not page.errors, page.errors)
    ctx.shot(page, "revision_01_real_conflict")


def run(ctx):
    _lost_submit(ctx)
    _continuation(ctx)
    _self_check(ctx)
    _revision_conflict(ctx)


FLOW = Flow(
    name="student_write_recovery",
    title="提交丢响应、A与B续稿分离、自查新intent及真实修订竞争",
    needs=frozenset({"flutter"}),
    run=run,
)
