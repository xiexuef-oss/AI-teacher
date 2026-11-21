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
from reportlab.graphics.shapes import Drawing, Polygon
from reportlab.lib.colors import black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

MARGIN = 15 * mm
QR_SIZE = 20 * mm


@dataclass(frozen=True)
class PaperItem:
    code: str
    page_token: str
    stem: str
    incline_sketch: bool = False


@dataclass(frozen=True)
class SolutionItem:
    code: str
    solution: str


def _incline_sketch() -> Drawing:
    diagram = Drawing(150, 78)
    diagram.hAlign = "LEFT"
    diagram.add(Polygon([12, 7, 132, 7, 132, 67], fillColor=white, strokeColor=black))
    diagram.add(
        Polygon([68, 35, 92, 47, 84, 63, 60, 51], fillColor=white, strokeColor=black)
    )
    return diagram


def _render(
    rows: list[tuple[str, str, str | None, bool]],
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
    for code, content, token, incline_sketch in rows:
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
                qr = Drawing(QR_SIZE, QR_SIZE)
                qr.add(QrCodeWidget(page_token, barWidth=QR_SIZE, barHeight=QR_SIZE))
                draw(qr, canvas, A4[0] - MARGIN - QR_SIZE, MARGIN)

        story = [Paragraph(escape(line), style) for line in content.splitlines() if line.strip()]
        if token:
            story[0:0] = [
                Paragraph("在校直接在纸上作答，无需扫码或联网。返家后再回收。", style),
                Paragraph("作答日期（可留空）：________________", style),
                Spacer(1, 3 * mm),
            ]
        if incline_sketch:
            story.append(_incline_sketch())
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
        [(item.code, item.stem, item.page_token, item.incline_sketch) for item in items],
        font,
        f"学生版 {label}".strip(),
        continuation_tokens,
    )


def render_solutions(items: list[SolutionItem], font: Path, *, label: str = "") -> bytes:
    return _render(
        [(item.code, item.solution, None, False) for item in items], font, f"解析版 {label}".strip()
    )
