"""Local-only student scan Mock routes."""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.errors import ApiError
from tutor_api.idempotency import run_idempotent
from tutor_api.schemas import MediaBlobIn, MediaUploadIn, ScanConfirmIn, ScanCreateIn
from tutor_api.services import scan_service as service


class PrivateScanRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private(request):
            headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
            try:
                response = await handler(request)
            except ApiError as error:
                error.headers.update(headers)
                raise
            except RequestValidationError as error:
                response = await request.app.exception_handlers[RequestValidationError](
                    request, error
                )
            response.headers.update(headers)
            return response

        return private


router = APIRouter(route_class=PrivateScanRoute)


def scan_ctx(ctx: Ctx = Depends(student_ctx)):
    service.store(ctx)
    return ctx


@router.post("/scans/uploads")
def create_upload(body: MediaUploadIn, ctx: Ctx = Depends(scan_ctx)):
    service.store(ctx)
    return run_idempotent(ctx, body, 201, lambda _: service.create_upload(ctx, body))


@router.put("/scans/uploads/{media_id}/content")
def upload(media_id: UUID, body: MediaBlobIn, ctx: Ctx = Depends(scan_ctx)):
    service.store(ctx)
    service.blob(ctx, str(media_id))
    return run_idempotent(ctx, body, 200, lambda _: service.upload(ctx, str(media_id), body))


@router.get("/scans/uploads/{media_id}/content")
def preview_upload(media_id: UUID, ctx: Ctx = Depends(student_ctx)):
    return ok(service.preview_upload(ctx, str(media_id)))


@router.post("/scans")
def create_scan(body: ScanCreateIn, ctx: Ctx = Depends(scan_ctx)):
    service.store(ctx)
    service.blob(ctx, str(body.media_id), uploaded=True)
    return run_idempotent(ctx, body, 202, lambda _: service.create(ctx, body))


@router.get("/scans/{scan_id}")
def get_scan(scan_id: UUID, ctx: Ctx = Depends(scan_ctx)):
    service.store(ctx)
    return ok(service.owned(ctx, str(scan_id)).payload, headers={"Cache-Control": "no-store"})


@router.post("/scans/{scan_id}/confirm")
def confirm_scan(scan_id: UUID, body: ScanConfirmIn, ctx: Ctx = Depends(scan_ctx)):
    service.store(ctx)
    service.owned(ctx, str(scan_id))
    return run_idempotent(ctx, body, 200, lambda _: service.confirm(ctx, str(scan_id), body))
