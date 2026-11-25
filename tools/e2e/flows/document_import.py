"""Self-authored multi-file import through the real admin UI and backend."""

from __future__ import annotations

import copy
import json
import time

from e2e._paths import REPO_ROOT
from e2e.api_client import Api, ApiError
from e2e.browser import all_text, onboard, open_flutter, read_admin_session, reopen
from e2e.flowbase import Context, Flow
from e2e.servers import ADMIN_URL
from support.documents import docx_document, png_image, text_pdf

PDF_TEXT = "1. Self authored PDF engineering question"
CONTINUATION_TEXT = "Additional condition continued from PDF"
ANSWER_TEXT = "1. secret-reference-only"
DOCX_TEXT = "1. Self authored DOCX engineering question"


def sample_payload():
    return json.loads(
        (REPO_ROOT / "apps/admin_web/public/examples/question-import.json").read_text(
            encoding="utf-8"
        )
    )


def upload_fixtures():
    payload = sample_payload()
    broken = copy.deepcopy(payload)
    broken["question"]["knowledge"] = ["missing-e2e-knowledge"]
    return [
        {
            "name": "batch.json",
            "mimeType": "application/json",
            "buffer": json.dumps([payload, broken]).encode(),
        },
        {"name": "sample.pdf", "mimeType": "application/pdf", "buffer": text_pdf(PDF_TEXT)},
        {
            "name": "continued.pdf",
            "mimeType": "application/pdf",
            "buffer": text_pdf(CONTINUATION_TEXT),
        },
        {"name": "answers.pdf", "mimeType": "application/pdf", "buffer": text_pdf(ANSWER_TEXT)},
        {
            "name": "sample.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": docx_document(f"<w:p><w:r><w:t>{DOCX_TEXT}</w:t></w:r></w:p>"),
        },
    ]


def _click_response(page, button, suffix):
    if suffix in {"/process", "/candidates", "/submit"}:
        from playwright.sync_api import expect

        page.get_by_test_id("doc-draft-state").filter(has_text="已保存").wait_for()
        adopt = page.get_by_test_id("document-adopt-source")
        if adopt.count():
            adopt.click()
            expect(adopt).to_have_count(0)
            page.get_by_test_id("doc-draft-state").filter(has_text="已保存").wait_for()
    try:
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith(suffix)
        ) as response:
            button.click()
    except Exception as error:
        raise RuntimeError(
            f"{suffix}: public UI alerts {page.get_by_role('alert').all_text_contents()}"
        ) from error
    result = response.value
    if not result.ok:
        raise RuntimeError(f"{suffix}: {result.status} {result.text()}")
    return result.json()["data"]


