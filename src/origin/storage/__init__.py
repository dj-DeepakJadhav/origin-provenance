"""Document storage selection.

``local`` for the DataHub submission (no AWS), ``s3`` for the CockroachDB
submission (which requires an AWS service). Everything downstream is unaware of
which is in use.
"""

from __future__ import annotations

from functools import lru_cache

from .. import config
from .base import DocumentStore
from .local_fs import LocalDocumentStore

__all__ = ["DocumentStore", "LocalDocumentStore", "get_store"]


@lru_cache(maxsize=1)
def get_store() -> DocumentStore:
    cfg = config.load()

    if cfg.storage == "s3":
        from .s3 import S3DocumentStore

        return S3DocumentStore(
            bucket=cfg.s3_bucket,
            prefix=cfg.s3_prefix,
            region=cfg.aws_region,
        )

    return LocalDocumentStore(cfg.storage_path)
