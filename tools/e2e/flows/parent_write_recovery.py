"""Fresh Mock accounts: real parent receipts and authorization generations.

Only reads product storage. Codes remain in process memory, never diagnostics.
"""

from __future__ import annotations

import json
import urllib.request

from e2e.api_client import Api
from e2e.browser import all_text, onboard, open_flutter, reopen, stored, stored_all, tap, type_into
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _wait
from e2e.flows.student_write_recovery import HoldWriteResponse
from e2e.servers import API_URL


def bundle(page, owner, role="student"):
    raw = stored(page, f"u/{owner}/parent_authorization_bundle/{role}")
    return {} if raw is None else json.loads(raw)


def no_plaintext_code(page, code):
    raw = "\n".join(stored_all(page).values())
    return code not in raw and code.lower() not in raw and f"{code[:5]} {code[5:]}" not in raw


def student(ctx):
    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    reopen(page, "#/profile")
    return page, Api(stored(page, "auth.token")), stored(page, "auth.userId")


def parent_api():
    request = urllib.request.Request(
        API_URL + "/dev/local-identities?role=parent",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        identity = json.load(response)["data"]
    return Api(identity["access_token"])


def generate(api):
    state = api.get("/me/parent-links")
    return api.post(
        "/me/parent-invites", {"expected_parent_invite_revision": state["parent_invite_revision"]}
    )


def _wire(page, path):
    writes, replies = [], []
    page.on(
        "request",
        lambda request: (
            writes.append((request.headers.get("idempotency-key"), request.post_data_json))
            if request.method == "POST" and request.url == API_URL + path
            else None
        ),
    )
    page.on(
        "response",
        lambda response: (
            replies.append((response.status, response.headers.get("idempotency-replayed")))
            if response.request.method == "POST" and response.url == API_URL + path
            else None
        ),
    )
    return writes, replies


def lost_generation(ctx):
    page, api, owner = student(ctx)
    before = api.get("/me/parent-links")["parent_invite_revision"]
    path = "/me/parent-invites"
    writes, replies = _wire(page, path)
    hold = HoldWriteResponse()
    page.context.route(API_URL + path, hold, times=1)
    tap(page, "生成邀请码", exact=True, wait=500)
    if not ctx.check("邀请生成真实成功而回执在途", _wait(page, lambda: hold.result is not None)):
        return
    code, identifier = hold.result["code"], hold.result["id"]
    ctx.check("生成命令固定真实版本来源", hold.body == {"expected_parent_invite_revision": before})
    ctx.check(
        "生成前键和body已持久但无码",
        bool(bundle(page, owner).get("commands")) and no_plaintext_code(page, code),
    )
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    reopen(page, "#/profile")
    page.wait_for_timeout(1500)
    ctx.check(
        "重启不自动再生成且原邀请仍在",
        len(writes) == 1 and api.get("/me/parent-links")["pending_invite"]["id"] == identifier,
    )
    tap(page, "重试原操作", exact=True, wait=1200)
    ctx.check(
        "明确恢复原key原body与真实成功回执",
        _wait(page, lambda: (201, "true") in replies)
        and len(writes) == 2
        and writes[0] == writes[1],
    )
    ctx.check(
        "恢复不重复增加邀请版本",
        api.get("/me/parent-links")["parent_invite_revision"] == before + 1,
    )
    ctx.check(
        "仍有效原码只在页面临时重现",
        f"{code[:5]} {code[5:]}" in all_text(page) and no_plaintext_code(page, code),
    )
    tap(page, "我知道了", wait=500)
    ctx.check(
        "关闭后码不在界面或产品存储",
        code not in all_text(page)
        and f"{code[:5]} {code[5:]}" not in all_text(page)
        and no_plaintext_code(page, code),
    )
    ctx.shot(page, "parent_01_original_invitation_recovered")


def stale_first_delivery(ctx):
    page, api, owner = student(ctx)
    hold = HoldWriteResponse()
    path = "/me/parent-invites"
    writes, _ = _wire(page, path)
    page.context.route(API_URL + path, hold, times=1)
    tap(page, "生成邀请码", exact=True, wait=500)
    if not ctx.check("旧邀请码首次响应已在途", _wait(page, lambda: hold.result is not None)):
        return
    old_code = hold.result["code"]
    newer = generate(api)
    hold.release()
    page.context.unroute(API_URL + path, hold)
    ctx.check(
        "迟到旧响应不展示已被替代的码",
        _wait(
            page,
            lambda: (
                "上次生成操作已确认" in all_text(page) and page.get_by_role("dialog").count() == 0
            ),
        )
        and old_code not in all_text(page)
        and f"{old_code[:5]} {old_code[5:]}" not in all_text(page),
    )
    state = api.get("/me/parent-links")
    ctx.check(
        "旧回执不覆盖较新邀请或自动另建",
        len(writes) == 1
        and state["pending_invite"]["id"] == newer["id"]
        and state["parent_invite_revision"] == newer["parent_invite_revision"],
    )
    ctx.check(
        "旧新两码均未写入产品存储",
        no_plaintext_code(page, old_code) and no_plaintext_code(page, newer["code"]),
    )
    ctx.shot(page, "parent_02_stale_delivery_blocked")


def revoke_receipt_after_regrant(ctx):
    page, api, owner = student(ctx)
    parent = parent_api()
    first = generate(api)
    parent.post("/parents/links", {"code": first["code"]})
    initial = api.get("/me/parent-links")["links"][0]
    reopen(page, "#/profile")
    path = f"/me/parent-links/{initial['id']}/revoke"
    writes, replies = _wire(page, path)
    hold = HoldWriteResponse()
    page.context.route(API_URL + path, hold, times=1)
    tap(page, "撤销", exact=True, wait=500)
    tap(page, "撤销授权", exact=True, wait=500)
    if not ctx.check("原代撤销真实成功而响应未交付", _wait(page, lambda: hold.result is not None)):
        return
    replacement = generate(api)
    parent.post("/parents/links", {"code": replacement["code"]})
    current = api.get("/me/parent-links")["links"][0]
    ctx.check(
        "另一端重新授权复用ID但代际已变化",
        current["id"] == initial["id"]
        and current["authorization_revision"] == initial["authorization_revision"] + 2,
    )
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    reopen(page, "#/profile")
    ctx.check(
        "刷新没有重撤销新授权",
        len(writes) == 1 and len(parent.get("/parents/students")["items"]) == 1,
    )
    tap(page, "重试原操作", exact=True, wait=1200)
    ctx.check(
        "旧撤销原key原body仅重放历史结果",
        _wait(page, lambda: (200, "true") in replies)
        and len(writes) == 2
        and writes[0] == writes[1],
    )
    latest = api.get("/me/parent-links")["links"][0]
    ctx.check(
        "历史撤销回执不撤销当前新代",
        latest == current and len(parent.get("/parents/students")["items"]) == 1,
    )
    ctx.check(
        "真实界面仍显示当前授权的撤销入口",
        page.get_by_role("button", name="撤销", exact=True).count() == 1,
    )
    ctx.check(
        "授权恢复未把两份邀请码落盘",
        no_plaintext_code(page, first["code"]) and no_plaintext_code(page, replacement["code"]),
    )
    ctx.shot(page, "parent_03_old_revoke_preserves_regrant")


def lost_redemption(ctx):
    page, api, student_id = student(ctx)
    invite = generate(api)
    code = invite["code"]
    tap(page, "切换到家长身份", wait=1800)
    parent_id = stored(page, "auth.userId")
    parent = Api(stored(page, "auth.token"))
    path = "/parents/links"
    writes, replies = _wire(page, path)
    hold = HoldWriteResponse()
    page.context.route(API_URL + path, hold, times=1)
    field = page.get_by_role("textbox", name="邀请码")
    type_into(page, field, f"{code[:5].lower()}-{code[5:].lower()}")
    tap(page, "绑定", exact=True, wait=500)
    if not ctx.check("兑换真实成功而回执在途", _wait(page, lambda: hold.result is not None)):
        return
    ctx.check(
        "首次兑换wire已规范化且产品存储无码",
        hold.body == {"code": code}
        and no_plaintext_code(page, code)
        and bundle(page, parent_id, "parent").get("commands", [])[0].get("body") is None,
    )
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    reopen(page, "#/parent")
    ctx.check(
        "重启没有自动兑换且要求原码",
        _wait(
            page, lambda: page.get_by_role("button", name="重输原码并重试", exact=True).count() == 1
        )
        and len(writes) == 1,
    )
    different = ("2" if code[0] != "2" else "3") + code[1:]
    type_into(page, page.get_by_role("textbox", name="邀请码"), different)
    tap(page, "重输原码并重试", exact=True, wait=800)
    ctx.check("不同新码不能复用旧intent发请求", len(writes) == 1)
    field = page.get_by_role("textbox", name="邀请码")
    field.click()
    page.wait_for_timeout(300)
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.press("Backspace")
    type_into(page, field, f"{code[:5].lower()} {code[5:].lower()}")
    ctx.check(
        "重输字段实际包含匹配原码",
        field.input_value().replace(" ", "").replace("-", "").upper() == code,
    )
    tap(page, "重输原码并重试", exact=True, wait=1200)
    ctx.check(
        "重输匹配原码才原key原body重放",
        _wait(page, lambda: (201, "true") in replies)
        and len(writes) == 2
        and writes[0] == writes[1],
    )
    ctx.check(
        "绑定仍只有原学生的一份真实授权",
        [x["student_id"] for x in parent.get("/parents/students")["items"]] == [student_id],
    )
    ctx.check("兑换恢复全程未把原码写本机", no_plaintext_code(page, code))
    ctx.shot(page, "parent_04_original_code_reentered")


def run(ctx):
    lost_generation(ctx)
    stale_first_delivery(ctx)
    revoke_receipt_after_regrant(ctx)
    lost_redemption(ctx)
    for page in ctx.pages:
        ctx.check("家长恢复页面无未捕获异常", not page.errors, page.errors)


FLOW = Flow(
    name="parent_write_recovery",
    title="家长邀请与撤销原键恢复、跨代保护及敏感兑换重输",
    needs=frozenset({"flutter"}),
    run=run,
)
