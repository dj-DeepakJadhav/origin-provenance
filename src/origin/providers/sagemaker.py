"""Amazon SageMaker provider: serverless/real-time endpoint for reasoning and generation.

Provides drop-in integration with AWS SageMaker text-generation endpoints,
with fallback to local embeddings and extractive classification if the endpoint is not serving.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .base import Completion, Provider
from .local import LocalProvider

log = logging.getLogger(__name__)


class SageMakerProvider(Provider):
    def __init__(
        self,
        *,
        region: str,
        endpoint_name: str,
        embed_dim: int = 1024,
    ) -> None:
        import boto3

        self._client = boto3.client("sagemaker-runtime", region_name=region)
        self._region = region
        self._endpoint_name = endpoint_name
        self._dim = embed_dim
        self._fallback = LocalProvider(embed_dim=embed_dim)
        self.name = f"sagemaker:{endpoint_name}"

    @property
    def supports_generation(self) -> bool:
        return True

    @property
    def embed_dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        # Fast local hash-ngram embedding for memory vector operations
        return self._fallback.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._fallback.embed_batch(texts)

    def complete(self, prompt: str, *, max_tokens: int = 512) -> Completion:
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": 0.1,
                "return_full_text": False,
            },
        }
        try:
            response = self._client.invoke_endpoint(
                EndpointName=self._endpoint_name,
                ContentType="application/json",
                Body=json.dumps(payload),
            )
            result = json.loads(response["Body"].read().decode("utf-8"))
            if isinstance(result, list) and result and "generated_text" in result[0]:
                text = result[0]["generated_text"].strip()
            elif isinstance(result, dict) and "generated_text" in result:
                text = result["generated_text"].strip()
            else:
                text = str(result).strip()
            return Completion(text=text, model_version=self.name)
        except Exception as exc:
            log.warning("SageMaker endpoint %r invoke failed: %s; using extractive answer", self._endpoint_name, exc)
            return self._fallback.complete(prompt, max_tokens=max_tokens)
