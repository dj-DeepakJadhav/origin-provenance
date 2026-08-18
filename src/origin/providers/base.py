"""The provider interface: embeddings and text generation.

Two implementations exist — ``local`` (offline, deterministic, no credentials)
and ``bedrock``. The interface is narrow on purpose: the moment a provider is
allowed to leak model-specific shapes into callers, swapping it stops being a
config change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    text: str
    model_version: str


class Provider(ABC):
    """Embeddings and text generation, as ORIGIN needs them."""

    #: Written into ``license_determinations.decided_by`` so every determination
    #: records which model made it. A determination without this is not evidence.
    name: str

    @property
    def supports_generation(self) -> bool:
        """Whether ``complete`` can produce free-form prose.

        The offline provider deliberately cannot: it serves licence
        classification and refuses everything else, because a fallback that
        invents plausible text is worse than one that says no. Callers that want
        a written answer must check this and produce an extractive result
        instead, labelled as such.
        """
        return False

    @property
    @abstractmethod
    def embed_dim(self) -> int:
        """Width of vectors from ``embed``. Must match the VECTOR(n) columns."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed one string. Must be deterministic for the same input."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed several strings. Order of results matches order of inputs."""

    @abstractmethod
    def complete(self, prompt: str, *, max_tokens: int = 1024) -> Completion:
        """Generate text. Returns the text and an identifiable model version."""
