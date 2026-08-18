"""Configuration, loaded from the environment with sane defaults.

Nothing here reaches out to a network. Import is always safe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or contradictory."""


@dataclass(frozen=True)
class Config:
    database_url: str
    datahub_gms_url: str
    datahub_token: str | None
    provider: str
    storage: str
    storage_path: str
    s3_bucket: str
    s3_prefix: str
    aws_region: str
    bedrock_text_model: str
    bedrock_embed_model: str
    sagemaker_endpoint_name: str
    embed_dim: int

    @property
    def uses_aws(self) -> bool:
        """Whether this configuration touches AWS at all.

        The DataHub submission runs with this False — that hackathon requires a
        DataHub component and nothing else. The CockroachDB submission requires
        at least one AWS service, so it runs with this True. Asserted by
        ``require_aws_for_cockroachdb``.
        """
        return self.provider in {"bedrock", "sagemaker"} or self.storage == "s3"

    def require_database(self) -> str:
        if not self.database_url:
            raise ConfigError(
                "DATABASE_URL is not set. Copy .env.example to .env and paste the "
                "connection string from CockroachDB Cloud > Connect."
            )
        return self.database_url

    def require_aws_for_cockroachdb(self) -> None:
        """Guard the CockroachDB submission's mandatory AWS requirement."""
        if not self.uses_aws:
            raise ConfigError(
                "This configuration uses no AWS service, which is valid for the "
                "DataHub submission but disqualifying for the CockroachDB one. "
                "Set ORIGIN_PROVIDER=bedrock|sagemaker and/or ORIGIN_STORAGE=s3."
            )


@lru_cache(maxsize=1)
def load() -> Config:
    provider = os.getenv("ORIGIN_PROVIDER", "local").strip().lower()
    if provider not in {"local", "bedrock", "sagemaker"}:
        raise ConfigError(
            f"ORIGIN_PROVIDER must be 'local', 'bedrock', or 'sagemaker', got {provider!r}"
        )

    try:
        embed_dim = int(os.getenv("ORIGIN_EMBED_DIM", "1024"))
    except ValueError as exc:
        raise ConfigError("ORIGIN_EMBED_DIM must be an integer") from exc

    # The schema declares VECTOR(1024). Drifting from that produces an error at
    # insert time that reads as a database problem, so catch it here instead.
    if embed_dim != 1024:
        raise ConfigError(
            f"ORIGIN_EMBED_DIM is {embed_dim} but sql/001_schema.sql declares "
            "VECTOR(1024). Change both together or neither."
        )

    storage = os.getenv("ORIGIN_STORAGE", "local").strip().lower()
    if storage not in {"local", "s3"}:
        raise ConfigError(
            f"ORIGIN_STORAGE must be 'local' or 's3', got {storage!r}"
        )

    s3_bucket = os.getenv("ORIGIN_S3_BUCKET", "").strip()
    if storage == "s3" and not s3_bucket:
        raise ConfigError("ORIGIN_STORAGE=s3 requires ORIGIN_S3_BUCKET to be set")

    token = os.getenv("DATAHUB_TOKEN", "").strip()

    return Config(
        database_url=os.getenv("DATABASE_URL", "").strip(),
        datahub_gms_url=os.getenv(
            "DATAHUB_GMS_URL", "http://localhost:8080"
        ).rstrip("/"),
        datahub_token=token or None,
        provider=provider,
        storage=storage,
        storage_path=os.getenv("ORIGIN_STORAGE_PATH", "data/documents").strip(),
        s3_bucket=s3_bucket,
        s3_prefix=os.getenv("ORIGIN_S3_PREFIX", "origin/documents").strip(),
        aws_region=os.getenv("AWS_REGION", "us-east-1").strip(),
        bedrock_text_model=os.getenv(
            "BEDROCK_TEXT_MODEL", "anthropic.claude-sonnet-4-5-20250929-v1:0"
        ).strip(),
        bedrock_embed_model=os.getenv(
            "BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0"
        ).strip(),
        sagemaker_endpoint_name=os.getenv(
            "SAGEMAKER_ENDPOINT_NAME", "origin-text-generator"
        ).strip(),
        embed_dim=embed_dim,
    )

