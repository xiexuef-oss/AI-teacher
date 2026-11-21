"""本地持久化队列：条件领取、逐文件检查点、过期租约恢复。"""

import logging
import re
from contextlib import contextmanager
from datetime import timedelta
from threading import Event, Thread

from sqlalchemy import or_, select, update

from tutor_api.db import new_id
from tutor_api.proto_models import DocumentImportCandidate, DocumentImportFile, DocumentImportJob
from tutor_api.services.document_durable_ocr import DurableOcrProgress
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_import_service import cleanup_expired, job_candidates, job_files
from tutor_api.services.document_ocr import recognize_pages
from tutor_api.services.document_ocr_progress import LocalOcrProgress
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.document_split import split_pages

logger = logging.getLogger(__name__)
_HEARTBEAT_MAX_INTERVAL = 1.0
_ANSWER_FILENAME = re.compile(r"答案|解析|(?:^|[_. -])answers?(?:[_. -]|$)", re.I)


@contextmanager
def _keep_lease(factory, settings, clock, job_id, lease, stopping):
    finished = Event()

    def renew():
        interval = min(_HEARTBEAT_MAX_INTERVAL, settings.import_worker_lease_seconds / 3)
        while not finished.wait(interval):
            if stopping.is_set():
                return
            try:
                with factory() as db:
                    now = clock()
                    job = _active(db, job_id, lease, now)
                    if job is None or stopping.is_set():
                        return
                    job.lease_until = now + timedelta(seconds=settings.import_worker_lease_seconds)
                    db.commit()
            except Exception:
                logger.exception("Document import lease renewal failed; job=%s", job_id)
                return

    thread = Thread(target=renew, name="document-import-lease", daemon=True)
    thread.start()
    try:
        yield
    finally:
        finished.set()
        thread.join()


def _active(db, job_id, lease, now):
    # 先取得写事务并条件校验，防止校验后取消/另一个租约接管造成迟到提交。
    guarded = db.execute(
        update(DocumentImportJob)
        .where(
            DocumentImportJob.id == job_id,
            DocumentImportJob.status == "processing",
            DocumentImportJob.lease_id == lease,
            DocumentImportJob.expires_at > now,
            DocumentImportJob.lease_until > now,
        )
        .values(lease_id=lease)
    )
    if guarded.rowcount == 1:
        return db.get(DocumentImportJob, job_id, populate_existing=True)
    return None


def _reconcile_files(db, job, files, settings):
    """Finalize suggestions atomically; never replace a human-edited workspace."""
    candidates = job_candidates(db, job.id)
    by_file = {file.id: file for file in files}

    def first_location(item):
        return (
            tuple(item.locations_json[0].get(k) for k in ("file_id", "page", "block"))
            if item.locations_json
            else None
        )

    originals = {first_location(item): item for item in candidates}
    if len(originals) != len(candidates):
        return  # Oversized fragments share an anchor; keep their existing stable IDs.
    for item in candidates:
        if item.question_id or item.confirmed_by or item.error_json:
            return
        file = by_file.get((item.locations_json or [{}])[0].get("file_id"))
        if file is None:
            return
        if file.kind != "json":
            baseline = {
                tuple([file.id, p["locations"][0]["page"], p["locations"][0]["block"]]): p
                for p in split_pages(file.pages_json)
            }
            piece = baseline.get(first_location(item))
            if (
                not piece
                or item.payload_json is not None
                or item.text != piece["text"]
                or item.title
                != (piece["text"].strip().splitlines() or ["待人工录入的候选题"])[0][:120]
            ):
                return
    pages = []
    uncertain = any(
        not getattr(file, "_upload_order_known", False) or file.status == "failed" for file in files
    )
    for file in files:
        for page in file.pages_json:
            annotated = {
                **page,
                "_file_id": file.id,
                "_order_uncertain": uncertain,
                "_answer_file": bool(_ANSWER_FILENAME.search(file.filename)),
            }
            if file.kind == "json":
                original = originals.get((file.id, page["number"], None))
                if original is None:
                    return
                annotated["_payload"] = original.payload_json
            pages.append(annotated)
    pieces = split_pages(pages)
    if len(pieces) > settings.import_max_candidates:
        return
    retained = set()
    for ordinal, piece in enumerate(pieces):
        key = tuple(piece["locations"][0].get(k) for k in ("file_id", "page", "block"))
        item = originals.get(key)
        if item is None:
            item = DocumentImportCandidate(
                id=new_id(), job_id=job.id, confirmed_by=None, question_id=None, error_json=None
            )
            db.add(item)
        retained.add(item.id)
        item.ordinal = ordinal
        item.title = (piece["text"].strip().splitlines() or ["待人工录入的候选题"])[0][:120]
        item.text, item.locations_json = piece["text"], piece["locations"]
        item.warnings_json = piece["warnings"] + ["尚未人工校对，不能直接入库。"]
        item.payload_json = piece["payload"]
    for item in candidates:
        if item.id not in retained:
            db.delete(item)


