"""Authenticated, local-only media lifecycle and review-context preview."""

from uuid import UUID

from fastapi import APIRouter, Depends

from tutor_api.deps import Ctx, ok, reviewer_ctx, student_ctx
from tutor_api.errors import ApiError
from tutor_api.idempotency import run_idempotent
from tutor_api.schemas import (
    MediaBlobIn,
    MediaConfirmIn,
    MediaDeleteIn,
    MediaReviewConfirmationIn,
    MediaUploadIn,
)
from tutor_api.services import media_service as service

router = APIRouter()

_PRIVATE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def private_content(action):
    try:
        return ok(action(), headers=_PRIVATE_HEADERS)
    except ApiError as error:
        error.headers.update(_PRIVATE_HEADERS)
        raise


@router.post("/media/uploads")
def create_upload(body: MediaUploadIn, ctx: Ctx = Depends(reviewer_ctx)):
    service.store(ctx)
    return run_idempotent(ctx, body, 201, lambda _: service.create_upload(ctx, body))


@router.put("/media/{media_id}/content")
def upload(media_id: UUID, body: MediaBlobIn, ctx: Ctx = Depends(reviewer_ctx)):
    service.store(ctx)
    return run_idempotent(ctx, body, 200, lambda _: service.upload(ctx, str(media_id), body))


@router.post("/media/{media_id}/confirm")
def confirm(
    media_id: UUID,
    body: MediaConfirmIn,
    ctx: Ctx = Depends(reviewer_ctx),
):
    service.store(ctx)
    return run_idempotent(ctx, body, 200, lambda _: service.confirm(ctx, str(media_id), body))


@router.get("/media/{media_id}/content")
def content(media_id: UUID, ctx: Ctx = Depends(reviewer_ctx)):
    return private_content(lambda: service.content(ctx, str(media_id)))


@router.post("/media/{media_id}/delete")
def delete(media_id: UUID, body: MediaDeleteIn, ctx: Ctx = Depends(reviewer_ctx)):
    service.store(ctx)
    response = run_idempotent(ctx, body, 200, lambda _: service.delete(ctx, str(media_id)))
    service.purge_deleted(ctx, str(media_id))
    return response


@router.get("/admin/questions/{question_id}/media/{media_id}/content")
def question_content(question_id: UUID, media_id: UUID, ctx: Ctx = Depends(reviewer_ctx)):
    return private_content(lambda: service.content(ctx, str(media_id), str(question_id)))


@router.get("/questions/{question_id}/media/{media_id}/content")
def published_question_media(question_id: UUID, media_id: UUID, ctx: Ctx = Depends(student_ctx)):
    return private_content(lambda: service.student_content(ctx, str(question_id), str(media_id)))


@router.post("/admin/questions/{question_id}/media/{media_id}/review-confirmations")
def confirm_review(
    question_id: UUID,
    media_id: UUID,
    body: MediaReviewConfirmationIn,
    ctx: Ctx = Depends(reviewer_ctx),
):
    service.store(ctx)
    return run_idempotent(
        ctx, body, 200, lambda _: service.confirm_review(ctx, str(question_id), str(media_id), body)
    )
