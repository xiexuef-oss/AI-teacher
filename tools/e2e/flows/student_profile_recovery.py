"""Real profile receipts, local edits and explicit revision conflict recovery."""

from __future__ import annotations

import json

from e2e.api_client import Api
from e2e.browser import all_text, onboard, open_flutter, reopen, stored, tap, type_into
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _wait
from e2e.flows.student_write_recovery import HoldWriteResponse
from e2e.servers import API_URL


def profile_bundle(page, owner):
    raw = stored(page, f"u/{owner}/profile_bundle")
    return {} if raw is None else json.loads(raw)


def read_name(page):
    # Flutter's unfocused semantic input is a proxy. Focus through the real UI
    # before reading the connected native editor; never set DOM value/text.
    field = page.get_by_role("textbox", name="你的称呼")
    before = field.input_value()
    field.click()
    page.wait_for_timeout(300)
    after = field.input_value()
    readings = getattr(page, "profile_field_readings", [])
    readings.append(
        {
            "before_focus": before,
            "after_focus": after,
            "attributes": field.evaluate(
                "e => Object.fromEntries(Array.from(e.attributes).map(a => [a.name, a.value]))"
            ),
        }
    )
    page.profile_field_readings = readings
    return after


def _name(page, value):
    field = page.get_by_role("textbox", name="你的称呼")
    field.click()
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.press("Backspace")
    type_into(page, field, value)


def _open(ctx):
    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    reopen(page, "#/profile")
    return page, Api(stored(page, "auth.token")), stored(page, "auth.userId")


def _lost_receipt(ctx):
    page, api, owner = _open(ctx)
    before = api.get("/profile")
    hold = HoldWriteResponse()
    writes, receipts = [], []

    def route(request):
        if request.request.method == "PUT":
            hold(request)
        else:
            request.continue_()

    def request_seen(request):
        if request.method == "PUT" and request.url == API_URL + "/profile":
            writes.append((request.headers.get("idempotency-key"), request.post_data_json))

    def response_seen(response):
        if response.request.method == "PUT" and response.url == API_URL + "/profile":
            receipts.append((response.status, response.headers.get("idempotency-replayed")))

    page.on("request", request_seen)
    page.on("response", response_seen)
    page.context.route(API_URL + "/profile", route, times=1)
    _name(page, "资料A")
    tap(page, "保存", exact=True, wait=500)
    if not ctx.check("资料A真实保存但回执尚未交付", _wait(page, lambda: hold.result is not None)):
        return
    ctx.check("保存携带真实版本条件", hold.body["expected_revision"] == before["revision"])
    _name(page, "续改B")
    ctx.check(
        "回执在途新编辑B先落本机",
        _wait(
            page, lambda: profile_bundle(page, owner).get("edit", {}).get("display_name") == "续改B"
        ),
    )
    hold.lose()
    page.context.unroute(API_URL + "/profile", route)
    reopen(page, "#/profile")
    page.wait_for_timeout(13500)
    ctx.check("刷新没有自动重发资料PUT", len(writes) == 1)
    ctx.check(
        "刷新同时保留云端A与本机B",
        api.get("/profile")["display_name"] == "资料A" and read_name(page) == "续改B",
    )
    tap(page, "重试原保存", exact=True, wait=1200)
    ctx.check("明确重试取得原成功回执", _wait(page, lambda: (200, "true") in receipts))
    ctx.check("重试复用完整原body和原key", len(writes) == 2 and writes[0] == writes[1])
    ctx.check("重放不再增加资料版本", api.get("/profile")["revision"] == before["revision"] + 1)
    ctx.check(
        "原A回执不覆盖新编辑B",
        read_name(page) == "续改B",
    )
    tap(page, "保存", exact=True, wait=1200)
    ctx.check(
        "明确保存B使用新key和新版本条件",
        len(writes) == 3
        and writes[2][0] != writes[0][0]
        and writes[2][1]["expected_revision"] == before["revision"] + 1,
    )
    ctx.check(
        "B实际保存且只再增加一个版本",
        api.get("/profile")["display_name"] == "续改B"
        and api.get("/profile")["revision"] == before["revision"] + 2,
    )
    reopen(page, "#/profile")
    ctx.check("再次刷新恢复已保存B", read_name(page) == "续改B")
    ctx.shot(page, "profile_01_lost_receipt_recovered")


