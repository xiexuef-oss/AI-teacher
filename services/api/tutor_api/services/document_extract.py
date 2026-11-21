"""有界的纯文档提取与安全栅格预览；不执行宏、链接或文档脚本。"""

from __future__ import annotations

import io
import json
import math
import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from tutor_api.schemas import AdminQuestionImportIn

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


class DocumentParseError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


@dataclass(frozen=True)
class ParseLimits:
    max_pages: int = 80
    max_chars: int = 100_000
    max_unpacked_bytes: int = 48 * 1024 * 1024
    max_image_pixels: int = 20_000_000
    max_preview_pixels: int = 4_000_000
    max_candidates: int = 200


def _page(number, text, method, warnings, media_refs=None, **extra):
    return {
        "number": number,
        "text": text,
        "method": method,
        "warnings": list(warnings),
        "confidence": None,
        "media_refs": list(media_refs or []),
        **extra,
    }


def _check_text(pages, limits):
    if sum(len(p["text"]) for p in pages) > limits.max_chars:
        raise DocumentParseError("text_limit", "提取文字超过上限，请拆分文档后上传")


def _pdf_reader(data, limits):
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentParseError("encrypted_document", "暂不接收加密 PDF，请先提供未加密副本")
        if len(reader.pages) > limits.max_pages:
            raise DocumentParseError("page_limit", "PDF 页数超过上限，请拆分后上传")
        return reader
    except DocumentParseError:
        raise
    except (PdfReadError, ValueError, OSError, KeyError, RecursionError) as error:
        raise DocumentParseError("invalid_pdf", "PDF 无法解析或已损坏") from error


def _pdf(data, limits):
    reader = _pdf_reader(data, limits)
    pages = []
    try:
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            warnings = ["PDF 的阅读顺序、公式、图表和上下标必须对照原文人工核对。"]
            if not text:
                warnings.append("未提取到文字，可能为空白页或扫描页；需要 OCR 或人工录入。")
            pages.append(_page(number, text, "pdf_text" if text else "unavailable", warnings))
            _check_text(pages, limits)
    except DocumentParseError:
        raise
    except Exception as error:
        raise DocumentParseError("invalid_pdf", "PDF 文字无法可靠提取，请对照原文件处理") from error
    return pages


def _xml(data):
    try:
        return SafeXML.fromstring(data)
    except (DefusedXmlException, SafeXML.ParseError) as error:
        raise DocumentParseError("unsafe_xml", "文档 XML 无效或包含不允许的实体声明") from error


def _open_docx(data, limits):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
        if len(entries) > 2000 or sum(e.file_size for e in entries) > limits.max_unpacked_bytes:
            archive.close()
            raise DocumentParseError("unpacked_limit", "文档解压大小或条目数超过上限")
        if any(
            ".." in PurePosixPath(e.filename).parts or e.filename.startswith(("/", "\\"))
            for e in entries
        ):
            archive.close()
            raise DocumentParseError("unsafe_archive", "文档包含不允许的路径")
        if any(
            "vbaproject" in e.filename.lower() or "vbadata" in e.filename.lower() for e in entries
        ):
            archive.close()
            raise DocumentParseError("macros_not_allowed", "不接收带宏的 Word 文档")
        if "word/document.xml" not in archive.namelist():
            archive.close()
            raise DocumentParseError("invalid_docx", "未找到 DOCX 正文")
        return archive
    except (zipfile.BadZipFile, ValueError) as error:
        raise DocumentParseError("invalid_docx", "DOCX 无法解析或已损坏") from error


def _paragraph(node):
    parts = []
    for element in node.iter():
        if element.tag in {W + "t", M + "t"}:
            parts.append(element.text or "")
        elif element.tag == W + "tab":
            parts.append("\t")
        elif element.tag in {W + "br", W + "cr"}:
            parts.append("\n")
    return "".join(parts).strip()


