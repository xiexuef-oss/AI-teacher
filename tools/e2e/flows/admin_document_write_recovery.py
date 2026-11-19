"""Real six-command recovery, with self-authored JSON only and safe evidence."""

import hashlib
import json
import re
import sqlite3
import time

from e2e._paths import REPO_ROOT
from e2e.flowbase import Flow
from e2e.flows.admin_question_recovery import _login
from e2e.servers import ADMIN_URL


def scenario(ctx):
    from playwright.sync_api import expect

    page, _, api = _login(ctx)
    ctx.check("真实WebLocks可用", page.evaluate("typeof navigator.locks?.request==='function'"))
    payload = json.loads(
        (REPO_ROOT / "apps/admin_web/public/examples/question-import.json").read_text(
            encoding="utf-8"
        )
    )
    page.goto(ADMIN_URL.rstrip("/") + "/#/document-import")
    page.get_by_label("任务名称", exact=True).fill("自编文档恢复A")
    page.get_by_label("来源", exact=True).fill(payload["source"]["source_name"])
    page.get_by_label("使用依据 / 授权编号", exact=True).fill(payload["source"]["source_license"])
    safe = []

    def saved():
        page.get_by_test_id("doc-draft-state").filter(has_text="已保存").wait_for()

    def recover(path, action, *, file=None, edit_inflight=None):
        records, first = [], []

        def intercept(route):
            req = route.request
            if req.method != "POST" or not req.url.endswith(path):
                route.continue_()
                return
            response = route.fetch()
            records.append(
                {
                    "key": req.headers.get("idempotency-key"),
                    "wire": req.post_data,
                    "status": response.status,
                    "replayed": response.headers.get("idempotency-replayed"),
                    "result": response.json().get("data"),
                }
            )
            if len(records) == 1:
                if not response.ok:
                    raise RuntimeError(f"Initial {path} failed: {response.status}")
                first.append({"route": route, "data": response.json()["data"]})
                # Hold a real committed response while the user can continue input.
            else:
                route.fulfill(response=response)

        pattern = "**" + path
        page.route(pattern, intercept)
        action()
        stop = time.monotonic() + 30
        while not first and time.monotonic() < stop:
            page.wait_for_timeout(25)
        if not first:
            raise RuntimeError("No successful committed response: " + path)
        if edit_inflight:
            edit_inflight()
            saved()
        first[0]["route"].abort()
        history = page.get_by_role("region", name="本机操作历史")
        row = history.locator("article").filter(
            has=page.locator(
                "pre",
                has_text=re.compile(r"^POST " + re.escape(path) + r" · (prepared|unavailable)"),
            )
        )
        row.wait_for()
        ctx.check(path + " 服务端成功后丢弃完整响应", records[0]["status"] in (200, 201))
        page.reload()
        # With several saved workspaces, restoration does not promise a latest
        # selection. Explicitly choose the original job, as a user would.
        parts = path.split("/")
        if len(parts) > 3:
            page.get_by_test_id("doc-workspace").filter(has_text=parts[3]).click()
        history = page.get_by_role("region", name="本机操作历史")
        row = history.locator("article").filter(
            has=page.locator(
                "pre",
                has_text=re.compile(r"^POST " + re.escape(path) + r" · (prepared|unavailable)"),
            )
        )
        row.wait_for()
        ctx.check(path + " 刷新无自动补发", len(records) == 1)
        if file:
            expect(row.get_by_test_id("doc-reselect")).to_be_enabled()
            row.get_by_test_id("doc-reselect").set_input_files(file)
        else:
            row.get_by_test_id("doc-retry").click()
        history.locator("article").filter(
            has=page.locator("pre", has_text=re.compile(r"^POST " + re.escape(path) + r" · acked"))
        ).wait_for()
        ctx.check(
            path + " 原key完整wire真实重放",
            len(records) == 2
            and records[0]["key"] == records[1]["key"]
            and records[0]["wire"] == records[1]["wire"]
            and records[1]["result"] == records[0]["result"]
            and records[1]["replayed"] == "true",
        )
        for r in records:
            safe.append(
                {
                    "path": path,
                    "key": r["key"],
                    "wire_sha256": hashlib.sha256(r["wire"].encode()).hexdigest(),
                    "status": r["status"],
                    "replayed": r["replayed"],
                }
            )
        page.unroute(pattern, intercept)
        return first[0]["data"]

    saved()
    job = recover(
        "/admin/import-jobs",
        lambda: page.get_by_test_id("create-job").click(),
        edit_inflight=lambda: page.get_by_label("任务名称", exact=True).fill(
            "自编文档续改B\n保留创建草稿"
        ),
    )
    ctx.check(
        "创建A未知重放未覆盖后续输入B",
        "续改B" in page.get_by_label("任务名称", exact=True).input_value(),
    )
    path = "/admin/import-jobs/" + job["id"]
    file = {
        "name": "self-authored.json",
        "mimeType": "application/json",
        "buffer": json.dumps([payload], ensure_ascii=False).encode(),
    }
    page.get_by_label("上传多个文件", exact=True).wait_for()
    expect(page.get_by_label("上传多个文件", exact=True)).to_be_enabled()
    recover(
        path + "/files",
        lambda: page.get_by_label("上传多个文件", exact=True).set_input_files(file),
        file=file,
    )
    recover(
        path + "/process",
        lambda: page.get_by_role("button", name="开始提取 / 重试处理", exact=True).click(),
    )
    stop = time.monotonic() + 45
    while time.monotonic() < stop:
        detail = api.get(path)
        if detail["job"]["status"] not in ("queued", "processing"):
            break
        page.wait_for_timeout(100)
    ctx.check("真实提取产生自编候选", len(detail["candidates"]) == 1)
    page.get_by_role("button", name="刷新任务", exact=True).click()
    candidate = page.locator(".candidate").first
    candidate.wait_for()
    candidate.get_by_label("题面、答案、题型、来源与教学 JSON", exact=True).fill(
        json.dumps(payload, ensure_ascii=False)
    )
    candidate.get_by_label("我已人工核对题面、答案配对、来源和使用依据", exact=True).check()
    saved()
    if page.get_by_test_id("document-adopt-source").count():
        page.get_by_test_id("document-adopt-source").click()
    recover(
        path + "/candidates",
        lambda: page.get_by_role("button", name="保存校对与确认", exact=True).click(),
    )
    if page.get_by_test_id("document-adopt-source").count():
        page.get_by_test_id("document-adopt-source").click()

    def question_count():
        db_path = (ctx.out_dir / "tutor.sqlite3").resolve().as_posix()
        with sqlite3.connect("file:" + db_path + "?mode=ro", uri=True) as db:
            return db.execute("SELECT count(*) FROM questions").fetchone()[0]

    before = question_count()
    batch = recover(
        path + "/submit",
        lambda: page.get_by_role(
            "button", name="批量创建已保存的确认草稿 / 重试未完成批次", exact=True
        ).click(),
    )
    ctx.check(
        "批次恢复只创建一次正式待审草稿",
        len(batch["items"]) == 1
        and batch["items"][0]["status"] == "imported"
        and question_count() == before + 1,
    )
    ctx.shot(page, "01_document_six_recovery")
    page.get_by_test_id("doc-new-workspace").click()
    page.get_by_label("任务名称", exact=True).fill("自编取消验证任务")
    page.get_by_label("来源", exact=True).fill(payload["source"]["source_name"])
    page.get_by_label("使用依据 / 授权编号", exact=True).fill(payload["source"]["source_license"])
    saved()
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/admin/import-jobs")
    ) as created:
        page.get_by_test_id("create-job").click()
    second = created.value.json()["data"]
    recover(
        "/admin/import-jobs/" + second["id"] + "/cancel",
        lambda: page.get_by_role("button", name="取消未开始的工作", exact=True).click(),
    )
    ctx.shot(page, "02_cancel_history")
    (ctx.out_dir / "safe_command_requests.json").write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
    )


FLOW = Flow(
    "admin_document_write_recovery", "文档六类写命令真实丢响应恢复", frozenset({"admin"}), scenario
)
