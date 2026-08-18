"""The local provider.

It has to be genuinely useful, not a stub — the offline demo depends on licence
strings that differ cosmetically actually landing near each other in vector
space. These tests assert that property rather than merely asserting shape.
"""

from __future__ import annotations

import math

import pytest

from origin.providers.local import LocalProvider

DIM = 1024


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@pytest.fixture
def provider() -> LocalProvider:
    return LocalProvider(embed_dim=DIM)


class TestEmbedding:
    def test_dimension_matches_configuration(self, provider):
        assert len(provider.embed("MIT")) == DIM
        assert provider.embed_dim == DIM

    def test_is_deterministic(self, provider):
        """Must not depend on PYTHONHASHSEED — determinations are compared
        across processes and across runs."""
        assert provider.embed("Apache-2.0") == provider.embed("Apache-2.0")

    def test_is_l2_normalised(self, provider):
        norm = math.sqrt(sum(v * v for v in provider.embed("CC-BY-4.0")))
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_empty_input_returns_zero_vector(self, provider):
        assert provider.embed("") == [0.0] * DIM

    def test_cosmetic_variants_are_close(self, provider):
        """The property the offline recall path depends on."""
        base = provider.embed("CC-BY-4.0")
        for variant in ["cc by 4.0", "CC BY 4.0", "cc-by-4.0"]:
            similarity = cosine(base, provider.embed(variant))
            assert similarity > 0.85, f"{variant!r} scored only {similarity:.3f}"

    def test_different_licences_are_farther_apart_than_variants(self, provider):
        """Relative ordering is what the recall path actually uses."""
        base = provider.embed("CC-BY-4.0")
        variant = cosine(base, provider.embed("cc by 4.0"))
        different = cosine(base, provider.embed("GPL-3.0 only, copyleft"))
        assert variant > different, (
            f"a cosmetic variant ({variant:.3f}) must be nearer than an "
            f"unrelated licence ({different:.3f})"
        )

    def test_batch_preserves_order(self, provider):
        texts = ["MIT", "GPL-3.0", "CC0-1.0"]
        batch = provider.embed_batch(texts)
        assert batch == [provider.embed(t) for t in texts]

    def test_rejects_nonsense_dimension(self):
        with pytest.raises(ValueError):
            LocalProvider(embed_dim=0)


class TestCompletion:
    def test_classifies_via_the_prompt_protocol(self, provider):
        completion = provider.complete("LICENCE_CLASSIFY: CC-BY-NC-4.0")
        assert "NONCOMMERCIAL" in completion.text
        assert completion.model_version == provider.name

    def test_refuses_general_generation(self, provider):
        """A fallback that invents prose is worse than one that refuses."""
        with pytest.raises(NotImplementedError):
            provider.complete("Write me a poem about lineage graphs")
