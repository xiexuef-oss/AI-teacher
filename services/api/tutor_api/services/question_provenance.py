"""Minimal version-bound document metadata; never a document access capability."""

from sqlalchemy.orm import Session

from tutor_api.errors import unprocessable
from tutor_api.models import QuestionVersion
from tutor_api.proto_models import DocumentImportFile, DocumentImportJob
from tutor_api.schemas import QuestionOriginLocation, QuestionProvenance

_LOCATORS = {
    "pdf": "pdf_page",
    "doc": "word_fragment",
    "docx": "word_fragment",
    "png": "image_page",
    "jpeg": "image_page",
    "json": "json_fragment",
}


def document_origins(
    db: Session, *, actor_id: str, job_id: str, locations: list[dict]
) -> list[QuestionOriginLocation]:
    job = db.get(DocumentImportJob, job_id)
    if (
        job is None
        or job.actor_id != actor_id
        or not isinstance(locations, list)
        or len(locations) > 2000
    ):
        raise unprocessable("locations", "原文定位不属于当前任务或格式无效")
    origins, seen = [], set()
    for location in locations:
        if (
            not isinstance(location, dict)
            or set(location) != {"file_id", "page", "block"}
            or not isinstance(location["file_id"], str)
        ):
            raise unprocessable("locations", "原文定位格式无效")
        file = db.get(DocumentImportFile, location["file_id"])
        page, block = location["page"], location["block"]
        if (
            file is None
            or file.job_id != job.id
            or file.kind not in _LOCATORS
            or not isinstance(file.pages_json, list)
            or type(page) is not int
            or page < 1
            or (block is not None and (type(block) is not int or block < 1))
            or page
            not in {
                p.get("number")
                for p in file.pages_json
                if isinstance(p, dict) and type(p.get("number")) is int
            }
        ):
            raise unprocessable("locations", "原文定位不属于当前任务或页/片段不存在")
        origin = QuestionOriginLocation(
            file_sha256=file.sha256,
            file_kind=file.kind,
            locator_kind=_LOCATORS[file.kind],
            index=page,
            declared_block=block,
        )
        identity = (origin.file_sha256, origin.file_kind, origin.locator_kind, page, block)
        if identity not in seen:
            origins.append(origin)
            seen.add(identity)
    return origins


def derived_provenance(previous: QuestionVersion) -> QuestionProvenance | None:
    if previous.provenance_json is None:
        return None
    return QuestionProvenance.model_validate(previous.provenance_json).model_copy(
        deep=True, update={"relation": "derived_unverified", "parent_version": previous.version}
    )
