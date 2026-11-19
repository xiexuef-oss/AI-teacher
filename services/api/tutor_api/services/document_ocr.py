"""导入 OCR 仅经模型网关；禁用、Mock、空输出均明确保留人工录入状态。"""

import hashlib

from ai_gateway import Constraints, GatewayRequest, InputPart, TaskType
from tutor_api.db import new_id
from tutor_api.services.document_extract import DocumentParseError


def recognize_pages(
    pages, data, kind, settings, gateway, parser, job_id, checkpoint=None, *, progress=None
):
    if settings.import_ocr_mode == "disabled" or gateway is None:
        return pages
    if settings.import_ocr_mode == "mock" and gateway.external_calls_possible:
        for page in pages:
            if page["method"] == "unavailable":
                page["warnings"].append(
                    "Mock 模式禁止外部调用，当前网关含可用外部路由，OCR 未执行。"
                )
        return pages
    for page in pages:
        if page["method"] != "unavailable":
            continue
        if checkpoint is not None and not checkpoint():
            raise DocumentParseError("import_cancelled", "任务已取消、过期或由另一工作器接管")
        try:
            preview = parser(data, kind, settings, page=page["number"])
            if checkpoint is not None and not checkpoint():
                raise DocumentParseError("import_cancelled", "任务已取消、过期或由另一工作器接管")
            trace = new_id()
            request = GatewayRequest(
                request_id=trace,
                trace_id=trace,
                student_pseudonym="import:" + hashlib.sha256(job_id.encode()).hexdigest()[:24],
                task_type=TaskType.OCR_EXTRACT,
                input_parts=[
                    InputPart(
                        kind="text",
                        text="仅转录图中的原文，保持题号和阅读顺序；不作答，不补全缺失内容。",
                    ),
                    InputPart(
                        kind="image_ref", media_ref="data:image/png;base64," + preview["png"]
                    ),
                ],
                constraints=Constraints(max_output_tokens=4000),
            )
            if progress is not None:
                cached = progress.begin(page, request)
                if cached is not None:
                    page.clear()
                    page.update(cached)
                    continue
            response = progress.invoke(request) if progress is not None else gateway.invoke(request)
            if settings.import_ocr_mode == "mock" or gateway.provider_is_mock(response.provider):
                page["method"], page["confidence"] = "ocr_mock", response.confidence
                page["warnings"].append("Mock 仅验证网关链路，不识别图中文字，请人工录入。")
            elif response.status != "ok" or not response.validated_output:
                page["warnings"].append("OCR 不可用，请人工录入或稍后重新创建任务。")
            else:
                text = response.validated_output["stem_text"].strip()
                if not text:
                    page["warnings"].append("OCR 未提取到文字，不能据此认定为空白页，请人工核对。")
                else:
                    total = sum(len(item["text"]) for item in pages) - len(page["text"]) + len(text)
                    if total > settings.import_max_extracted_chars:
                        raise DocumentParseError("text_limit", "OCR 总文字超过任务上限，请拆分文件")
                    page.update(text=text, method="ocr", confidence=response.confidence)
                    page["warnings"].append(
                        "OCR 输出未经学科校对，公式、图表及阅读顺序须对照原图确认。"
                    )
                    if (
                        response.review_required
                        or response.confidence is None
                        or response.confidence < 0.8
                    ):
                        page["warnings"].append("识别置信度不足或未知，必须人工复核。")
            if progress is not None:
                progress.complete(page)
        except DocumentParseError as error:
            if error.code in {"import_cancelled", "text_limit"}:
                raise
            page["warnings"].append(f"{error.code}: 无法生成 OCR 输入，请人工录入。")
    if sum(len(page["text"]) for page in pages) > settings.import_max_extracted_chars:
        raise DocumentParseError("text_limit", "OCR 总文字超过任务上限，请拆分文件")
    return pages
