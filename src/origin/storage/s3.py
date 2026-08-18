"""Amazon S3 document store — the CockroachDB-submission profile.

Only used when ORIGIN_STORAGE=s3. The DataHub submission runs on the filesystem
backend and never imports this module, so boto3 is a soft dependency in practice
even though it is declared.
"""

from __future__ import annotations

import logging

from .base import DocumentStore

log = logging.getLogger(__name__)


class S3AccessError(RuntimeError):
    """S3 rejected the call in a way the operator needs to fix."""


class S3DocumentStore(DocumentStore):
    name = "s3"

    def __init__(self, *, bucket: str, prefix: str = "", region: str | None = None):
        if not bucket:
            raise ValueError("ORIGIN_S3_BUCKET must be set when ORIGIN_STORAGE=s3")

        import boto3

        self._client = boto3.client("s3", region_name=region)
        self._bucket = bucket
        # Normalise so joining never produces a double or leading slash, which
        # S3 treats as a real (and confusing) key segment.
        self._prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        if not key or key.startswith("/"):
            raise ValueError(f"invalid document key {key!r}")
        return f"{self._prefix}/{key}" if self._prefix else key

    def put(self, key: str, data: bytes) -> str:
        from botocore.exceptions import ClientError

        try:
            self._client.put_object(
                Bucket=self._bucket, Key=self._key(key), Body=data
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"AccessDenied", "NoSuchBucket", "InvalidAccessKeyId"}:
                raise S3AccessError(
                    f"S3 rejected a write to s3://{self._bucket}/{self._key(key)}: "
                    f"{code}. Check the bucket exists, the region matches, and "
                    "the credentials can PutObject. To proceed without AWS, set "
                    "ORIGIN_STORAGE=local."
                ) from exc
            raise
        return self.uri(key)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(
                Bucket=self._bucket, Key=self._key(key)
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404"}:
                raise KeyError(key) from exc
            raise
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key(key))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{self._key(key)}"
