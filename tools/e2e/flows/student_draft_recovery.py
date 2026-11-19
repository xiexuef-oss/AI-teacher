"""真实409、双份本机留档、刷新与API离线重载、明确选择及本机副本恢复。

只读取产品存储作为证据，不写入存储。另一端更新通过真实API产生。
API离线使用浏览器路由中断，Flutter静态资源仍可加载，并非整机断网验收。
"""

from __future__ import annotations

import json
import re
import time

from e2e import data
from e2e.api_client import Api
from e2e.browser import (
    all_text,
    is_disabled,
    labels,
    onboard,
    open_flutter,
    reopen,
    stored,
    stored_all,
    tap,
)
from e2e.checks import say
from e2e.flowbase import Context, Flow
from e2e.servers import API_URL

KEY = "math-mono-quadratic"


def _record(page, kind: str, question_id: str, attempt_id: str | None = None) -> dict:
    """Read scoped product records, falling back to preserved legacy data only."""
    values = stored_all(page)

    def read(suffix):
        for key, raw in values.items():
            if key.endswith(suffix):
                value = json.loads(raw)
                return json.loads(value) if isinstance(value, str) else value
        return {}

    bundle = read(f"/draft-bundle/{question_id}")
    # Explicit null is authoritative; only older bundles use the legacy pointer.
    active = bundle["active"] if "active" in bundle else read(f"/active/{question_id}")
    active = active or {}
    target = attempt_id or active.get("attemptId")
    if target:
        if kind == "draft":
            value = bundle.get("drafts", {}).get(f"attempt/{target}")
            if value is not None:
                return value
        if kind == "draft-recovery":
            value = read(f"/draft-recovery/{question_id}/attempt/{target}")
            if value:
                return value
    legacy = read(f"/{kind}/{question_id}")
    if kind == "draft" and target and legacy.get("attemptId") != target:
        return {}
    return legacy


def _wait(page, predicate, *, seconds: float = 20) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        page.wait_for_timeout(200)
    return False


def _selected(draft: dict) -> list[str]:
    return (draft.get("answer") or {}).get("selected", [])


def _restore_first(page) -> None:
    tap(page, "查看并恢复", wait=700)
    # DropdownButton 的菜单角色随 Flutter 语义实现变化，按实际角色选择同一个可见条目。
    for role in ("menuitem", "option", "button"):
        candidate = page.get_by_role(role, name=re.compile(r"^1 ·"))
        if candidate.count():
            candidate.first.click()
            page.wait_for_timeout(1000)
            return
    # 部分版本给菜单项分配通用语义节点，文字仍由真实页面渲染。
    page.get_by_text(re.compile(r"^1 ·")).last.click()
    page.wait_for_timeout(1000)


