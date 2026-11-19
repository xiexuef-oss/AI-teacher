"""One normalization corpus guards Python/Dart fixed redemption bodies."""

import json
from pathlib import Path

import pytest

from tutor_api.services.parent_service import normalize_code

CASES = json.loads(
    (
        Path(__file__).resolve().parents[2] / "contracts/fixtures/parent_invite_normalization.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=[f"case-{i}" for i in range(len(CASES))])
def test_shared_invitation_normalization_matches_server(case):
    assert normalize_code(case["input"]) == case["normalized"]
