"""Real four-stage scan recovery with self-authored PNGs and no storage writes."""

from __future__ import annotations

import base64
import io
import json
import re

from e2e import data
from e2e.api_client import Api
from e2e.browser import onboard, open_flutter, reopen, stored, stored_all, tap, type_into
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _wait
from e2e.flows.student_scan import KEY, image_fixture
from e2e.servers import API_URL


class HoldScanResponse:
    def __init__(self):
        self.route = self.response = self.result = self.body = self.key = None

    def __call__(self, route):
        response = route.fetch()
        if response.status not in (200, 201, 202):
            route.fulfill(response=response)
            return
        self.route, self.response = route, response
        self.result = response.json()["data"]
        self.body = route.request.post_data_json
        self.key = route.request.headers.get("idempotency-key")

    def lose(self):
        self.route.abort("connectionclosed")
        self.route = None


def workspace(page):
    owner = stored(page, "auth.userId")
    raw = stored(page, f"u/{owner}/scan_workspace_bundle")
    if raw is None:
        return {}
    value = json.loads(raw)
    return next((w for w in value["workspaces"] if w["id"] == value["activeWorkspaceId"]), {})


def no_source_bytes(page):
    raw = "\n".join(stored_all(page).values())
    encoded = base64.b64encode(image_fixture()["buffer"]).decode("ascii")
    return encoded not in raw and "content_base64" not in raw


def _open(ctx, text="扫描文字保留"):
    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    reopen(page, "#/scan")
    type_into(page, page.get_by_role("textbox", name="手工填写题干"), text)
    return page, Api(stored(page, "auth.token"))


def _pick(page, image=None):
    with page.expect_file_chooser() as chosen:
        page.get_by_role("button", name="选择图片", exact=True).click()
    chosen.value.set_files(image_fixture() if image is None else image)
    page.wait_for_timeout(650)


def _upload(page):
    page.get_by_role("button", name=re.compile(r"^(上传临时图片|继续建立扫描)$")).click()


def _wire(page, method, path):
    writes, replies = [], []
    page.on(
        "request",
        lambda r: (
            writes.append((r.headers.get("idempotency-key"), r.post_data_json))
            if r.method == method and r.url == API_URL + path
            else None
        ),
    )
    page.on(
        "response",
        lambda r: (
            replies.append((r.status, r.headers.get("idempotency-replayed")))
            if r.request.method == method and r.url == API_URL + path
            else None
        ),
    )
    return writes, replies


def metadata_recovery(ctx):
    page, api = _open(ctx)
    _pick(page)
    path = "/scans/uploads"
    writes, replies = _wire(page, "POST", path)
    hold = HoldScanResponse()
    page.context.route(API_URL + path, hold, times=1)
    _upload(page)
    if not ctx.check(
        "上传metadata真实创建后回执丢失", _wait(page, lambda: hold.result is not None)
    ):
        return
    identifier = hold.result["media_id"]
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    reopen(page, "#/scan")
    ctx.check("metadata重启不自动上传", len(writes) == 1 and no_source_bytes(page))
    tap(page, "重试原操作", exact=True, wait=1000)
    ctx.check(
        "无原图也能原key原body恢复metadata",
        _wait(page, lambda: (201, "true") in replies)
        and len(writes) == 2
        and writes[0] == writes[1]
        and workspace(page).get("mediaId") == identifier,
    )
    ctx.check(
        "恢复metadata不伪称内容或扫描已完成",
        workspace(page).get("scanId") is None
        and not any(
            c["kind"] in {"content", "create"} for c in workspace(page).get("commands", [])
        ),
    )
    _pick(page)
    _upload(page)
    ctx.check(
        "重选原图明确继续并复用原媒体",
        _wait(page, lambda: bool(workspace(page).get("scanId")))
        and workspace(page)["mediaId"] == identifier
        and len(writes) == 2,
    )
    ctx.check(
        "新扫描是真实本人资源且图像未落本机",
        api.get(f"/scans/{workspace(page)['scanId']}")["status"] == "needs_confirmation"
        and no_source_bytes(page),
    )
    ctx.shot(page, "scan_recovery_01_metadata")