def run(ctx: Context) -> None:
    check = ctx.check
    question_id = data.question_id(KEY)
    first, cloud, local = [option["key"] for option in data.question(KEY)["content"]["options"]][:3]
    page = ctx.new_page()
    requests: list[tuple[str, str]] = []
    page.on(
        "request",
        lambda request: (
            requests.append((request.method, request.url.split("?")[0]))
            if request.url.startswith(API_URL)
            else None
        ),
    )

    say("== 引导、打开自编单选样题，先保存一份正常草稿")
    open_flutter(page)
    onboard(page)
    tap(page, "练习", wait=2500)
    tap(page, data.title_of(KEY), wait=3500)
    token = stored(page, "auth.token")
    if not check("本地Mock学生身份已就绪（凭据不输出）", bool(token)):
        return
    api = Api(token)
    tap(page, f"选项 {first}")
    if not check(
        "页面草稿已正常同步",
        _wait(
            page,
            lambda: any(
                method == "PUT" and path.endswith("/draft") and status == 200
                for method, path, status in page.responses
            ),
        ),
    ):
        return
    draft = _record(page, "draft", question_id)
    attempt_id = draft.get("attemptId")
    if not check("读取真实页面保存的作答关联", bool(attempt_id)):
        return
    # go_router 的 imperative push 默认不反映在浏览器URL，明确使用题目公开路由。
    solve_path = f"#/questions/{question_id}/solve?origin=practice"
    draft_path = f"/attempts/{attempt_id}/draft"

    say("== 另一端通过实际API改选，再由本页面编辑触发真实409")
    before = api.get(draft_path)
    other = api.request(
        "PUT",
        draft_path,
        {
            "base_revision": before["revision"],
            "answer": {"selected_options": [cloud]},
        },
    )
    tap(page, f"选项 {local}")
    if not check(
        "实际409与冲突横幅出现",
        _wait(
            page,
            lambda: (
                "这份草稿在别处有了更新" in all_text(page)
                and any(
                    method == "PUT" and path.endswith("/draft") and status == 409
                    for method, path, status in page.responses
                )
            ),
        ),
    ):
        return
    if not check(
        "双方完整写入本机恢复记录",
        _wait(page, lambda: bool(_record(page, "draft-recovery", question_id).get("pending"))),
    ):
        return
    recovery = _record(page, "draft-recovery", question_id)
    copies = recovery.get("copies", [])
    check(
        "留档本机稿与另一端稿均存在且不同",
        len(copies) >= 2 and _selected(copies[0]) == [local] and _selected(copies[1]) == [cloud],
    )
    check("冲突时提交被阻止", is_disabled(page.get_by_role("button", name="提交", exact=True)))
    check("冲突没有覆盖云端", api.get(draft_path) == other)
    ctx.shot(page, "01_conflict")

    say("== 刷新恢复待解决冲突，不能自动同步")
    writes = sum(method == "PUT" and path.endswith("/draft") for method, path in requests)
    reopen(page, solve_path)
    check(
        "刷新仍显示双方冲突",
        "这份草稿在别处有了更新" in all_text(page)
        and f"选了 {local}" in all_text(page)
        and f"选了 {cloud}" in all_text(page),
    )
    check("刷新保留待解决记录及全部副本", _record(page, "draft-recovery", question_id) == recovery)
    ctx.shot(page, "02_reloaded")

    say("== 仅阻断浏览器API，静态页面照常加载：离线重载仍恢复双方")
    pattern = API_URL + "/**"

    def offline(route):
        route.abort("internetdisconnected")

    page.context.route(pattern, offline)
    try:
        reopen(page, solve_path)
        text = all_text(page)
        check(
            "API离线重载后冲突及本机稿仍在",
            "这份草稿在别处有了更新" in text
            and f"选了 {local}" in text
            and f"选了 {cloud}" in text,
        )
        check("API离线仍禁止提交", is_disabled(page.get_by_role("button", name="提交", exact=True)))
        check(
            "API离线重载没有清理或改写留档",
            _record(page, "draft-recovery", question_id) == recovery,
        )
        ctx.shot(page, "03_api_offline_reloaded")
    finally:
        page.context.unroute(pattern, offline)
    # 超过产品4秒同步延迟及12秒断网重试间隔，不能靠短等待漏掉迟到上传。
    page.wait_for_timeout(13500)
    check(
        "网络恢复后没有新增草稿PUT",
        sum(method == "PUT" and path.endswith("/draft") for method, path in requests) == writes,
    )
    check("网络恢复后云端内容及revision未变", api.get(draft_path) == other)

    say("== 学生明确采用云端，再通过真实副本菜单恢复原本机稿")
    tap(page, "用云端的", wait=2000)
    check(
        "明确选择后冲突解除",
        "这份草稿在别处有了更新" not in all_text(page)
        and _record(page, "draft-recovery", question_id).get("pending") is False,
    )
    check("当前稿已采用云端选项", _selected(_record(page, "draft", question_id)) == [cloud])
    check("本机副本入口说明仅在此设备", "本机留档副本（仅保存在这台设备" in all_text(page))
    old_count = len(_record(page, "draft-recovery", question_id).get("copies", []))
    attempts = sum(method == "POST" and path.endswith("/attempts") for method, path in requests)
    _restore_first(page)
    check(
        "恢复菜单取回原本机稿",
        _wait(page, lambda: _selected(_record(page, "draft", question_id)) == [local]),
    )
    updated = _record(page, "draft-recovery", question_id).get("copies", [])
    check(
        "恢复前的当前云端稿也已留档",
        len(updated) == old_count + 2 and _selected(updated[old_count]) == [cloud],
    )
    check("真实界面选中恢复的选项", any(f"选项 {local}，已选" in label for label in labels(page)))
    page.wait_for_timeout(5000)
    check(
        "副本恢复没有新增服务端作答",
        sum(method == "POST" and path.endswith("/attempts") for method, path in requests)
        == attempts,
    )
    check(
        "副本恢复没有自动上传，服务器仍是另一端稿",
        api.get(draft_path) == other
        and sum(method == "PUT" and path.endswith("/draft") for method, path in requests) == writes,
    )
    ctx.shot(page, "04_local_copy_restored")
    check("页面没有未捕获的异常", not page.errors, page.errors)
    unexpected = [
        response
        for response in page.responses
        if response[2] >= 400
        and not (response[0] == "PUT" and response[1].endswith("/draft") and response[2] == 409)
    ]
    check("只出现预期409，没有其他错误响应", not unexpected, unexpected)


FLOW = Flow(
    name="student_draft_recovery",
    title="学生端冲突双份留档、刷新/API离线恢复与本机副本恢复",
    needs=frozenset({"flutter"}),
    run=run,
)
