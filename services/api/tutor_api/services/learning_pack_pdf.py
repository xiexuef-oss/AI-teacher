"""Render separate, printable views of a paper learning pack."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from secrets import token_hex
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.renderPDF import draw
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

MARGIN = 15 * mm


@dataclass(frozen=True)
class PaperItem:
    code: str
    page_token: str
    stem: str


@dataclass(frozen=True)
class SolutionItem:
    code: str
    solution: str


def _render(
    rows: list[tuple[str, str, str | None]],
    font: Path,
    title: str,
    continuation_tokens: dict[str, list[str]] | None = None,
) -> bytes:
    if not rows:
        raise ValueError("A printable pack must contain at least one item")
    name = "Paper" + sha256(str(font.resolve()).encode()).hexdigest()
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(font)))
    style = ParagraphStyle("paper", fontName=name, fontSize=11, leading=17, wordWrap="CJK")
    output = PdfWriter()
    for code, content, token in rows:
        page = BytesIO()

        def header(canvas, document, code=code, token=token):
            canvas.setFont(name, 11)
            canvas.drawString(MARGIN, A4[1] - MARGIN, f"{title}  {code}  /  {document.page}")
            if token:
                page_token = token
                if document.page > 1:
                    page_token = token_hex(16)
                    if continuation_tokens is not None:
                        continuation_tokens.setdefault(code, []).append(page_token)
                size = 20 * mm
                qr = Drawing(size, size)
                qr.add(QrCodeWidget(page_token, barWidth=size, barHeight=size))
                draw(qr, canvas, A4[0] - MARGIN - size, MARGIN)

        story = [Paragraph(escape(line), style) for line in content.splitlines() if line.strip()]
        if token:
            story.append(Spacer(1, 35 * mm))
        document = SimpleDocTemplate(
            page,
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=25 * mm,
            bottomMargin=39 * mm,
        )
        document.build(story, onFirstPage=header, onLaterPages=header)
        page.seek(0)
        output.append(PdfReader(page, strict=True), import_outline=False)
    result = BytesIO()
    output.write(result)
    return result.getvalue()


def render_student(
    items: list[PaperItem],
    font: Path,
    *,
    label: str = "",
    continuation_tokens: dict[str, list[str]] | None = None,
) -> bytes:
    return _render(
        [(item.code, item.stem, item.page_token) for item in items],
        font,
        f"学生版 {label}".strip(),
        continuation_tokens,
    )


def render_solutions(items: list[SolutionItem], font: Path, *, label: str = "") -> bytes:
    return _render(
        [(item.code, item.solution, None) for item in items], font, f"解析版 {label}".strip()
    )
