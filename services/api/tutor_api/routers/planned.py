"""契约里已规划、本阶段未实现的操作：鉴权照常进行，之后统一返回 501。

拍题 OCR、媒体上传、家长周报、内容审核不在 ADR-006 切片内。这里不做任何"看起来能用"的假实现。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from tutor_api.auth import Principal
from tutor_api.deps import get_principal
from tutor_api.errors import ApiError

router = APIRouter()


def _not_implemented(operation: str) -> ApiError:
    return ApiError(501, "not_implemented", f"{operation} 已在契约中规划，本阶段尚未实现")


@router.post("/media/uploads")
def create_media_upload(_: Principal = Depends(get_principal)) -> None:
    raise _not_implemented("createMediaUpload")


@router.post("/scans")
def create_scan(_: Principal = Depends(get_principal)) -> None:
    raise _not_implemented("createScan")


@router.get("/scans/{scan_id}")
def get_scan(scan_id: str, _: Principal = Depends(get_principal)) -> None:
    raise _not_implemented("getScan")


@router.post("/scans/{scan_id}/confirm")
def confirm_scan(scan_id: str, _: Principal = Depends(get_principal)) -> None:
    raise _not_implemented("confirmScan")


@router.get("/parents/students/{student_id}/weekly")
def get_parent_weekly(student_id: str, _: Principal = Depends(get_principal)) -> None:
    raise _not_implemented("getParentWeekly")


@router.post("/admin/questions/{question_id}/review")
def review_question(question_id: str, _: Principal = Depends(get_principal)) -> None:
    raise _not_implemented("reviewQuestion")
