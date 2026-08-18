"""Provider selection."""

from __future__ import annotations

from functools import lru_cache

from .. import config
from .base import Completion, Provider
from .local import LocalProvider, classify_license_text

__all__ = [
    "Completion",
    "Provider",
    "LocalProvider",
    "classify_license_text",
    "get_provider",
]


@lru_cache(maxsize=1)
def get_provider() -> Provider:
    """Return the configured provider.

    Cached: both implementations are stateless and cheap to reuse, and the
    Bedrock client holds a connection pool worth keeping.
    """
    cfg = config.load()

    if cfg.provider == "bedrock":
        from .bedrock import BedrockProvider

        return BedrockProvider(
            region=cfg.aws_region,
            text_model=cfg.bedrock_text_model,
            embed_model=cfg.bedrock_embed_model,
            embed_dim=cfg.embed_dim,
        )

    if cfg.provider == "sagemaker":
        from .sagemaker import SageMakerProvider

        return SageMakerProvider(
            region=cfg.aws_region,
            endpoint_name=cfg.sagemaker_endpoint_name,
            embed_dim=cfg.embed_dim,
        )

    return LocalProvider(embed_dim=cfg.embed_dim)