def _conflict(ctx):
    page, api, owner = _open(ctx)
    initial = api.get("/profile")
    _name(page, "本机保留")
    if not ctx.check(
        "冲突前本机编辑已落盘",
        _wait(
            page,
            lambda: profile_bundle(page, owner).get("edit", {}).get("display_name") == "本机保留",
        ),
    ):
        return
    fields = {
        key: initial[key] for key in ("region_code", "grade", "subjects", "curriculum_version")
    }
    other = api.request(
        "PUT",
        "/profile",
        {**fields, "display_name": "他端更新", "expected_revision": initial["revision"]},
    )
    tap(page, "保存", exact=True, wait=1200)
    ctx.check(
        "过期版本实际409且保留双方",
        ("PUT", "/profile", 409) in page.responses
        and "本机保留" in all_text(page)
        and "他端更新" in all_text(page),
    )
    ctx.check(
        "冲突未覆盖云端或清除本机",
        api.get("/profile")["revision"] == other["revision"]
        and api.get("/profile")["display_name"] == "他端更新"
        and profile_bundle(page, owner).get("edit", {}).get("display_name") == "本机保留",
    )
    reopen(page, "#/profile")
    ctx.check("冲突双方跨刷新保留", "本机保留" in all_text(page) and "他端更新" in all_text(page))
    tap(page, "保留本机编辑，再次保存", exact=True, wait=800)
    ctx.check("选择本机尚不自动覆盖云端", api.get("/profile")["display_name"] == "他端更新")
    tap(page, "保存", exact=True, wait=1200)
    ctx.check(
        "明确新intent按新版本保存本机",
        api.get("/profile")["display_name"] == "本机保留"
        and api.get("/profile")["revision"] == other["revision"] + 1,
    )
    ctx.shot(page, "profile_02_conflict_resolved")


def _refresh_conflict(ctx):
    page, api, owner = _open(ctx)
    initial = api.get("/profile")
    writes = []
    page.on(
        "request",
        lambda request: (
            writes.append(request.post_data_json)
            if request.method == "PUT" and request.url == API_URL + "/profile"
            else None
        ),
    )
    _name(page, "未提交旧编辑")
    if not ctx.check(
        "未提交编辑固定原版本来源",
        _wait(
            page,
            lambda: (
                profile_bundle(page, owner).get("editBaseRevision") == initial["revision"]
                and profile_bundle(page, owner).get("edit", {}).get("display_name")
                == "未提交旧编辑"
            ),
        ),
    ):
        return
    fields = {
        key: initial[key] for key in ("region_code", "grade", "subjects", "curriculum_version")
    }
    other = api.request(
        "PUT",
        "/profile",
        {**fields, "display_name": "刷新前他端新资料", "expected_revision": initial["revision"]},
    )
    reopen(page, "#/profile")
    ctx.check(
        "GET新版本不把旧编辑自动重基",
        not writes
        and profile_bundle(page, owner).get("editBaseRevision") == initial["revision"]
        and profile_bundle(page, owner).get("cloud", {}).get("revision") == other["revision"],
    )
    ctx.check(
        "无prepared命令也展示双方选择",
        "未提交旧编辑" in all_text(page)
        and "刷新前他端新资料" in all_text(page)
        and page.get_by_role("button", name="采用云端资料", exact=True).count() == 1,
    )
    tap(page, "采用云端资料", exact=True, wait=800)
    ctx.check(
        "显式采用云端不发PUT且恢复其表单",
        not writes
        and read_name(page) == "刷新前他端新资料"
        and api.get("/profile")["revision"] == other["revision"],
    )
    ctx.shot(page, "profile_03_refresh_keeps_edit_origin")


