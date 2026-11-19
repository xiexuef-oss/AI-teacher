"""Locator metadata codec fixtures, not a claim of real DOC conversion."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from tutor_api.errors import ApiError
from tutor_api.models import QuestionVersion
from tutor_api.proto_models import DocumentImportFile, DocumentImportJob
from tutor_api.schemas import QuestionProvenance
from tutor_api.services.question_provenance import derived_provenance, document_origins


class Db:
    def __init__(self, actor="owner", kind="docx"):
        self.job = DocumentImportJob(id="job", actor_id=actor)
        self.file = DocumentImportFile(
            id="file",
            job_id="job",
            kind=kind,
            sha256="a" * 64,
            pages_json=[{"number": 2, "text": "not copied"}],
        )

    def get(self, model, key):
        return {DocumentImportJob: self.job, DocumentImportFile: self.file}[model]


@pytest.mark.parametrize(
    "kind,locator",
    [
        ("pdf", "pdf_page"),
        ("doc", "word_fragment"),
        ("docx", "word_fragment"),
        ("png", "image_page"),
        ("jpeg", "image_page"),
        ("json", "json_fragment"),
    ],
)
def test_file_kind_and_index_are_declared_metadata_not_text_offsets(kind, locator):
    db = Db(kind=kind)
    loc = {"file_id": "file", "page": 2, "block": 8}
    result = document_origins(db, actor_id="owner", job_id="job", locations=[loc, deepcopy(loc)])
    assert [v.model_dump() for v in result] == [
        {
            "file_sha256": "a" * 64,
            "file_kind": kind,
            "locator_kind": locator,
            "index": 2,
            "declared_block": 8,
        }
    ]


def test_locator_owner_check_precedes_file_metadata_read():
    db = Db(actor="other")
    db.file.sha256 = "foreign-secret-hash"
    with pytest.raises(ApiError) as caught:
        document_origins(
            db,
            actor_id="owner",
            job_id="job",
            locations=[{"file_id": "file", "page": 2, "block": None}],
        )
    assert "foreign-secret-hash" not in str(caught.value)


def test_derivation_copies_deeply_and_null_stays_unknown():
    previous = QuestionVersion(
        id="v1", question_id="q", version=4, created_at=datetime.now(UTC), provenance_json=None
    )
    assert derived_provenance(previous) is None
    previous.provenance_json = QuestionProvenance(
        source_snapshot={
            "source_type": "self_authored",
            "source_category": "foundation",
            "source_name": "engineering fixture",
            "source_year": None,
            "source_license": "self authored",
            "source_url": None,
            "is_engineering_sample": False,
            "label": "declared source",
        },
        origins=[
            {
                "file_sha256": "a" * 64,
                "file_kind": "docx",
                "locator_kind": "word_fragment",
                "index": 2,
                "declared_block": None,
            }
        ],
        relation="declared",
        parent_version=None,
        access="metadata_only",
    ).model_dump()
    old = deepcopy(previous.provenance_json)
    derived = derived_provenance(previous)
    assert derived.relation == "derived_unverified" and derived.parent_version == 4
    derived.origins[0].index = 9
    derived.source_snapshot.source_name = "changed local copy"
    assert previous.provenance_json == old
