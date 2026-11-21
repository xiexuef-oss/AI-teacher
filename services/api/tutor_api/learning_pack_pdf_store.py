"""Private immutable PDF objects for published learning packs."""

import json
import re
from contextlib import closing
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

from tutor_api.blob_store import BlobNotFound, BlobStorageUnavailable
from tutor_api.models import LearningJob, LearningPackCommand, LearningPackPublication
from tutor_api.s3_blob_store import local_s3_client

MAX_PDF_BYTES = 2**24 - 1
_KEY = re.compile(
    r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/"
    r"(?:student|solution)-([0-9a-f]{64})\.pdf"
)


class S3LearningPackPdfStore:
    def __init__(self, client, *, bucket: str, prefix: str):
        if not bucket or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/", prefix):
            raise ValueError("Invalid paper PDF storage namespace")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self._cleanup_cursor = None

    def _object_key(self, key: str) -> tuple[str, str]:
        match = _KEY.fullmatch(key)
        if match is None:
            raise ValueError("Invalid paper PDF key")
        return self.prefix + key, match[1]

    def write(self, key: str, data: bytes) -> None:
        object_key, digest = self._object_key(key)
        if not 0 < len(data) <= MAX_PDF_BYTES or sha256(data).hexdigest() != digest:
            raise ValueError("Paper PDF bytes must match their content key")
        from botocore.exceptions import ClientError

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType="application/pdf",
                IfNoneMatch="*",
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise BlobStorageUnavailable("Paper PDF write failed") from None
        except Exception:
            raise BlobStorageUnavailable("Paper PDF write failed") from None

    def read(self, key: str) -> bytes:
        object_key, digest = self._object_key(key)
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key)
            with closing(response["Body"]) as body:
                length = response["ContentLength"]
                if type(length) is not int or not 0 < length <= MAX_PDF_BYTES:
                    raise ValueError("Invalid paper PDF length")
                data = body.read(length + 1)
            if len(data) != length or sha256(data).hexdigest() != digest:
                raise ValueError("Invalid paper PDF digest")
            return data
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                raise BlobNotFound() from None
            raise BlobStorageUnavailable("Paper PDF read failed") from None
        except Exception:
            raise BlobStorageUnavailable("Paper PDF read failed") from None

    def purge_unreferenced(self, factory, now) -> int:
        """Scan one bounded page and delete aged objects of immutable terminal jobs."""
        from botocore.exceptions import ClientError

        cutoff = now - timedelta(days=1)
        params = {"Bucket": self.bucket, "Prefix": self.prefix, "MaxKeys": 100}
        if self._cleanup_cursor is not None:
            params["ContinuationToken"] = self._cleanup_cursor
        page = self.client.list_objects_v2(**params)
        candidates = []
        for item in page.get("Contents", []):
            key = item["Key"].removeprefix(self.prefix)
            if (
                item["Key"].startswith(self.prefix)
                and _KEY.fullmatch(key)
                and item["LastModified"] <= cutoff
            ):
                candidates.append((key, item["ETag"]))
        owners = {key.split("/", 1)[0] for key, _ in candidates}
        with factory() as db:
            terminal = dict(
                db.execute(
                    select(LearningJob.id, LearningPackPublication.manifest_json)
                    .join(LearningPackCommand, LearningPackCommand.job_id == LearningJob.id)
                    .outerjoin(
                        LearningPackPublication, LearningPackPublication.job_id == LearningJob.id
                    )
                    .where(
                        LearningJob.id.in_(owners),
                        LearningJob.status.in_(("succeeded", "failed", "cancelled")),
                    )
                ).all()
            )
        removed = 0
        for key, tag in candidates:
            job_id = key.split("/", 1)[0]
            if job_id not in terminal:
                continue
            manifest = terminal[job_id] or {}
            if key in manifest.get("pdf_objects", {}).values():
                continue
            try:
                self.client.delete_object(Bucket=self.bucket, Key=self.prefix + key, IfMatch=tag)
                removed += 1
            except ClientError as exc:
                if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") not in {404, 412}:
                    raise BlobStorageUnavailable("Paper PDF cleanup failed") from None
        self._cleanup_cursor = page.get("NextContinuationToken")
        return removed


def local_pdf_store(config_path: Path) -> S3LearningPackPdfStore:
    """Create an explicitly configured loopback PDF store for deployment rehearsals."""
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    client = local_s3_client(
        **{name: config[name] for name in ("endpoint", "region", "access_key", "secret_key")}
    )
    return S3LearningPackPdfStore(client, bucket=config["bucket"], prefix=config["prefix"])