def run(ctx: Context) -> None:
    page = ctx.new_admin_page()
    page.goto(ADMIN_URL)
    page.get_by_test_id("sign-in-reviewer").click()
    page.wait_for_selector('[data-testid="queue"]')
    session = read_admin_session(page)
    api = Api(session["token"])
    page.goto(ADMIN_URL.rstrip("/") + "/#/document-import")
    page.get_by_label("任务名称", exact=True).fill("CONTENT-IMPORT-002 自编联调")
    payload = sample_payload()
    page.get_by_label("来源", exact=True).fill(payload["source"]["source_name"])
    page.get_by_label("使用依据 / 授权编号", exact=True).fill(payload["source"]["source_license"])
    job = _click_response(page, page.get_by_test_id("create-job"), "/import-jobs")
    path = f"/admin/import-jobs/{job['id']}"
    page.wait_for_function(
        """() => { const input = document.querySelector('input[aria-label="上传多个文件"]'); return input && !input.disabled; }"""
    )
    page.get_by_label("上传多个文件").set_input_files(upload_fixtures())
    from playwright.sync_api import expect

    for fixture in upload_fixtures():
        page.locator("summary").filter(has_text=fixture["name"]).wait_for()
    expect(page.get_by_role("button", name="开始提取 / 重试处理", exact=True)).to_be_enabled()
    _click_response(page, page.get_by_role("button", name="开始提取 / 重试处理"), "/process")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        detail = api.get(path)
        if detail["job"]["status"] not in {"queued", "processing"}:
            break
        time.sleep(0.25)
    ctx.check(
        "全部自编文件均处理完成",
        len(detail["files"]) == len(upload_fixtures())
        and all(f["status"] == "ready" for f in detail["files"]),
        detail["job"],
    )
    merged = [c for c in detail["candidates"] if PDF_TEXT in c["text"]]
    ctx.check(
        "跨文件续题保留两份原位置",
        len(merged) == 1
        and CONTINUATION_TEXT in merged[0]["text"]
        and len(merged[0]["locations"]) == 2,
    )
    ctx.check(
        "独立答案不进入题干或结构化答案",
        all("secret-reference-only" not in c["text"] for c in detail["candidates"]),
    )
    page.get_by_role("button", name="刷新任务", exact=True).click()
    current = page.get_by_test_id("document-use-current")
    if current.count():
        page.locator("details").filter(has=current).locator("summary").click()
        current.click()
        page.get_by_test_id("doc-draft-state").filter(has_text="已保存").wait_for()
    page.locator(".candidate").first.wait_for()
    page.reload()
    page.locator(".candidate").first.wait_for()
    ctx.check("刷新后恢复同一任务", job["title"] in page.inner_text("body"))
    pdf = page.get_by_role("region", name="当前导入任务").locator("details").filter(has_text="sample.pdf")
    pdf.locator("summary").click()
    pdf.get_by_role("button", name="查看 PNG 原文", exact=True).first.click()
    page.get_by_alt_text("原文 PNG 预览").wait_for()
    ctx.check(
        "原文以安全 PNG 展示",
        page.get_by_alt_text("原文 PNG 预览")
        .get_attribute("src")
        .startswith("data:image/png;base64,"),
    )
    ctx.check("识别结果仍待人工确认", not any(c["confirmed"] for c in detail["candidates"]))
    for index, candidate in enumerate(detail["candidates"]):
        item = page.locator(".candidate").nth(index)
        body = candidate["payload"] or copy.deepcopy(payload)
        item.get_by_label("提取文字", exact=True).fill(body["question"]["content"]["stem"])
        item.get_by_label("题面、答案、题型、来源与教学 JSON", exact=True).fill(
            json.dumps(body, ensure_ascii=False)
        )
        source_name = body["source"]["source_name"] + "（逐题核对）"
        item.get_by_test_id("candidate-source-name").fill(source_name)
        item.get_by_test_id("candidate-subject").select_option(body["subject"])
        edited = json.loads(
            item.get_by_label("题面、答案、题型、来源与教学 JSON", exact=True).input_value()
        )
        ctx.check(
            f"候选{index + 1}逐题来源表单双向同步",
            edited["source"]["source_name"] == source_name
            and not item.get_by_role("checkbox").is_checked(),
        )
        if index == 0:
            answer_file = next(f for f in detail["files"] if f["filename"] == "answers.pdf")
            before = item.get_by_label(
                "题面、答案、题型、来源与教学 JSON", exact=True
            ).input_value()
            item.get_by_test_id("answer-location").select_option(answer_file["id"] + ":1")
            item.get_by_test_id("pair-answer").click()
            ctx.check(
                "人工配对仅记录原位置",
                item.get_by_label("题面、答案、题型、来源与教学 JSON", exact=True).input_value()
                == before
                and not item.get_by_role("checkbox").is_checked(),
            )
        if index == 0:
            item.get_by_test_id("open-structured-editor").click()
            visual = item.get_by_test_id("editor")
            visual.get_by_test_id("title").fill(body["question"]["title"] + "（可视化校对）")
            current_json = json.loads(
                item.get_by_label("题面、答案、题型、来源与教学 JSON", exact=True).input_value()
            )
            ctx.check(
                "候选可视化编辑同步JSON且保持待确认",
                current_json["question"]["title"].endswith("（可视化校对）")
                and not item.get_by_label(
                    "我已人工核对题面、答案配对、来源和使用依据", exact=True
                ).is_checked(),
            )
            item.get_by_test_id("open-structured-editor").click()
        item.get_by_label("我已人工核对题面、答案配对、来源和使用依据", exact=True).check()
    _click_response(
        page, page.get_by_role("button", name="保存校对与确认", exact=True), "/candidates"
    )
    result = _click_response(
        page, page.get_by_role("button", name="批量创建已保存", exact=False), "/submit"
    )
    imported = [i for i in result["items"] if i["status"] == "imported"]
    failed = [i for i in result["items"] if i["status"] == "failed"]
    ctx.check(
        "批次部分失败保留成功草稿",
        len(imported) == len(detail["candidates"]) - 1 and len(failed) == 1,
        result,
    )
    ctx.shot(page, "01_partial_batch")
    current = api.get(path)
    failed_id = failed[0]["candidate_id"]
    index = next(i for i, c in enumerate(current["candidates"]) if c["id"] == failed_id)
    repaired = current["candidates"][index]["payload"]
    repaired["question"]["knowledge"] = payload["question"]["knowledge"]
    page.locator(".candidate").nth(index).get_by_label(
        "题面、答案、题型、来源与教学 JSON", exact=True
    ).fill(json.dumps(repaired, ensure_ascii=False))
    page.locator(".candidate").nth(index).get_by_role("checkbox").check()
    _click_response(
        page, page.get_by_role("button", name="保存校对与确认", exact=True), "/candidates"
    )
    retried = _click_response(
        page, page.get_by_role("button", name="仅重试失败项", exact=True), "/submit"
    )
    ctx.check(
        "仅失败项创建草稿",
        len(retried["items"]) == 1 and retried["items"][0]["status"] == "imported",
        retried,
    )
    finished = api.get(path)
    ctx.check(
        "成功项映射保持稳定",
        all(
            next(c for c in finished["candidates"] if c["id"] == i["candidate_id"])["question_id"]
            == i["question_id"]
            for i in imported
        ),
    )
    question_id = imported[0]["question_id"]
    student = Api(Api("").post("/dev/local-identities?role=student")["access_token"])
    try:
        student.get(f"/questions/{question_id}")
        invisible = False
    except ApiError as error:
        invisible = error.status == 404
    ctx.check("学生不可读取待审草稿", invisible)
    current_draft = api.get(f"/admin/questions/{question_id}")
    try:
        api.post(
            f"/admin/questions/{question_id}/review",
            {
                "decision": "approve",
                "expected_version": current_draft["version"],
                "expected_review_revision": current_draft["review_revision"],
                "solution_kinds": ["standard"],
                "comment": "自审应拒绝",
            },
        )
        rejected = False
    except ApiError as error:
        rejected = error.status == 403
    ctx.check("导入者不能自审", rejected)
    page.goto(ADMIN_URL.rstrip("/") + f"/#/questions/{question_id}")
    page.get_by_test_id("edit").click()
    page.get_by_test_id("editor").wait_for()
    edited_title = payload["question"]["title"] + "（联调校对）"
    page.get_by_test_id("title").fill(edited_title)
    page.get_by_test_id("comment").last.fill("联调：编辑导入草稿")
    saved = _click_response(page, page.get_by_test_id("save"), "/versions")
    ctx.check("草稿编辑保存新版本", saved["version"] == 2 and saved["title"] == edited_title)
    other = ctx.new_admin_page()
    other.goto(ADMIN_URL)
    other.get_by_test_id("sign-in-reviewer").click()
    other.wait_for_selector('[data-testid="queue"]')
    other.goto(ADMIN_URL.rstrip("/") + f"/#/questions/{question_id}")
    other.get_by_test_id("decision-panel").wait_for()
    other.get_by_role("radio", name="二审通过", exact=True).check()
    other.get_by_test_id("comment").last.fill("独立审校自编工程样题")
    reviewed = _click_response(other, other.get_by_test_id("submit-decision"), "/review")
    ctx.check("独立审核通过但未自动发布", reviewed["status"] == "reviewed", reviewed)
    adopt = other.get_by_test_id("review-adopt")
    adopt.click()
    adopt.wait_for(state="hidden")
    other.get_by_role("radio", name="上线", exact=True).check()
    other.get_by_test_id("comment").last.fill("联调：独立审校后发布自编题目")
    published = _click_response(other, other.get_by_test_id("submit-decision"), "/review")
    ctx.check("独立审校员明确发布", published["status"] == "published")
    visible = student.get(f"/questions/{question_id}")
    ctx.check("发布后学生可见校对版本", visible["title"] == edited_title)
    ctx.check("页面无未捕获异常", not page.errors and not other.errors, page.errors + other.errors)
    ctx.shot(other, "02_independent_review")
    other_session = read_admin_session(other)
    author_api = Api(other_session["token"])
    first = author_api.post("/admin/question-imports", payload)
    second = author_api.post("/admin/question-imports", payload)
    page.goto(ADMIN_URL.rstrip("/") + "/#/batch-review?ids=" + first["id"] + "," + second["id"])
    page.get_by_test_id("batch-confirm").nth(1).wait_for()
    page.get_by_test_id("batch-confirm").nth(0).check()
    page.get_by_test_id("batch-confirm").nth(1).check()
    author_api.post(
        f"/admin/questions/{second['id']}/versions",
        {
            "expected_version": 1,
            "expected_review_revision": second["review_revision"],
            **payload["question"],
            "title": payload["question"]["title"] + "（并发更新）",
            "comment": "联调：并发更新版本",
        },
    )
    batch_result = _click_response(page, page.get_by_test_id("batch-submit"), "/batch")
    ctx.check(
        "批量审核部分失败保留成功项",
        [item["status"] for item in batch_result["items"]] == ["succeeded", "failed"]
        and batch_result["items"][1]["error"]["code"] == "version_conflict",
    )
    row = page.locator("article").nth(1)
    row.get_by_role("button", name="刷新本题版本并重新核对", exact=True).click()
    row.get_by_role(
        "heading", name=payload["question"]["title"] + "（并发更新） · v2", exact=True
    ).wait_for()
    row.get_by_test_id("batch-confirm").check()
    retried_review = _click_response(page, page.get_by_test_id("batch-submit"), "/batch")
    ctx.check(
        "批量审核只重试重新确认的失败题",
        len(retried_review["items"]) == 1 and retried_review["items"][0]["status"] == "succeeded",
    )
    page.reload()
    page.get_by_test_id("batch-confirm").nth(1).wait_for()
    ctx.check(
        "批量审核成功记录刷新恢复",
        all(box.is_disabled() for box in page.get_by_test_id("batch-confirm").all()),
    )
    ctx.shot(page, "03_batch_review")
    page.goto(ADMIN_URL.rstrip("/") + f"/#/questions/{first['id']}")
    page.get_by_test_id("edit").click()
    media_editor = page.get_by_test_id("editor").get_by_test_id("media-attachments")
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/confirm")
    ) as uploaded_media:
        media_editor.get_by_label("上传PNG/JPEG/WebP", exact=True).set_input_files(
            {"name": "self-authored.png", "mimeType": "image/png", "buffer": png_image()}
        )
    media_id = uploaded_media.value.json()["data"]["media_id"]
    media_editor.get_by_text(media_id, exact=True).wait_for()
    media_editor.get_by_label("附件说明", exact=True).fill("自编工程题面图示")
    page.get_by_test_id("comment").last.fill("联调：新增自编附件")
    attachment_version = _click_response(page, page.get_by_test_id("save"), "/versions")
    ctx.check(
        "附件上传确认后保存到题目新版本",
        attachment_version["content"]["attachments"][0]["media_id"] == media_id,
    )
    other.goto(ADMIN_URL.rstrip("/") + f"/#/questions/{first['id']}")
    other.get_by_test_id("preview-media").first.click()
    other.get_by_alt_text("已授权附件预览").wait_for()
    ctx.check(
        "独立审校员通过题目实际引用预览附件",
        other.get_by_alt_text("已授权附件预览")
        .get_attribute("src")
        .startswith("data:image/png;base64,"),
    )
    try:
        author_api.get(f"/media/{media_id}/content")
        blocked_direct = False
    except ApiError as error:
        blocked_direct = error.status == 404
    ctx.check("审校员仍不能跨owner直接读取媒体", blocked_direct)
    try:
        student.get(f"/media/{media_id}/content")
        blocked_student = False
    except ApiError as error:
        blocked_student = error.status == 403
    ctx.check("未审附件不向学生开放", blocked_student)
    ctx.shot(other, "04_private_attachment_review")
    other.get_by_test_id("confirm-viewed-media").check()
    declaration = _click_response(
        other, other.get_by_test_id("declare-media-review"), "/review-confirmations"
    )
    ctx.check(
        "独立审校声明绑定当前版本和媒体",
        declaration["version"] == attachment_version["version"]
        and declaration["media_id"] == media_id,
    )
    other.get_by_role("radio", name="二审通过", exact=True).check()
    _click_response(other, other.get_by_test_id("submit-decision"), "/review")
    adopt = other.get_by_test_id("review-adopt")
    adopt.click()
    adopt.wait_for(state="hidden")
    other.get_by_role("radio", name="上线", exact=True).check()
    _click_response(other, other.get_by_test_id("submit-decision"), "/review")
    student_image = student.get(f"/questions/{first['id']}/media/{media_id}/content")
    ctx.check("发布后学生只能通过题目当前引用读取图片", student_image["media_id"] == media_id)
    learner = ctx.new_page()
    open_flutter(learner)
    onboard(learner)
    reopen(learner, f"#/questions/{first['id']}/solve")
    ctx.check(
        "学生题面图片通过带身份接口加载",
        any(
            path.endswith(f"/questions/{first['id']}/media/{media_id}/content") and status == 200
            for _, path, status in learner.responses
        ),
    )
    ctx.check("图片替代文本在学生题面可访问", "自编工程题面图示" in all_text(learner))
    ctx.shot(learner, "05_student_static_attachment")
    api.post(f"/media/{media_id}/delete", {})
    reopen(learner, f"#/questions/{first['id']}/solve")
    unavailable = all_text(learner)
    ctx.check(
        "附件删除后显示替代文本和重试且题面仍可作答",
        "自编工程题面图示" in unavailable
        and "重试图片" in unavailable
        and "图片暂不可用" in unavailable
        and learner.get_by_role("button", name="提交", exact=True).count() == 1,
    )
    ctx.shot(learner, "06_student_attachment_unavailable")
    blocked_visual = _click_response(
        learner, learner.get_by_role("button", name="看图理解", exact=True), "/next"
    )
    ctx.check(
        "SEC304独立作答图解请求只返回无答案通知",
        not blocked_visual["session"]["used_solution"]
        and all(event["type"] == "notice" for event in blocked_visual["events"])
        and all(
            not {"template_id", "params", "caption", "static_fallback"}.intersection(
                event["payload"]
            )
            for event in blocked_visual["events"]
        ),
    )
    learner.get_by_role("button", name="我想直接看解析…", exact=True).click()
    explicit_solution = _click_response(
        learner, learner.get_by_role("button", name="看解析", exact=True), "/next"
    )
    ctx.check("完整解析独立动作记录used_solution", explicit_solution["session"]["used_solution"])
    allowed_visual = _click_response(
        learner, learner.get_by_role("button", name="看图理解", exact=True), "/next"
    )
    ctx.check(
        "明确选择完整解析后仍保留图解学习",
        allowed_visual["session"]["used_solution"]
        and any(event["type"] == "visual" for event in allowed_visual["events"]),
    )
    ctx.shot(learner, "07_sec304_solution_visual")


FLOW = Flow(
    name="document_import",
    title="多文件导入、人工校对、部分失败修复、独立二审",
    needs=frozenset({"admin", "flutter"}),
    run=run,
)
