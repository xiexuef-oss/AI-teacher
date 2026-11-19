"""Actual file chooser, temporary student upload and explicit manual confirmation."""

import io

from e2e import data
from e2e.browser import all_text, onboard, open_flutter, reopen, type_into
from e2e.flowbase import Context, Flow

KEY = "chem-process-reading"


def image_fixture():
    from PIL import Image

    output = io.BytesIO()
    with Image.new("RGB", (128, 128), color="white") as image:
        image.save(output, format="PNG")
    return {"name": "self-authored-scan.png", "mimeType": "image/png", "buffer": output.getvalue()}


def run(ctx: Context):
    from playwright.sync_api import expect

    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    reopen(page, "#/scan")
    ctx.check("拍题说明明确没有实际OCR", "未实际 OCR" in all_text(page))
    stem = data.question(KEY)["content"]["stem"]
    field = page.get_by_role("textbox", name="手工填写题干")

    def read_stem():
        # Flutter connects the native editing value when the field receives focus.
        field.click()
        expect(field).to_have_value(stem)
        return field.input_value()

    type_into(page, field, stem)
    reopen(page, "#/scan")
    ctx.check("拍题文字经真实页面输入后刷新恢复", read_stem() == stem)
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="选择图片", exact=True).click()
    chooser.value.set_files(image_fixture())
    upload = page.get_by_role("button", name="上传临时图片", exact=True)
    expect(upload).to_be_enabled()
    with page.expect_response(
        lambda response: (
            response.request.method == "POST" and response.url.endswith("/api/v1/scans")
        )
    ) as pending:
        upload.click()
    created = pending.value.json()["data"]
    ctx.check(
        "图片上传后仍为空候选与未知置信度",
        created["stem_text"] == ""
        and created["confidence"] is None
        and created["low_confidence"]
        and created["matched_question_id"] is None
        and "未实际识别" in created["mock_notice"],
    )
    ctx.check("上传结果不覆盖本机手工文字", read_stem() == stem)
    ctx.shot(page, "manual_input")
    reopen(page, "#/scan")
    read_stem()
    confirm = page.get_by_role("button", name="确认题干并匹配已有题目", exact=True)
    expect(confirm).to_be_enabled()
    ctx.check(
        "确认前不创建会话或作答",
        not any(
            method == "POST" and path in {"/sessions", "/attempts"}
            for method, path, _ in page.responses
        ),
    )
    with page.expect_response(
        lambda response: (
            response.request.method == "POST"
            and response.url.endswith(f"/scans/{created['id']}/confirm")
        )
    ) as pending:
        confirm.click()
    result = pending.value.json()["data"]
    ctx.check(
        "明确确认后匹配唯一发布工程题且不新建题库草稿",
        result["question_id"] == data.question_id(KEY) and result["draft_question_id"] is None,
    )
    start = page.get_by_role("button", name="开始练习", exact=True)
    expect(start).to_be_enabled()
    ctx.check(
        "匹配完成仍等待学生选择开始",
        not any(
            method == "POST" and path in {"/sessions", "/attempts"}
            for method, path, _ in page.responses
        ),
    )
    ctx.shot(page, "confirmed")
    start.click()
    expect(page.get_by_role("button", name="提交", exact=True)).to_be_visible(timeout=20000)
    ctx.check("学生点击开始后进入已发布题练习", stem in all_text(page))
    ctx.check("拍题页面无未捕获JS异常", not page.errors)


FLOW = Flow(
    name="student_scan",
    title="学生临时选图、本机文字恢复与明确确认匹配（未实际OCR）",
    needs=frozenset({"flutter"}),
    run=run,
)
