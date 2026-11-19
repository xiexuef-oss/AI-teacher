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
)


@pytest.fixture
def font():
    return Path(reportlab_path).parent / "fonts" / "Vera.ttf"


def test_two_pdfs_have_separate_content_and_a4_pages(font):
    question = PaperItem(code="AB123", page_token="opaque-page", stem="Compute 2 + 2.")
    student = PdfReader(BytesIO(render_student([question], font)))
    solutions = PdfReader(BytesIO(render_solutions([SolutionItem("AB123", "Answer: four")], font)))
    assert "Compute 2 + 2." in student.pages[0].extract_text()
    assert "AB123" in student.pages[0].extract_text()
    assert "Answer: four" not in student.pages[0].extract_text()
    assert "Answer: four" in solutions.pages[0].extract_text()
    assert float(student.pages[0].mediabox.width) == pytest.approx(595.276, abs=0.001)


def test_long_question_flows_without_truncation(font):
    stem = ("The question continues here. " * 500) + "\nEnd of question."
    student = PdfReader(BytesIO(render_student([PaperItem("AB123", "opaque-page", stem)], font)))
    assert len(student.pages) > 1
    assert "End of question." in "".join(page.extract_text() for page in student.pages)
    assert all("AB123" in page.extract_text() for page in student.pages)