def process_next(
    factory,
    settings,
    clock,
    *,
    parser=parse_isolated,
    gateway=None,
    stopping=None,
    invocation_store=None,
):
    stopping = stopping if stopping is not None else Event()
    if stopping.is_set():
        return False
    now, lease = clock(), new_id()
    available = or_(
        DocumentImportJob.status == "queued",
        (DocumentImportJob.status == "processing") & (DocumentImportJob.lease_until <= now),
    )
    with factory() as db:
        cleanup_expired(db, now)
        job_id = db.scalar(
            select(DocumentImportJob.id)
            .where(available)
            .order_by(DocumentImportJob.created_at)
            .limit(1)
        )
        if job_id is None:
            db.commit()
            return False
        claimed = db.execute(
            update(DocumentImportJob)
            .where(DocumentImportJob.id == job_id, available)
            .values(
                status="processing",
                lease_id=lease,
                lease_until=now + timedelta(seconds=settings.import_worker_lease_seconds),
                revision=DocumentImportJob.revision + 1,
                updated_at=now,
            )
        )
        db.commit()
        if claimed.rowcount != 1:
            return False
        file_ids = [
            file.id for file in job_files(db, job_id) if file.status in {"pending", "processing"}
        ]
    for file_id in file_ids:
        if stopping.is_set():
            return True
        with factory() as db:
            job = _active(db, job_id, lease, clock())
            if job is None:
                return True
            file = db.get(DocumentImportFile, file_id)
            file.status = "processing"
            data, kind = file.content, file.kind
            is_answer_docx = kind == "docx" and bool(_ANSWER_FILENAME.search(file.filename))
            job.lease_until = clock() + timedelta(seconds=settings.import_worker_lease_seconds)
            db.commit()
        with _keep_lease(factory, settings, clock, job_id, lease, stopping):
            text_only = False
            try:
                try:
                    pages = parser(data, kind, settings)["pages"]
                except DocumentParseError as error:
                    if not is_answer_docx or error.code != "media_limit":
                        raise
                    pages = parser(data, "docx_answer_text", settings)["pages"]
                    text_only = True

                def checkpoint():
                    if stopping.is_set():
                        return False
                    with factory() as db:
                        current = _active(db, job_id, lease, clock())
                        if current is None:
                            return False
                        current.lease_until = clock() + timedelta(
                            seconds=settings.import_worker_lease_seconds
                        )
                        db.commit()
                        return True

                progress = (
                    DurableOcrProgress(
                        factory,
                        clock,
                        job_id,
                        file_id,
                        lease,
                        _active,
                        settings=settings,
                        gateway=gateway,
                        store=invocation_store,
                    )
                    if invocation_store is not None
                    else LocalOcrProgress(
                        factory, clock, job_id, file_id, lease, _active, gateway=gateway
                    )
                )
                pages = recognize_pages(
                    pages,
                    data,
                    kind,
                    settings,
                    None if text_only else gateway,
                    parser,
                    job_id,
                    checkpoint,
                    progress=progress,
                )
                problem = None
            except DocumentParseError as error:
                pages, problem = [], f"{error.code}: {error.message}"
            except Exception:
                logger.exception("Document import parser failed; job=%s file=%s", job_id, file_id)
                pages, problem = [], "parse_failed: 文件处理失败，可取消任务后重新上传"
            if stopping.is_set():
                return True
            with factory() as db:
                job = _active(db, job_id, lease, clock())
                if job is None:
                    return True
                file = db.get(DocumentImportFile, file_id)
                candidates = job_candidates(db, job_id)
                # 单文件结果和候选题在同一事务提交，恢复时不会重复创建。
                pieces = [] if text_only else split_pages(pages)
                if len(candidates) + len(pieces) > settings.import_max_candidates:
                    problem = "candidate_limit: 候选题数量超过上限，请拆分任务"
                if problem:
                    file.status, file.problems_json = "failed", [problem]
                else:
                    file.pages_json = [
                        {k: v for k, v in page.items() if not k.startswith("_")} for page in pages
                    ]
                    file.status = (
                        "needs_ocr"
                        if any(page["method"] in {"unavailable", "ocr_mock"} for page in pages)
                        else "ready"
                    )
                    file.problems_json = []
                    for index, piece in enumerate(pieces):
                        text = piece["text"]
                        db.add(
                            DocumentImportCandidate(
                                id=new_id(),
                                job_id=job_id,
                                ordinal=len(candidates) + index,
                                title=(text.strip().splitlines() or ["待人工录入的候选题"])[0][
                                    :120
                                ],
                                text=text,
                                locations_json=[
                                    {"file_id": file.id, **location}
                                    for location in piece["locations"]
                                ],
                                warnings_json=piece["warnings"] + ["尚未人工校对，不能直接入库。"],
                                payload_json=piece["payload"],
                                confirmed_by=None,
                                question_id=None,
                                error_json=None,
                            )
                        )
                job.revision += 1
                job.updated_at = clock()
                db.commit()
    if stopping.is_set():
        return True
    with factory() as db:
        job = _active(db, job_id, lease, clock())
        if job is not None:
            files = job_files(db, job_id)
            _reconcile_files(db, job, files, settings)
            failed = sum(file.status == "failed" for file in files)
            job.status = (
                "failed"
                if failed == len(files)
                else "partial_failure"
                if failed
                else "needs_review"
            )
            job.message = "请人工核对提取文本、公式、图像与题目边界；未确认的内容不能导入题库。"
            job.lease_id = job.lease_until = None
            job.revision += 1
            job.updated_at = clock()
            db.commit()
    return True


class ImportWorker:
    def __init__(self, factory, settings, clock, gateway=None, invocation_store=None):
        self.factory, self.settings, self.clock = factory, settings, clock
        self.gateway = gateway
        self.invocation_store = invocation_store
        self.stop = Event()
        self.thread = Thread(target=self.run, name="document-import", daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                worked = process_next(
                    self.factory,
                    self.settings,
                    self.clock,
                    gateway=self.gateway,
                    stopping=self.stop,
                    invocation_store=self.invocation_store,
                )
            except Exception:
                logger.exception("Document import worker iteration failed")
                worked = False
            if not worked:
                self.stop.wait(1)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        # Lifespan disposes the engine immediately after close. Wait for the
        # bounded in-flight parser/gateway and its heartbeat to finish first.
        self.thread.join()
