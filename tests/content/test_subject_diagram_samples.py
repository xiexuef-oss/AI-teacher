"""SUBJECT302/303 engineering examples: givens are complete before diagrams unlock."""

import re
from decimal import Decimal

from tutor_api.services.content_seed import load_seed, validate_seed


def samples():
    return {question["key"]: question for question in load_seed().questions}


def test_process_sample_stem_contains_all_required_edges():
    question = samples()["chem-process-reading"]
    stem = question["content"]["stem"]
    assert "原料→处理Ⅰ→分离→处理Ⅱ→产物" in stem
    assert "分离→支路" in stem
    assert "处理Ⅱ→处理Ⅰ" in stem
    assert question["teaching"]["visual"] == {
        "template_id": "chemical_process",
        "params": {"focus": 0, "branch": 1, "recycle": 1},
        "caption": "只定位题干已给出的流程关系，不推断物质、反应或操作。",
    }
    assert question["answer"]["value"] == ["B"]


def test_triangle_sample_coordinates_match_the_diagram_without_extra_construction():
    question = samples()["math-triangle-coordinate-proof"]
    givens = " ".join(question["content"]["proof"]["givens"])
    assert "A(0,0)" in givens and "B(1,0)" in givens and "C(0.35,0.65)" in givens
    assert question["answer_mode"] == "proof"
    visual = question["teaching"]["visual"]
    assert visual["template_id"] == "triangle_schematic"
    assert visual["params"] == {"apex_x": 0.35, "height": 0.65, "focus": 0}
    steps = question["answer"]["value"]["steps"]
    assert all(step["reason"] for step in steps)
    assert steps[-1]["stage"] == "conclusion"
    assert {step["stage"] for step in steps} <= {
        point["part"] for point in question["rubric"]["points"]
    }
    coordinates = {
        name: (Decimal(x), Decimal(y))
        for name, x, y in re.findall(r"([ABC])\(([\d.]+),([\d.]+)\)", givens)
    }
    squared_lengths = {
        (coordinates[a][0] - coordinates[b][0]) ** 2 + (coordinates[a][1] - coordinates[b][1]) ** 2
        for a, b in (("A", "B"), ("A", "C"), ("B", "C"))
    }
    assert len(squared_lengths) == 3
    reference = " ".join(step["text"] for step in steps)
    assert all(format(value.normalize(), "f") in reference for value in squared_lengths)


def test_new_engineering_samples_pass_the_existing_content_rules():
    assert validate_seed(load_seed()) == []
