"""Real page conflict → explicit server copy → scoped reload/list editing.

Only read localStorage as evidence. The other-device update uses the real API;
no copy is created by the test API, and no product storage is fabricated.
"""

from __future__ import annotations

from e2e import data
from e2e.api_client import Api
from e2e.browser import all_text, onboard, open_flutter, reopen, stored, tap
from e2e.flowbase import Context, Flow
from e2e.flows.student_draft_recovery import _record, _selected, _wait

KEY = "math-mono-quadratic"


class LostCopyResponse:
    """Execute the browser's real POST, then withhold its successful response."""

    def __init__(self):
        self.result = None
        self.key = None

    def __call__(self, route):
        response = route.fetch()
        if response.status != 201:
            route.fulfill(response=response)
            return
        self.result = response.json()["data"]
        self.key = route.request.headers.get("idempotency-key")
        route.abort("connectionclosed")


def run(ctx: Context) -> None:
    check = ctx.check
    qid = data.question_id(KEY)
    first, cloud, local = [o["key"] for o in data.question(KEY)["content"]["options"]][:3]
    page = ctx.new_page()
    copies = []
    copy_keys = []
    replay_headers = []

    def requested(request):
        if request.method == "POST" and request.url.endswith("/copies"):
            copy_keys.append(request.headers.get("idempotency-key"))

    page.on("request", requested)

    def capture(response):
        if (
            response.request.method == "POST"
            and response.url.endswith("/copies")
            and response.status == 201
        ):
            copies.append(response.json()["data"])
            replay_headers.append(response.headers.get("idempotency-replayed"))

    page.on("response", capture)
    open_flutter(page)
    onboard(page)
    tap(page, "练习", wait=2500)
    tap(page, data.title_of(KEY), wait=3500)
    api = Api(stored(page, "auth.token"))
    tap(page, f"选项 {first}")
    if not check(
        "页面已建立并同步原稿",
        _wait(
            page,
            lambda: (
                bool(_record(page, "draft", qid).get("attemptId"))
                and any(
                    m == "PUT" and p.endswith("/draft") and s == 200 for m, p, s in page.responses
                )
            ),
        ),
    ):
        return
    original = _record(page, "draft", qid)
    source_id, session_id = original["attemptId"], original["sessionId"]
    source_path = f"/attempts/{source_id}/draft"
    fixed_question = api.get(f"/sessions/{session_id}/question")
    before = api.get(source_path)
    cloud_draft = api.request(
        "PUT",
        source_path,
        {"base_revision": before["revision"], "answer": {"selected_options": [cloud]}},
    )
    tap(page, f"选项 {local}")
    if not check(
        "另一端实际更新触发409及第三选项",
        _wait(
            page,
            lambda: (
                "这份草稿在别处有了更新" in all_text(page)
                and any(
                    m == "PUT" and p.endswith("/draft") and s == 409 for m, p, s in page.responses
                )
            ),
        ),
    ):
        return
    lost = LostCopyResponse()
    pattern = "**/attempts/*/copies"
    page.context.route(pattern, lost, times=1)
    try:
        tap(page, "创建独立云端副本", wait=2000)
        if not check("服务端复制成功后响应确实丢失", _wait(page, lambda: lost.result is not None)):
            return
    finally:
        page.context.unroute(pattern, lost)
    pending = _record(page, "draft-bundle", qid).get("pending", {}).get(f"attempt/{source_id}", {})
    check(
        "丢响应后原pending键及完整输入仍落本机",
        bool(lost.key)
        and pending.get("idempotencyKey") == lost.key
        and _selected(pending.get("snapshot", {})) == [local],
    )
    created_id = lost.result["attempt"]["id"]
    check("响应丢失没有切走原稿", _record(page, "draft", qid).get("attemptId") == source_id)
    check(
        "响应丢失时服务端已只有一份来源副本",
        [
            r["attempt_id"]
            for r in api.get(f"/questions/{qid}/drafts")["items"]
            if r["copied_from_attempt_id"] == source_id
        ]
        == [created_id],
    )
    ctx.shot(page, "00_copy_response_lost")
    reopen(page, f"#/questions/{qid}/solve?origin=practice")
    restored_pending = (
        _record(page, "draft-bundle", qid).get("pending", {}).get(f"attempt/{source_id}", {})
    )
    check("刷新保留同一pending复制请求", restored_pending == pending)
    tap(page, "创建独立云端副本", wait=2000)
    if not check("页面实际创建服务端副本", _wait(page, lambda: bool(copies))):
        return
    result = copies[0]
    copy_id = result["attempt"]["id"]
    check(
        "刷新重试同key重放同一副本",
        copy_id == created_id
        and len(copy_keys) == 2
        and all(key == lost.key for key in copy_keys)
        and replay_headers == ["true"],
    )
    check(
        "重放未多建副本",
        [
            r["attempt_id"]
            for r in api.get(f"/questions/{qid}/drafts")["items"]
            if r["copied_from_attempt_id"] == source_id
        ]
        == [created_id],
    )
    copy_path = f"/attempts/{copy_id}/draft"
    check(
        "副本与原稿共享会话且ID不同", result["session"]["id"] == session_id and copy_id != source_id
    )
    check("创建未覆盖原稿", api.get(source_path) == cloud_draft)
    check(
        "副本保存本机选择且未提交",
        api.get(copy_path)["answer"]["selected_options"] == [local]
        and result["attempt"]["status"] == "draft",
    )
    check(
        "副本与原稿使用相同固定版本题面",
        api.get(f"/sessions/{session_id}/question") == fixed_question,
    )
    check(
        "副本成功切换当前本机槽",
        _wait(page, lambda: _record(page, "draft", qid).get("attemptId") == copy_id),
    )
    ctx.shot(page, "01_server_copy")
    # Reload the public question route without an explicit attempt: active pointer must win.
    reopen(page, f"#/questions/{qid}/solve?origin=practice")
    check(
        "刷新恢复确切副本而非默认原稿",
        _wait(
            page,
            lambda: (
                _record(page, "draft", qid).get("attemptId") == copy_id
                and _selected(_record(page, "draft", qid)) == [local]
            ),
        ),
    )
    refs = api.get(f"/questions/{qid}/drafts")["items"]
    by_id = {r["attempt_id"]: r for r in refs}
    check(
        "本人列表包含原稿及来源可追溯副本",
        source_id in by_id
        and copy_id in by_id
        and by_id[copy_id]["copied_from_attempt_id"] == source_id,
    )

    def open_from_list(attempt_id):
        # Reach the actual practice-card entry, then select its rendered metadata row.
        reopen(page, "#/practice")
        entry = page.get_by_role("button", name=f"云端草稿 · {data.title_of(KEY)}", exact=True)
        if not check("练习页目标题目的云端草稿入口可用", _wait(page, lambda: entry.count() == 1)):
            return False
        entry.click()
        ref = by_id[attempt_id]
        # ListTile exposes its title and subtitle as one actionable semantics node.
        tap(page, f"草稿 {ref['attempt_no']} · 题目版本 {ref['question_version']}")
        check(
            "列表选中明确作答槽",
            _wait(page, lambda: _record(page, "draft", qid).get("attemptId") == attempt_id),
        )
        return True

    if not open_from_list(source_id):
        return
    # The source scope still owns its unresolved local/cloud archive. Creating
    # another attempt does not silently resolve that source's conflict.
    if not check(
        "返回原稿仍保留其待选冲突",
        _wait(page, lambda: "这份草稿在别处有了更新" in all_text(page)),
    ):
        return
    check("待选原稿尚未覆盖服务器", api.get(source_path) == cloud_draft)
    tap(page, "用云端的", wait=2000)
    if not check(
        "明确采用云端后才解除原稿冲突",
        _wait(page, lambda: "这份草稿在别处有了更新" not in all_text(page)),
    ):
        return
    tap(page, f"选项 {first}")
    check(
        "原稿独立编辑并同步",
        _wait(page, lambda: api.get(source_path)["answer"]["selected_options"] == [first]),
    )
    check("编辑原稿未串到副本", api.get(copy_path)["answer"]["selected_options"] == [local])
    if not open_from_list(copy_id):
        return
    tap(page, f"选项 {cloud}")
    check(
        "副本独立编辑并同步",
        _wait(page, lambda: api.get(copy_path)["answer"]["selected_options"] == [cloud]),
    )
    check("编辑副本未串到原稿", api.get(source_path)["answer"]["selected_options"] == [first])
    check(
        "本机原稿及副本槽分别留存",
        _selected(_record(page, "draft", qid, source_id)) == [first]
        and _selected(_record(page, "draft", qid, copy_id)) == [cloud],
    )
    check(
        "全程没有自动提交",
        not any(m == "POST" and p.endswith("/submit") for m, p, _ in page.responses),
    )
    check("页面没有未捕获异常", not page.errors, page.errors)
    ctx.shot(page, "02_independent_edits")


FLOW = Flow(
    name="student_draft_copies",
    title="真实冲突创建独立云端副本、刷新及列表分槽编辑",
    needs=frozenset({"flutter"}),
    run=run,
)
