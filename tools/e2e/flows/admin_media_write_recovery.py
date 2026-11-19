"""Isolated real-browser media recovery acceptance; no auth in artifacts."""

import json
import re

from e2e._paths import REPO_ROOT
from e2e.flowbase import Flow
from e2e.flows.admin_question_recovery import _login, _open, _open_editor, _saved
from support.documents import png_image


def scenario(ctx):
    page, owner, api = _login(ctx)
    payload = json.loads(
        (REPO_ROOT / "apps/admin_web/public/examples/question-import.json").read_text(
            encoding="utf-8"
        )
    )
    question = api.post("/admin/question-imports", payload)
    _open(page, question["id"])
    _open_editor(page)
    media = page.get_by_test_id("editor").get_by_test_id("media-attachments")
    ctx.check("真实WebLocks可用", page.evaluate("typeof navigator.locks?.request==='function'"))
    requests = []
    dropped = []

    def intercept(route):
        req = route.request
        if req.method != "POST":
            route.continue_()
            return
        response = route.fetch()
        requests.append(
            {
                "path": req.url.split("/api/v1")[-1],
                "key": req.headers.get("idempotency-key"),
                "body": json.loads(req.post_data),
                "status": response.status,
                "replayed": response.headers.get("idempotency-replayed"),
            }
        )
        if not dropped:
            dropped.append(response.json()["data"])
            route.abort()
        else:
            route.fulfill(response=response)

    page.route("**/media/*/confirm", intercept)
    media.get_by_label("上传PNG/JPEG/WebP", exact=True).set_input_files(
        {"name": "self-authored-recovery.png", "mimeType": "image/png", "buffer": png_image()}
    )
    media.get_by_test_id("media-local-status").filter(has_text="结果未知").wait_for()
    ctx.check("确认已真实成功但完整响应被丢弃", len(dropped) == 1 and requests[0]["status"] == 200)
    ctx.check("丢失确认未自动加入题目草稿", media.get_by_label("附件说明", exact=True).count() == 0)
    page.reload()
    _open_editor(page)
    media = page.get_by_test_id("editor").get_by_test_id("media-attachments")
    history = media.get_by_test_id("media-history")
    history.get_by_text(re.compile(r"confirm (prepared|unavailable)")).wait_for()
    ctx.check("刷新未自动补发确认", len(requests) == 1)
    # Routing survives page reload; real store decides which command is eligible.
    row = (
        history.locator("div")
        .filter(has=page.locator("span", has_text=re.compile(r"confirm (prepared|unavailable)")))
        .last
    )
    row.get_by_role("button", name="恢复原命令", exact=True).click()
    history.get_by_role("button", name="仅确认本机历史", exact=True).wait_for()
    ctx.check(
        "恢复确认复用原key及body",
        len(requests) == 2
        and requests[0]["key"] == requests[1]["key"]
        and requests[0]["body"] == requests[1]["body"],
    )
    ctx.check("服务端实际回放原成功确认", requests[1]["replayed"] == "true")
    history.get_by_role("button", name="仅确认本机历史", exact=True).click()
    history.get_by_test_id("choose-association-target").check()
    history.get_by_test_id("associate-media").click()
    media.get_by_label("附件说明", exact=True).wait_for()
    _saved(page, "edit")
    ctx.check(
        "恢复图片明确选目标后加入草稿", media.get_by_label("附件说明", exact=True).count() == 1
    )
    before = len(requests)
    page.reload()
    _open_editor(page)
    media = page.get_by_test_id("editor").get_by_test_id("media-attachments")
    media.get_by_label("附件说明", exact=True).wait_for()
    ctx.check(
        "父题目草稿刷新后保留附件且不补发确认",
        len(requests) == before and media.get_by_label("附件说明", exact=True).count() == 1,
    )
    ctx.shot(page, "01_parent_draft_recovered")
    page.get_by_test_id("comment").last.fill("自编媒体恢复验收：保存原附件引用")
    _saved(page, "edit")
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/versions")
    ) as saved:
        page.get_by_test_id("save").click()
    detail = saved.value.json()["data"]
    ctx.check(
        "父草稿附件真实保存为新题目版本",
        detail["content"]["attachments"][0]["media_id"] == dropped[0]["media_id"],
    )
    other, _, _ = _login(ctx)
    _open(other, question["id"])
    other.get_by_test_id("preview-media").first.click()
    box = other.get_by_test_id("confirm-viewed-media")
    other.wait_for_function(
        "()=>!document.querySelector('[data-testid=confirm-viewed-media]')?.disabled"
    )
    box.check()
    declarations = []

    def declaration_route(route):
        req = route.request
        if req.method != "POST":
            route.continue_()
            return
        response = route.fetch()
        declarations.append(
            {
                "key": req.headers.get("idempotency-key"),
                "body": json.loads(req.post_data),
                "status": response.status,
                "replayed": response.headers.get("idempotency-replayed"),
            }
        )
        if len(declarations) == 1:
            route.abort()
        else:
            route.fulfill(response=response)

    other.route("**/review-confirmations", declaration_route)
    other.get_by_test_id("declare-media-review").click()
    other.get_by_test_id("media-history").get_by_text(
        re.compile(r"declaration (prepared|unavailable)")
    ).wait_for()
    ctx.check(
        "独立审校声明已真实成功但响应丢失",
        len(declarations) == 1 and declarations[0]["status"] == 200,
    )
    other.reload()
    other.get_by_test_id("media-history").get_by_text(
        re.compile(r"declaration (prepared|unavailable)")
    ).wait_for()
    ctx.check("重载未自动补发声明", len(declarations) == 1)
    other.get_by_test_id("media-history").get_by_role(
        "button", name="恢复原命令", exact=True
    ).click()
    other.get_by_test_id("media-history").get_by_role(
        "button", name="仅确认本机历史", exact=True
    ).wait_for()
    ctx.check(
        "声明原key和固定版本body真实重放",
        len(declarations) == 2
        and declarations[0]["key"] == declarations[1]["key"]
        and declarations[0]["body"] == declarations[1]["body"]
        and declarations[1]["replayed"] == "true",
    )
    other.get_by_test_id("media-history").get_by_role(
        "button", name="仅确认本机历史", exact=True
    ).click()
    other.get_by_test_id("media-history").get_by_text("declaration acked", exact=False).wait_for()
    ctx.check("仅本机ACK不额外发送声明", len(declarations) == 2)
    ctx.shot(other, "02_declaration_recovered")
    (ctx.out_dir / "safe_requests.json").write_text(
        json.dumps(requests, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ctx.out_dir / "safe_declarations.json").write_text(
        json.dumps(declarations, ensure_ascii=False, indent=2), encoding="utf-8"
    )


FLOW = Flow(
    "admin_media_write_recovery", "媒体确认与独立审校声明写命令恢复", frozenset({"admin"}), scenario
)