def _offline_restart(ctx):
    page, api, owner = _open(ctx)
    initial = api.get("/profile")

    def offline(route):
        route.abort("internetdisconnected")

    page.context.route(API_URL + "/**", offline)
    reopen(page, "#/profile")
    ctx.check(
        "完整离线刷新用缓存配置显示资料表单",
        page.get_by_role("textbox", name="你的称呼").count() == 1,
    )
    if not page.get_by_role("textbox", name="你的称呼").count():
        return
    _name(page, "离线新编辑")
    ctx.check(
        "离线编辑先落本机且保留来源版本",
        _wait(
            page,
            lambda: (
                profile_bundle(page, owner).get("edit", {}).get("display_name") == "离线新编辑"
                and profile_bundle(page, owner).get("editBaseRevision") == initial["revision"]
            ),
        ),
    )
    reopen(page, "#/profile")
    ctx.check(
        "离线再次重启不丢新编辑",
        read_name(page) == "离线新编辑",
    )
    page.context.unroute(API_URL + "/**", offline)
    ctx.check("离线编辑未擅自写云端", api.get("/profile")["revision"] == initial["revision"])
    reopen(page, "#/profile")
    tap(page, "保存", exact=True, wait=1200)
    ctx.check(
        "恢复联网后明确保存原编辑",
        api.get("/profile")["display_name"] == "离线新编辑"
        and api.get("/profile")["revision"] == initial["revision"] + 1,
    )
    ctx.shot(page, "profile_04_offline_restart")


def _account_switch(ctx):
    page, api, owner = _open(ctx)
    hold = HoldWriteResponse()

    def route(request):
        if request.request.method == "PUT":
            hold(request)
        else:
            request.continue_()

    page.context.route(API_URL + "/profile", route, times=1)
    _name(page, "旧账号保存")
    tap(page, "保存", exact=True, wait=500)
    if not ctx.check("切号前旧账号真实保存回执在途", _wait(page, lambda: hold.result is not None)):
        return
    tap(page, "切换到家长身份", wait=1800)
    parent = stored(page, "auth.userId")
    ctx.check(
        "保存未决时切换到隔离家长身份", parent != owner and stored(page, "auth.role") == "parent"
    )
    hold.release()
    page.context.unroute(API_URL + "/profile", route)
    ctx.check(
        "旧账号回执仅落原账号记录",
        _wait(
            page,
            lambda: any(
                c.get("phase") == "acked" and c.get("idempotencyKey") == hold.key
                for c in profile_bundle(page, owner).get("commands", [])
            ),
        ),
    )
    ctx.check(
        "迟到回执不污染新身份或资料缓存",
        stored(page, "auth.userId") == parent
        and stored(page, "auth.role") == "parent"
        and stored(page, f"u/{parent}/profile_bundle") is None
        and stored(page, f"u/{parent}/profile") is None
        and page.get_by_role("textbox", name="你的称呼").count() == 0,
    )
    tap(page, "切换到学生身份", wait=1800)
    reopen(page, "#/profile")
    ctx.check(
        "切回原身份仍可读取自己实际保存结果",
        stored(page, "auth.userId") == owner
        and read_name(page) == "旧账号保存"
        and api.get("/profile")["display_name"] == "旧账号保存",
    )
    ctx.shot(page, "profile_05_account_switch")


def run(ctx):
    _lost_receipt(ctx)
    _conflict(ctx)
    _refresh_conflict(ctx)
    _offline_restart(ctx)
    _account_switch(ctx)
    for index, page in enumerate(ctx.pages):
        (ctx.out_dir / f"profile-field-readings-{index}.json").write_text(
            json.dumps(getattr(page, "profile_field_readings", []), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ctx.check("资料恢复页面没有未捕获异常", not page.errors, page.errors)


FLOW = Flow(
    name="student_profile_recovery",
    title="资料固定命令丢响应、续改与版本冲突恢复",
    needs=frozenset({"flutter"}),
    run=run,
)