def _docx(data, limits):
    warnings = ["DOCX 序号表示提取片段，不是 Word 物理页码；公式、图示及版式必须人工核对。"]
    with _open_docx(data, limits) as archive:
        document = _xml(archive.read("word/document.xml"))
        body = document.find(W + "body")
        if body is None:
            raise DocumentParseError("invalid_docx", "DOCX 没有正文")
        textboxes = [
            (parent, textbox)
            for parent in body.iter()
            for textbox in parent.findall(W + "txbxContent")
        ]
        if textboxes:
            warnings.append("图形文本框未拼入正文，请在 Word 原件中核对文本框内容。")
            for parent, textbox in textboxes:
                parent.remove(textbox)
        media = [
            e.filename
            for e in archive.infolist()
            if e.filename.startswith("word/media/") and not e.is_dir()
        ]
        raster_or_other = [ref for ref in media if not ref.lower().endswith((".wmf", ".emf"))]
        if len(raster_or_other) != len(media):
            warnings.append("文档含 WMF/EMF 矢量公式或图示，请在 Word 原件中核对。")
        media = raster_or_other
        if len(media) > 100:
            raise DocumentParseError("media_limit", "文档内媒体数量超过上限")
        links = {}
        if "word/_rels/document.xml.rels" in archive.namelist():
            for rel in _xml(archive.read("word/_rels/document.xml.rels")):
                if rel.attrib.get("TargetMode") == "External":
                    warnings.append("文档包含外部链接，未加载外部内容。")
                    continue
                target = posixpath.normpath(posixpath.join("word", rel.attrib.get("Target", "")))
                if target in media:
                    links[rel.attrib.get("Id")] = target
        if any(e.tag.startswith(M) for e in document.iter()):
            warnings.append("包含 Word 公式，提取文字不保证公式结构完整，请对照原文补成 LaTeX。")
        blocks = []
        used_media = set()
        for element in body:
            if element.tag == W + "p":
                text = _paragraph(element)
            elif element.tag == W + "tbl":
                text = "\n".join(
                    " | ".join(_paragraph(cell) for cell in row.findall(W + "tc"))
                    for row in element.findall(W + "tr")
                )
            elif element.tag == W + "sectPr":
                continue
            else:
                text = "[未完整解析的 Word 内容块，请查看原文件]"
                warnings.append("存在未支持的 Word 内容块。")
            refs = [
                links[e.attrib.get(R + "embed")]
                for e in element.iter(A + "blip")
                if e.attrib.get(R + "embed") in links
            ]
            used_media.update(refs)
            if refs:
                text += "\n" + "\n".join("[图像：" + ref + "]" for ref in refs)
            if text.strip():
                blocks.append(text.strip())
        chunks, current = [], ""
        for block in blocks:
            if len(block) > 4000:
                warnings.append("过长的段落已分段，必须人工核对题目边界。")
            for offset in range(0, len(block), 4000):
                part = block[offset : offset + 4000]
                if current and len(current) + len(part) + 1 > 4000:
                    chunks.append(current)
                    current = ""
                current = (current + "\n" + part).strip()
        if current or not chunks:
            chunks.append(current)
        if len(chunks) > limits.max_pages:
            raise DocumentParseError("page_limit", "DOCX 提取片段过多，请拆分文档")
        if set(media) - used_media:
            warnings.append("文档包含无法定位到段落的内嵌媒体，已保留引用供校对。")
        pages = [
            _page(
                i + 1,
                text,
                "docx_text",
                list(dict.fromkeys(warnings)),
                [ref for ref in media if "[图像：" + ref + "]" in text],
            )
            for i, text in enumerate(chunks)
        ]
        pages[0]["media_refs"] = list(
            dict.fromkeys(
                [*pages[0]["media_refs"], *(ref for ref in media if ref not in used_media)]
            )
        )
        _check_text(pages, limits)
        return pages


