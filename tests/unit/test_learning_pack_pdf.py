from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab import __file__ as reportlab_path

from tutor_api.services.learning_pack_pdf import (
    PaperItem,
    SolutionItem,
    render_solutions,
    render_student,
    stamp_print_time,
)


@pytest.fixture
def font():
    return Path(reportlab_path).parent / "fonts" / "Vera.ttf"


def test_two_pdfs_have_separate_content_and_a4_pages(font, monkeypatch):
    from tutor_api.services import learning_pack_pdf as renderer

    original = renderer.Paragraph
    rendered_lines = []

    def record(text, style):
        rendered_lines.append(text)
        return original(text, style)

    monkeypatch.setattr(renderer, "Paragraph", record)
    question = PaperItem(code="AB123", page_token="opaque-page", stem="Compute 2 + 2.")
    student = PdfReader(BytesIO(render_student([question], font)))
    assert any("作答日期" in line for line in rendered_lines)
    assert any("无需扫码或联网" in line for line in rendered_lines)
    solutions = PdfReader(BytesIO(render_solutions([SolutionItem("AB123", "Answer: four")], font)))
    assert "Compute 2 + 2." in student.pages[0].extract_text()
    assert "AB123" in student.pages[0].extract_text()
    assert "Answer: four" not in student.pages[0].extract_text()
    assert "Answer: four" in solutions.pages[0].extract_text()
    assert "Answer: four" not in str(student.metadata)
    assert student.xmp_metadata is None
    assert not student.attachments
    assert "/AF" not in student.root_object
    assert "/OCProperties" not in student.root_object
    assert all(not page.images and not page.annotations for page in student.pages)
    assert float(student.pages[0].mediabox.width) == pytest.approx(595.276, abs=0.001)


def test_long_question_flows_without_truncation(font):
    stem = ("The question continues here. " * 500) + "\nEnd of question."
    published = render_student([PaperItem("AB123", "opaque-page", stem)], font)
    student = PdfReader(BytesIO(published))
    assert len(student.pages) > 1
    assert "End of question." in "".join(page.extract_text() for page in student.pages)
    assert all("AB123" in page.extract_text() for page in student.pages)
    printed = PdfReader(BytesIO(stamp_print_time(published, datetime(2026, 11, 22, 5, tzinfo=UTC))))
    assert len(printed.pages) == len(student.pages)
    for original, stamped in zip(student.pages, printed.pages, strict=True):
        assert original.mediabox == stamped.mediabox
        assert original.extract_text().strip() in stamped.extract_text()
        assert "2026-11-22 13:00:00" in stamped.extract_text()


def test_incline_sketch_is_vector_and_does_not_add_solution_text(font):
    plain = PaperItem("001", "opaque-page", "A block rests on a slope.")
    illustrated = PaperItem("001", "opaque-page", plain.stem, incline_sketch=True)
    base = PdfReader(BytesIO(render_student([plain], font))).pages[0]
    diagram = PdfReader(BytesIO(render_student([illustrated], font))).pages[0]
    assert diagram.extract_text() == base.extract_text()
    assert not diagram.images and not diagram.annotations
    base_lines = sum(operator == b"l" for _, operator in base.get_contents().operations)
    diagram_lines = sum(operator == b"l" for _, operator in diagram.get_contents().operations)
    assert diagram_lines > base_lines
