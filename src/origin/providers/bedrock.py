"""Amazon Bedrock provider: Claude for reasoning, Titan for embeddings.

Bedrock requires per-model access to be granted explicitly in each region. The
failure when it has not been is an AccessDeniedException at invoke time, which
reads like a credentials problem and is not — so it is translated here into
something actionable.
"""

from __future__ import annotations

import json
import logging

from .base import Completion, Provider

log = logging.getLogger(__name__)


class BedrockAccessError(RuntimeError):
    """Bedrock rejected the call in a way the operator needs to fix."""


class BedrockProvider(Provider):
    def __init__(
        self,
        *,
        region: str,
        text_model: str,
        embed_model: str,
        embed_dim: int = 1024,
    ) -> None:
        # Imported lazily so the module is importable without boto3 configured.
        import boto3

        self._client = boto3.client("bedrock-runtime", region_name=region)
        self._region = region
        self._text_model = text_model
        self._embed_model = embed_model
        self._dim = embed_dim
        self.name = f"bedrock:{text_model}"

    @property
    def supports_generation(self) -> bool:
        return True

    @property
    def embed_dim(self) -> int:
        return self._dim

    def _invoke(self, model_id: str, payload: dict) -> dict:
        from botocore.exceptions import ClientError

        try:
            response = self._client.invoke_model(
                modelId=model_id, body=json.dumps(payload)
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"AccessDeniedException", "ValidationException"}:
                error_msg = exc.response.get("Error", {}).get("Message", "")
                raise BedrockAccessError(
                    f"Bedrock invocation rejected for {model_id!r} in {self._region} [{code}: {error_msg}]. "
                    "This occurs when Bedrock inference is blocked at the AWS Organisation Policy (SCP) level "
                    "or when model access has not been granted in Bedrock Console > Model access. "
                    "Set ORIGIN_PROVIDER=local for full local offline embeddings and classification."
                ) from exc
            raise
        return json.loads(response["body"].read())

    def embed(self, text: str) -> list[float]:
        body = self._invoke(
            self._embed_model,
            {"inputText": text, "dimensions": self._dim, "normalize": True},
        )
        embedding = body.get("embedding")
        if not embedding:
            raise RuntimeError(
                f"{self._embed_model} returned no embedding for a "
                f"{len(text)}-character input"
            )
        if len(embedding) != self._dim:
            raise RuntimeError(
                f"expected {self._dim}-dimensional embedding, got "
                f"{len(embedding)}. Check BEDROCK_EMBED_MODEL and "
                "ORIGIN_EMBED_DIM agree."
            )
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Titan's invoke_model is single-input. Batching would need the async
        # batch inference API, which is not worth the complexity at this volume.
        return [self.embed(t) for t in texts]

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> Completion:
        body = self._invoke(
            self._text_model,
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": 0,  # classification must be reproducible
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        blocks = body.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return Completion(text=text.strip(), model_version=self._text_model)
