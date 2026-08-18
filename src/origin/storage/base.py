"""Document storage: where raw document bytes live.

This exists to make the AWS dependency optional rather than structural. ORIGIN
ships two submission profiles:

  * ``local``  — filesystem. No AWS, no credentials. Used for the DataHub
    submission, which requires a DataHub component and nothing else.
  * ``s3``     — Amazon S3. Used for the CockroachDB submission, which requires
    at least one AWS service.

Neither is a lesser build. The provenance ledger, the point-in-time queries, the
policy gate and the takedown impact query are all storage-agnostic and identical
in both. What changes is where the bytes sit and who classifies novel licence
strings — not what the product does.

The stored URI is recorded in ``documents.source_uri`` and mirrored into the
DataHub graph, so the graph stays accurate whichever backend is in play.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class DocumentStore(ABC):
    """Content-addressed blob storage for raw documents."""

    #: Recorded alongside stored documents so the ledger says which backend
    #: held the bytes. An audit that cannot locate the artefact is not an audit.
    name: str

    @abstractmethod
    def put(self, key: str, data: bytes) -> str:
        """Store bytes under ``key``. Returns the durable URI.

        Must be idempotent: storing identical bytes under the same key twice is
        not an error. Ingestion is re-run constantly and must not be punished
        for it.
        """

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve bytes. Raises ``KeyError`` if absent."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether ``key`` is present."""

    @abstractmethod
    def uri(self, key: str) -> str:
        """The durable URI for ``key``, whether or not it exists yet."""
