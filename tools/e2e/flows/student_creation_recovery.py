"""Real session/attempt creation success with lost response and durable replay.

Two isolated browser contexts; only read product storage. No fabricated creation
response, copy API, storage write, submission or tutoring action is used.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from e2e import data
from e2e.api_client import Api
from e2e.browser import all_text, labels, onboard, open_flutter, reopen, stored, tap
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _record, _selected, _wait
from e2e.servers import API_URL

KEY = "math-mono-quadratic"


class LostCreationResponse:
    def __init__(self):
        self.result = None
        self.key = None
        self.body = None

    def __call__(self, route):
        response = route.fetch()
        if response.status != 201:
            route.fulfill(response=response)
            return
        self.result = response.json()["data"]
        self.key = route.request.headers.get("idempotency-key")
        self.body = route.request.post_data_json
        route.abort("connectionclosed")


def creation_command(bundle, key):
    for workspace in bundle.get("creationIntents", {}).values():
        for command in workspace.get("history", {}).values():
            if key in (command.get("sessionKey"), command.get("attemptKey")):
                return command
    return {}


def local_choice(bundle, option):
    return any(_selected(draft) == [option] for draft in bundle.get("drafts", {}).values())


def _scenario(ctx, endpoint):
    check = ctx.check
    page = ctx.new_page()
    qid = data.question_id(KEY)
    selected = data.question(KEY)["content"]["options"][0]["key"]
    lost = LostCreationResponse()
    pattern = API_URL + "/" + endpoint
    requests = []
    responses = []

    def request_seen(request):
        if request.method == "POST" and request.url == pattern:
            requests.append((request.headers.get("idempotency-key"), request.post_data_json))

    def response_seen(response):
        if response.request.method == "POST" and response.url == pattern and response.status == 201:
            responses.append(
                (response.json()["data"], response.headers.get("idempotency-replayed"))
            )

    page.on("request", request_seen)
    page.on("response", response_seen)
    page.context.route(pattern, lost, times=1)
    try:
        open_flutter(page)
        onboard(page)
        tap(page, "练习", wait=2500)
        tap(page, data.title_of(KEY), wait=2000)
        if not check(
            f"{endpoint}服务端真实创建成功后响应丢失", _wait(page, lambda: lost.result is not None)
        ):
            return
    finally:
        page.context.unroute(pattern, lost)
    tap(page, f"选项 {selected}", wait=1000)

    def bundle():
        return _record(page, "draft-bundle", qid)

    if not check(
        f"{endpoint}丢响应后输入先存本机", _wait(page, lambda: local_choice(bundle(), selected))
    ):
        return
    command = creation_command(bundle(), lost.key)
    body_field = "sessionBody" if endpoint == "sessions" else "attemptBody"
    check(
        f"{endpoint}不可变命令及原body已落盘",
        bool(command) and command.get(body_field) == lost.body,
    )
    check(f"{endpoint}刷新前没有成功接收该响应", not responses)
    check(
        f"{endpoint}原命令仍处于prepared阶段",
        command.get("phase")
        == ("session_prepared" if endpoint == "sessions" else "attempt_prepared"),
    )
    ctx.shot(page, f"{endpoint}_01_response_lost")
    original_id = lost.result["id"]
    reopen(page, f"#/questions/{qid}/solve?origin=practice")
    if not check(
        f"{endpoint}刷新后自动重放并恢复输入",
        _wait(
            page, lambda: bool(responses) and _selected(_record(page, "draft", qid)) == [selected]
        ),
    ):
        return
    recovered = _record(page, "draft", qid)
    check(
        f"{endpoint}恢复原服务端资源ID",
        recovered.get("sessionId" if endpoint == "sessions" else "attemptId") == original_id,
    )
    if endpoint == "attempts":
        check(
            f"{endpoint}未另开会话绕过原命令", recovered.get("sessionId") == lost.body["session_id"]
        )
    check(
        f"{endpoint}刷新重放原key与原body",
        len(requests) >= 2 and all(key == lost.key and body == lost.body for key, body in requests),
    )
    check(
        f"{endpoint}服务端证实幂等重放且ID不变",
        all(result["id"] == original_id and replay == "true" for result, replay in responses),
    )
    after = creation_command(bundle(), lost.key)
    check(
        f"{endpoint}同一intent已关联原资源",
        after.get("intentId") == command.get("intentId") and after.get("phase") == "attached",
    )
    api = Api(stored(page, "auth.token"))
    session_id, attempt_id = recovered.get("sessionId"), recovered.get("attemptId")
    if not check(f"{endpoint}会话与作答关联均已恢复", bool(session_id and attempt_id)):
        return
    check(
        f"{endpoint}原作答属于恢复会话且未提交",
        api.get(f"/attempts/{attempt_id}")["session_id"] == session_id
        and api.get(f"/attempts/{attempt_id}")["status"] == "draft",
    )
    refs = api.get(f"/questions/{qid}/drafts")["items"]
    check(
        f"{endpoint}没有重复新增草稿或会话",
        len(refs) == 1
        and refs[0]["attempt_id"] == attempt_id
        and refs[0]["session_id"] == session_id,
    )
    check(
        f"{endpoint}固定题目版本与创建命令一致",
        api.get(f"/sessions/{session_id}/question")["version"]
        == after["sessionBody"]["expected_question_version"],
    )
    check(
        f"{endpoint}选项恢复来自真实页面",
        any(f"选项 {selected}，已选" in label for label in labels(page)),
    )
    check(
        f"{endpoint}没有自动提交或辅导请求",
        not any(
            method == "POST"
            and (path.endswith("/submit") or "/tutor/" in path or path.endswith("/self-check"))
            for method, path, _ in page.responses
        ),
    )
    check(f"{endpoint}页面没有未捕获异常", not page.errors, page.errors)
    ctx.shot(page, f"{endpoint}_02_restored")


class UnsentSessionCreation:
    """Block creation entirely; unlike lost-response tests no fetch is allowed."""

    def __init__(self):
        self.requests = []

    def __call__(self, route):
        self.requests.append(
            (route.request.headers.get("idempotency-key"), route.request.post_data_json)
        )
        route.abort("internetdisconnected")


def publish_next_version(question_id):
    from support.admin import edit_body

    author = Api(Api("").post("/dev/local-identities?role=reviewer")["access_token"])
    independent = Api(Api("").post("/dev/local-identities?role=reviewer")["access_token"])
    path = f"/admin/questions/{question_id}"
    original = author.get(path)
    withdrawn = author.post(
        path + "/review",
        {
            "decision": "withdraw",
            "expected_version": original["version"],
            "expected_review_revision": original["review_revision"],
            "comment": "工程联调：版本恢复保护",
        },
    )
    changed = author.post(
        path + "/versions",
        edit_body(
            {**original, "review_revision": withdrawn["review_revision"]},
            title=original["title"] + "（版本恢复联调更新）",
            content={
                **original["content"],
                "stem": "版本恢复联调更新。\n" + original["content"]["stem"],
            },
        ),
    )
    version = changed["version"]
    kinds = [solution["kind"] for solution in changed["solutions"]]
    approved = independent.post(
        path + "/review",
        {
            "decision": "approve",
            "expected_version": version,
            "expected_review_revision": changed["review_revision"],
            "solution_kinds": kinds,
        },
    )
    independent.post(
        path + "/review",
        {
            "decision": "publish",
            "expected_version": version,
            "expected_review_revision": approved["review_revision"],
        },
    )
    published = independent.get(path)
    return original, published


def _version_scenario(ctx):
    check = ctx.check
    page = ctx.new_page()
    qid = data.question_id(KEY)
    option = data.question(KEY)["content"]["options"][2]["key"]
    blocked = UnsentSessionCreation()
    pattern = API_URL + "/sessions"
    conflicts = []
    creates = []

    def response_seen(response):
        if response.request.method == "POST" and response.url == pattern:
            if response.status == 409:
                conflicts.append(
                    (
                        response.json()["error"],
                        response.request.headers.get("idempotency-key"),
                        response.request.post_data_json,
                    )
                )
            if response.status == 201:
                creates.append((response.json()["data"], response.request.post_data_json))

    page.on("response", response_seen)
    page.context.route(pattern, blocked)
    try:
        open_flutter(page)
        onboard(page)
        tap(page, "练习", wait=2500)
        tap(page, data.title_of(KEY), wait=2000)
        if not check("旧版会话创建始终未发送至服务端", _wait(page, lambda: bool(blocked.requests))):
            return
        tap(page, f"选项 {option}", wait=1000)
        if not check(
            "未绑定旧版输入已保存本机",
            _wait(page, lambda: local_choice(_record(page, "draft-bundle", qid), option)),
        ):
            return
        bundle = _record(page, "draft-bundle", qid)
        old_scope = next(
            scope
            for scope, draft in bundle.get("drafts", {}).items()
            if _selected(draft) == [option]
        )
        old_context = bundle["workspaceContexts"][old_scope]
        old_version = old_context["question"]["version"]
        old_key, old_body = blocked.requests[0]
        check(
            "未绑定输入有可信旧版上下文",
            old_scope.startswith("local/") and old_body["expected_question_version"] == old_version,
        )
        api = Api(stored(page, "auth.token"))
        check("离线创建没有生成远端草稿", api.get(f"/questions/{qid}/drafts")["items"] == [])
        old, published = publish_next_version(qid)
        check(
            "实际双审核身份发布可区分的新版本",
            published["status"] == "published"
            and published["version"] == old_version + 1
            and old["version"] == old_version,
        )
    finally:
        page.context.unroute(pattern, blocked)
    reopen(page, f"#/questions/{qid}/solve?origin=practice")
    if not check("旧命令恢复实际收到题目版本409", _wait(page, lambda: bool(conflicts))):
        return
    error, key, request = conflicts[-1]
    check(
        "409来自原key原body且只含版本信息",
        error["code"] == "question_version_conflict"
        and key == old_key
        and request == old_body
        and error["details"]
        == {
            "expected_question_version": old_version,
            "current_question_version": published["version"],
        },
    )
    check(
        "409保持旧题面与选择且显示暂停",
        _wait(
            page,
            lambda: (
                old["title"] in all_text(page)
                and "版本恢复联调更新。" not in all_text(page)
                and "创建已暂停" in all_text(page)
                and any(f"选项 {option}，已选" in label for label in labels(page))
            ),
        ),
        {
            "title": old["title"] in all_text(page),
            "marker": "版本恢复联调更新。" in all_text(page),
            "paused": "创建已暂停" in all_text(page),
            "selected": any(f"选项 {option}，已选" in label for label in labels(page)),
        },
    )
    (ctx.out_dir / "version-conflict-semantics.txt").write_text(
        repr({"title": old["title"], "labels": labels(page)}), encoding="utf-8"
    )
    check(
        "409没有向新版上传或新建会话",
        not creates
        and not any(
            method == "PUT" and path.endswith("/draft") for method, path, _ in page.responses
        ),
    )
    check(
        "409原输入和上下文仍完整保留",
        _selected(_record(page, "draft-bundle", qid)["drafts"].get(old_scope, {})) == [option]
        and _record(page, "draft-bundle", qid)["workspaceContexts"].get(old_scope) == old_context,
    )
    ctx.shot(page, "version_01_conflict_preserves_old")
    tap(page, "保留旧稿，另开新版", exact=True, wait=2500)
    if not check(
        "明确选择后新版workspace自动创建",
        _wait(page, lambda: bool(creates) and bool(_record(page, "draft", qid).get("attemptId"))),
    ):
        return
    current = _record(page, "draft", qid)
    check(
        "新版使用新命令及新版本而非改写旧body",
        creates[-1][1]["expected_question_version"] == published["version"]
        and creates[-1][0]["question_version"] == published["version"],
    )
    check(
        "新版题面可区分且输入为空",
        _wait(
            page,
            lambda: (
                published["title"] in all_text(page)
                and "版本恢复联调更新。" in all_text(page)
                and _selected(_record(page, "draft", qid)) == []
                and not any("，已选" in label and "选项 " in label for label in labels(page))
            ),
        ),
        {
            "title": published["title"] in all_text(page),
            "marker": "版本恢复联调更新。" in all_text(page),
            "empty": _selected(_record(page, "draft", qid)) == [],
            "selected": [label for label in labels(page) if "，已选" in label and "选项 " in label],
        },
    )
    (ctx.out_dir / "version-latest-semantics.txt").write_text(
        repr({"title": published["title"], "labels": labels(page)}), encoding="utf-8"
    )
    final = _record(page, "draft-bundle", qid)
    check(
        "另开新版保留原v1槽及输入",
        _selected(final["drafts"].get(old_scope, {})) == [option]
        and final["workspaceContexts"].get(old_scope) == old_context,
    )
    check(
        "新版没有自动迁移旧答案至云端",
        api.get(f"/attempts/{current['attemptId']}/draft")["answer"]
        in (None, {}, {"selected_options": []}),
    )
    check(
        "版本链没有自动提交或辅导请求",
        not any(
            method == "POST" and (path.endswith("/submit") or "/tutor/" in path)
            for method, path, _ in page.responses
        ),
    )
    check("版本链页面没有未捕获异常", not page.errors, page.errors)
    ctx.shot(page, "version_02_new_empty_workspace")
    tap(page, "本机旧稿", exact=True, wait=500)
    tap(page, old["title"], wait=500)
    check(
        "真实旧稿入口只读显示原版本及原选择",
        _wait(
            page,
            lambda: (
                "本机旧稿（只读）" in all_text(page)
                and f"题目版本 {old_version}" in all_text(page)
                and f"选择：{option}" in all_text(page)
            ),
        ),
    )
    ctx.shot(page, "version_03_readonly_original")
    tap(page, "关闭", exact=True, wait=300)
    check(
        "查看旧稿没有替换当前新版空稿",
        _record(page, "draft", qid).get("attemptId") == current["attemptId"]
        and _selected(_record(page, "draft", qid)) == [],
    )


def bound_route_ids(url):
    query = parse_qs(urlsplit(urlsplit(url).fragment).query)
    return query.get("session", [None])[0], query.get("attempt", [None])[0]


def _blocked_retry_scenario(ctx):
    check = ctx.check
    page = ctx.new_page()
    qid = data.question_id(KEY)
    option = data.question(KEY)["content"]["options"][0]["key"]
    conflicts = []

    def response_seen(response):
        if (
            response.request.method == "POST"
            and response.url == API_URL + "/attempts"
            and response.status == 409
        ):
            conflicts.append(response.json()["error"])

    page.on("response", response_seen)
    open_flutter(page)
    onboard(page)
    api = Api(stored(page, "auth.token"))
    title = api.get(f"/questions/{qid}")["title"]
    tap(page, "练习", wait=2500)
    tap(page, title, wait=2500)
    tap(page, f"选项 {option}", wait=1000)
    if not check(
        "显式旧路由场景已创建原稿",
        _wait(
            page,
            lambda: (
                bool(_record(page, "draft", qid).get("attemptId"))
                and _selected(_record(page, "draft", qid)) == [option]
                and _record(page, "draft", qid).get("baseRevision", 0) > 0
            ),
        ),
    ):
        return
    original = _record(page, "draft", qid)
    session1, attempt1 = original["sessionId"], original["attemptId"]
    old_route = f"#/questions/{qid}/solve?session={session1}&attempt={attempt1}&origin=practice"
    reopen(page, old_route)
    check("起点URL明确绑定旧会话与作答", bound_route_ids(page.url) == (session1, attempt1))
    # Explicitly reveal the complete solution before submitting this original attempt.
    tap(page, "我想直接看解析…", exact=True, wait=500)
    tap(page, "看解析", exact=True, wait=1500)
    if not check(
        "原会话明确查看完整解析",
        _wait(page, lambda: api.get(f"/sessions/{session1}")["used_solution"] is True),
    ):
        return
    tap(page, "提交", exact=True, wait=2500)
    if not check(
        "原作答真实提交",
        _wait(page, lambda: api.get(f"/attempts/{attempt1}")["status"] == "submitted"),
    ):
        return
    old_attempt = api.get(f"/attempts/{attempt1}")
    old_draft = api.get(f"/attempts/{attempt1}/draft")
    old_session = api.get(f"/sessions/{session1}")
    other = api.post("/attempts", {"session_id": session1})
    other_id = other["id"]
    other_draft = api.get(f"/attempts/{other_id}/draft")
    tap(page, "再试一次", exact=True, wait=1800)
    if not check(
        "实际再试一次收到其他未提交稿409",
        _wait(page, lambda: bool(conflicts) and "创建已暂停" in all_text(page)),
    ):
        return
    check(
        "409确认为attempt_in_progress而非伪造错误", conflicts[-1]["code"] == "attempt_in_progress"
    )
    commands = [
        command
        for workspace in _record(page, "draft-bundle", qid).get("creationIntents", {}).values()
        for command in workspace.get("history", {}).values()
    ]
    check("重试命令阻断并持久保留", any(command.get("phase") == "blocked" for command in commands))
    ctx.shot(page, "retry_01_explicit_old_route_blocked")
    tap(page, "保留旧稿，另开新版", exact=True, wait=2500)
    if not check(
        "阻断重试后明确另开独立会话",
        _wait(
            page,
            lambda: (
                bool(_record(page, "draft", qid).get("attemptId"))
                and _record(page, "draft", qid).get("sessionId") != session1
            ),
        ),
    ):
        return
    fresh = _record(page, "draft", qid)
    session2, attempt2 = fresh["sessionId"], fresh["attemptId"]
    check(
        "新workspace空白且不借用其他稿",
        session2 != session1 and attempt2 not in (attempt1, other_id) and _selected(fresh) == [],
    )
    check("另开新版规范化URL删除旧显式关联", bound_route_ids(page.url) == (None, None))
    new_session = api.get(f"/sessions/{session2}")
    check(
        "新会话没有继承旧教学状态",
        all(
            new_session[field] is False
            for field in ("assisted", "used_solution", "independent_ended")
        ),
    )
    check(
        "新页不显示旧解析与提交反馈",
        "再试一次" not in all_text(page)
        and "常规解法" not in all_text(page)
        and "对照要点自查" not in all_text(page),
    )
    check(
        "原提交作答与另一稿均未改写",
        api.get(f"/attempts/{attempt1}") == old_attempt
        and api.get(f"/attempts/{attempt1}/draft") == old_draft
        and api.get(f"/attempts/{other_id}") == other
        and api.get(f"/attempts/{other_id}/draft") == other_draft,
    )
    check(
        "旧会话解析标记未被新workspace重置",
        api.get(f"/sessions/{session1}")["used_solution"] == old_session["used_solution"] is True,
    )
    ctx.shot(page, "retry_02_new_session")
    # Reload the actual canonical URL produced by the product, without repairing it in the test.
    current_route = "#" + urlsplit(page.url).fragment
    response_offset = len(page.responses)
    reopen(page, current_route)
    check(
        "刷新实际新URL仍恢复S2A2",
        _wait(
            page,
            lambda: (
                _record(page, "draft", qid).get("sessionId") == session2
                and _record(page, "draft", qid).get("attemptId") == attempt2
            ),
        ),
    )
    check(
        "刷新新稿为空且旧教学结果没有复活",
        _selected(_record(page, "draft", qid)) == []
        and "再试一次" not in all_text(page)
        and "常规解法" not in all_text(page),
    )
    reloaded = page.responses[response_offset:]
    check(
        "刷新真实读取新会话而非仅看到本机指针",
        any(
            method == "GET" and path.endswith(f"/sessions/{session2}") and status == 200
            for method, path, status in reloaded
        )
        and not any(
            method == "GET" and path.endswith(f"/sessions/{session1}")
            for method, path, _ in reloaded
        ),
    )
    check(
        "新会话没有自动请求辅导",
        not any(
            method == "POST" and f"/tutor/sessions/{session2}/" in path
            for method, path, _ in page.responses
        ),
    )
    check("新作答仍未提交", api.get(f"/attempts/{attempt2}")["status"] == "draft")
    check(
        "该场景只明确提交原作答一次",
        sum(method == "POST" and path.endswith("/submit") for method, path, _ in page.responses)
        == 1,
    )
    check("新场景页面没有未捕获异常", not page.errors, page.errors)
    ctx.shot(page, "retry_03_canonical_reload")


def run(ctx):
    for endpoint in ("sessions", "attempts"):
        _scenario(ctx, endpoint)
    _version_scenario(ctx)
    _blocked_retry_scenario(ctx)


FLOW = Flow(
    name="student_creation_recovery",
    title="创建丢响应、版本冲突及重试阻断后新workspace刷新恢复",
    needs=frozenset({"flutter"}),
    run=run,
)