def content_recovery(ctx):
    page, _ = _open(ctx)
    _pick(page)
    hold = HoldScanResponse()
    pattern = API_URL + "/scans/uploads/*/content"
    page.context.route(pattern, hold, times=1)
    _upload(page)
    if not ctx.check("图片内容真实写入后回执丢失", _wait(page, lambda: hold.result is not None)):
        return
    path = hold.route.request.url.removeprefix(API_URL)
    writes, replies = _wire(page, "PUT", path)
    # The listener starts after the original request; include the observed real wire.
    original = (hold.key, hold.body)
    hold.lose()
    page.context.unroute(pattern, hold)
    reopen(page, "#/scan")
    ctx.check(
        "content重启未重发且没有图片body落盘",
        not writes
        and no_source_bytes(page)
        and all(
            c.get("body") is None for c in workspace(page)["commands"] if c["kind"] == "content"
        ),
    )
    from PIL import Image

    output = io.BytesIO()
    with Image.new("RGB", (128, 128), color="black") as image:
        image.save(output, format="PNG")
    _pick(
        page,
        {
            "name": "different-self-authored.png",
            "mimeType": "image/png",
            "buffer": output.getvalue(),
        },
    )
    tap(page, "重试原操作", exact=True, wait=500)
    ctx.check("不同原图不能重用原content意图", not writes and workspace(page).get("scanId") is None)
    _pick(page)
    tap(page, "重试原操作", exact=True, wait=1000)
    ctx.check(
        "同字节原图重建同body同key重放内容",
        _wait(page, lambda: (200, "true") in replies) and writes == [original],
    )
    ctx.check("内容回执不自动冒充scan创建", workspace(page).get("scanId") is None)
    _upload(page)
    ctx.check(
        "学生明确继续才创建扫描",
        _wait(page, lambda: bool(workspace(page).get("scanId"))) and no_source_bytes(page),
    )
    ctx.shot(page, "scan_recovery_02_content")


def scan_creation_recovery(ctx):
    page, api = _open(ctx)
    _pick(page)
    path = "/scans"
    writes, replies = _wire(page, "POST", path)
    hold = HoldScanResponse()
    page.context.route(API_URL + path, hold, times=1)
    _upload(page)
    if not ctx.check(
        "Scan真实202创建成功但响应未交付", _wait(page, lambda: hold.result is not None)
    ):
        return
    identifier = hold.result["id"]
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    reopen(page, "#/scan")
    ctx.check("扫描创建刷新不自动重试", len(writes) == 1)
    tap(page, "重试原操作", exact=True, wait=1000)
    ctx.check(
        "无原图恢复同一真实scanId与原命令",
        _wait(page, lambda: (202, "true") in replies)
        and len(writes) == 2
        and writes[0] == writes[1]
        and workspace(page).get("scanId") == identifier,
    )
    ctx.check(
        "恢复资源仍需确认且不自动练习",
        api.get(f"/scans/{identifier}")["status"] == "needs_confirmation"
        and not any(m == "POST" and p in {"/sessions", "/attempts"} for m, p, _ in page.responses),
    )
    ctx.shot(page, "scan_recovery_03_creation")


def confirmation_recovery(ctx):
    first = data.question(KEY)["content"]["stem"]
    second = first + "（本机续改保留）"
    page, api = _open(ctx, first)
    _pick(page)
    _upload(page)
    if not ctx.check(
        "确认前真实scan已建立", _wait(page, lambda: bool(workspace(page).get("scanId")))
    ):
        return
    identifier = workspace(page)["scanId"]
    path = f"/scans/{identifier}/confirm"
    writes, replies = _wire(page, "POST", path)
    hold = HoldScanResponse()
    page.context.route(API_URL + path, hold, times=1)
    tap(page, "确认题干并匹配已有题目", exact=True, wait=500)
    if not ctx.check(
        "A真实确认匹配题目但回执仍在途",
        _wait(page, lambda: hold.result is not None)
        and hold.result["question_id"] == data.question_id(KEY),
    ):
        return
    field = page.get_by_role("textbox", name="手工填写题干")
    field.click()
    page.wait_for_timeout(300)
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.press("Backspace")
    type_into(page, field, second)
    ctx.check(
        "确认A未决时B文字先存本机", _wait(page, lambda: workspace(page).get("stem") == second)
    )
    hold.lose()
    page.context.unroute(API_URL + path, hold)
    reopen(page, "#/scan")
    ctx.check("B重启保留且不自动确认", workspace(page).get("stem") == second and len(writes) == 1)
    tap(page, "重试原操作", exact=True, wait=1000)
    ctx.check(
        "明确恢复仍重放A完整原body和原key",
        _wait(page, lambda: (200, "true") in replies)
        and len(writes) == 2
        and writes[0] == writes[1]
        and writes[1][1]["stem_text"] == first,
    )
    ctx.check(
        "A回执不覆盖B或把A匹配当B结果",
        workspace(page).get("stem") == second
        and page.get_by_role("button", name="开始练习", exact=True).count() == 0
        and api.get(f"/scans/{identifier}")["stem_text"] == first,
    )
    ctx.check(
        "确认恢复没有自动创建练习或保存原图",
        no_source_bytes(page)
        and not any(m == "POST" and p in {"/sessions", "/attempts"} for m, p, _ in page.responses),
    )
    ctx.shot(page, "scan_recovery_04_confirmation_B_retained")


def run(ctx):
    metadata_recovery(ctx)
    content_recovery(ctx)
    scan_creation_recovery(ctx)
    confirmation_recovery(ctx)
    for page in ctx.pages:
        ctx.check("扫描恢复页面没有未捕获异常", not page.errors, page.errors)


FLOW = Flow(
    name="student_scan_recovery",
    title="扫描四阶段真实丢响应、原图重选与确认续稿恢复",
    needs=frozenset({"flutter"}),
    run=run,
)
