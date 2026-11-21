"""本地文档提取：保序、限额、不将扫描件当作已识别。"""

import io
from zipfile import ZipFile

import pytest
from PIL import Image

from support.documents import docx_document, png_image, scanned_pdf, text_pdf
from tutor_api.services.document_extract import (
    DocumentParseError,
    ParseLimits,
    extract,
    render_preview,
)


def test_pdf_keeps_pages_and_text_order():
    result = extract(
        text_pdf("1. First question\nA. choice", "2. Second question"), "pdf", ParseLimits()
    )
    assert [p["number"] for p in result] == [1, 2]
    assert result[0]["text"].index("1. First") < result[0]["text"].index("A. choice")
    assert result[1]["method"] == "pdf_text"
    assert result[0]["warnings"], "阅读顺序和公式仍须人工核对"


def test_scanned_pdf_is_marked_for_ocr_without_fake_text():
    result = extract(scanned_pdf(), "pdf", ParseLimits())
    assert result[0]["text"] == "" and result[0]["method"] == "unavailable"
    assert result[0]["warnings"]


def test_docx_keeps_paragraph_table_order_and_media_references():
    body = "<w:p><w:r><w:t>1. 自编题</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>数据甲</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>12</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>2. 下一题</w:t></w:r></w:p>"
    result = extract(docx_document(body, image=True), "docx", ParseLimits())
    text = "\n".join(p["text"] for p in result)
    assert text.index("自编题") < text.index("数据甲") < text.index("下一题")
    assert any("image1.png" in ref for p in result for ref in p["media_refs"])
    assert all(p["method"] == "docx_text" and p["warnings"] for p in result)


def test_images_need_ocr_and_preview_is_safe_png():
    data = png_image()
    page = extract(data, "png", ParseLimits())[0]
    assert page["text"] == "" and page["method"] == "unavailable"
    image = Image.open(io.BytesIO(render_preview(data, "png", 1, ParseLimits())))
    assert image.format == "PNG" and image.size == (320, 80)


def test_word_metafiles_do_not_prevent_text_extraction():
    data = io.BytesIO(docx_document("<w:p><w:r><w:t>1. 公式题</w:t></w:r></w:p>", image=True))
    with ZipFile(data, "a") as archive:
        for index in range(101):
            archive.writestr(f"word/media/formula{index}.wmf", b"vector")
    pages = extract(data.getvalue(), "docx", ParseLimits())
    assert pages[0]["text"] == "1. 公式题"
    assert any("WMF" in warning for warning in pages[0]["warnings"])
    assert pages[0]["media_refs"] == ["word/media/image1.png"]


def test_word_drawing_textbox_does_not_hide_question_number():
    body = (
        "<w:p><w:r><w:pict><w:txbxContent><w:p><w:r><w:t>ABCD</w:t></w:r></w:p>"
        "</w:txbxContent></w:pict></w:r><w:r><w:t>13. 下一题</w:t></w:r></w:p>"
    )
    page = extract(docx_document(body), "docx", ParseLimits())[0]
    assert page["text"] == "13. 下一题"
    assert any("文本框" in warning for warning in page["warnings"])


def test_pdf_preview_renders_the_requested_page():
    preview = render_preview(text_pdf("Self authored PDF"), "pdf", 1, ParseLimits())
    image = Image.open(io.BytesIO(preview))
    assert image.format == "PNG" and image.width * image.height <= 4_000_000


@pytest.mark.parametrize(
    "data,kind,limits,code",
    [
        (b"%PDF-broken", "pdf", ParseLimits(), "invalid_pdf"),
        (text_pdf("secret", encrypted=True), "pdf", ParseLimits(), "encrypted_document"),
        (text_pdf("one", "two"), "pdf", ParseLimits(max_pages=1), "page_limit"),
        (
            docx_document("<w:p><w:r><w:t>" + ("a" * 1000) + "</w:t></w:r></w:p>"),
            "docx",
            ParseLimits(max_chars=20),
            "text_limit",
        ),
        (docx_document("<w:p/>", macro=True), "docx", ParseLimits(), "macros_not_allowed"),
        (docx_document("<w:p/>"), "docx", ParseLimits(max_unpacked_bytes=10), "unpacked_limit"),
        (png_image((100, 100)), "png", ParseLimits(max_image_pixels=100), "image_limit"),
        (b"not a doc converter input", "doc", ParseLimits(), "converter_unavailable"),
    ],
)
def test_invalid_or_unbounded_documents_fail_explicitly(data, kind, limits, code):
    with pytest.raises(DocumentParseError) as error:
        extract(data, kind, limits)
    assert error.value.code == code


def test_docx_embedded_image_can_be_previewed_without_executing_document():
    data = docx_document("<w:p><w:r><w:t>自编图片</w:t></w:r></w:p>", image=True)
    preview = render_preview(data, "docx", 1, ParseLimits(), media_index=0)
    assert Image.open(io.BytesIO(preview)).format == "PNG"


def test_docx_external_entity_is_rejected_without_reading_resource():
    import zipfile

    source = docx_document("<w:p/>")
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(output, "w") as target:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.replace(
                    b"<w:document",
                    b'<!DOCTYPE document [<!ENTITY secret SYSTEM "file:///unavailable-secret">]><w:document',
                    1,
                )
            target.writestr(item, data)
    with pytest.raises(DocumentParseError) as error:
        extract(output.getvalue(), "docx", ParseLimits())
    assert error.value.code == "unsafe_xml"


def test_mixed_pdf_preserves_text_page_and_marks_scan_for_ocr():
    from pypdf import PdfReader, PdfWriter

    from support.documents import scanned_pdf

    writer = PdfWriter()
    for source in (text_pdf("1. Self authored mixed page"), scanned_pdf()):
        reader = PdfReader(io.BytesIO(source))
        for page in reader.pages:
            writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    pages = extract(output.getvalue(), "pdf", ParseLimits())
    assert [page["number"] for page in pages] == [1, 2]
    assert pages[0]["method"] == "pdf_text" and "mixed page" in pages[0]["text"]
    assert pages[1]["method"] == "unavailable" and pages[1]["text"] == ""