def _validate_image(data, limits):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > limits.max_image_pixels:
                raise DocumentParseError("image_limit", "图片像素超过上限，请缩小后上传")
            if image.format not in {"PNG", "JPEG"}:
                raise DocumentParseError("invalid_image", "只接收 PNG/JPEG 图片")
            image.verify()
    except DocumentParseError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise DocumentParseError("invalid_image", "图片无法解析或已损坏") from error


def extract(data: bytes, kind: str, limits: ParseLimits) -> list[dict]:
    if kind == "pdf":
        return _pdf(data, limits)
    if kind == "docx":
        return _docx(data, limits)
    if kind in {"png", "jpeg"}:
        _validate_image(data, limits)
        return [_page(1, "", "unavailable", ["图片文字尚未识别，需要 OCR 或人工录入。"])]
    if kind == "doc":
        raise DocumentParseError(
            "converter_unavailable", "未配置安全 DOC 转换器，请另存为 DOCX 后上传"
        )
    if kind == "json":
        try:
            value = json.loads(data.decode("utf-8-sig"))
            items = value if isinstance(value, list) else [value]
            if not items or len(items) > limits.max_candidates:
                raise DocumentParseError("candidate_limit", "JSON 题目数量为空或超限")
            payloads = [
                AdminQuestionImportIn.model_validate(item).model_dump(
                    mode="json", exclude_unset=True
                )
                for item in items
            ]
            pages = [
                _page(
                    i + 1,
                    item["question"]["content"]["stem"],
                    "json",
                    ["结构化题目仍须人工确认。"],
                    _payload=item,
                )
                for i, item in enumerate(payloads)
            ]
            _check_text(pages, limits)
            return pages
        except DocumentParseError:
            raise
        except (ValueError, ValidationError, RecursionError) as error:
            raise DocumentParseError("invalid_json", "JSON 不符合单题或题目数组导入格式") from error
    raise DocumentParseError("unsupported_document", "不支持此文档格式")


def _image_png(data, limits):
    _validate_image(data, limits)
    with Image.open(io.BytesIO(data)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        scale = min(1.0, math.sqrt(limits.max_preview_pixels / (image.width * image.height)))
        if scale < 1:
            image.thumbnail((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()


def render_preview(
    data: bytes, kind: str, page: int, limits: ParseLimits, media_index: int | None = None
) -> bytes:
    if page < 1:
        raise DocumentParseError("preview_not_found", "预览页不存在")
    if kind in {"png", "jpeg"}:
        if page != 1:
            raise DocumentParseError("preview_not_found", "预览页不存在")
        return _image_png(data, limits)
    if kind == "docx":
        pages = _docx(data, limits)
        if page > len(pages):
            raise DocumentParseError("preview_not_found", "提取片段不存在")
        refs = pages[page - 1]["media_refs"]
        index = media_index if media_index is not None else 0
        if not refs or index >= len(refs):
            raise DocumentParseError(
                "preview_not_available", "此片段没有可栅格预览的图像，请查看提取文本或下载原文"
            )
        with _open_docx(data, limits) as z:
            return _image_png(z.read(refs[index]), limits)
    if kind == "pdf":
        reader = _pdf_reader(data, limits)
        if page > len(reader.pages):
            raise DocumentParseError("preview_not_found", "预览页不存在")
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(data)
        surface = bitmap = None
        try:
            surface = document[page - 1]
            width, height = surface.get_size()
            scale = min(1.5, math.sqrt(limits.max_preview_pixels / (width * height)))
            bitmap = surface.render(scale=scale, may_draw_forms=False)
            out = io.BytesIO()
            bitmap.to_pil().convert("RGB").save(out, format="PNG")
            return out.getvalue()
        except Exception as error:
            raise DocumentParseError("preview_failed", "无法生成页面栅格预览") from error
        finally:
            if bitmap is not None:
                bitmap.close()
            if surface is not None:
                surface.close()
            document.close()
    raise DocumentParseError("preview_not_available", "此格式请查看提取文字或下载原文件")
