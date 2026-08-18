"""Offline provider: deterministic, no credentials, no network.

This is not a stub that returns zeros. Licence strings are short and highly
repetitive ("CC-BY-4.0", "cc by 4.0", "Creative Commons Attribution 4.0"), and
hashed character n-grams capture that similarity well enough that the recall
path — match a new licence string against past determinations — genuinely works
offline. The demo is therefore honest without Bedrock; Bedrock improves the
classification of *novel* strings, not the mechanism.

Classification here is rule-based over the licence families that actually appear
in HuggingFace and arXiv metadata. It is deliberately conservative: anything it
does not recognise comes back UNKNOWN rather than being guessed, because a
wrong permissive answer is the one failure mode that matters.
"""

from __future__ import annotations

import hashlib
import math
import re

from .base import Completion, Provider

_NGRAM = 3


def _normalize(text: str) -> str:
    """Fold the cosmetic variation that makes licence strings look distinct."""
    lowered = text.lower().strip()
    # Punctuation carries no licence meaning; whitespace runs are noise.
    collapsed = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", collapsed).strip()


class LocalProvider(Provider):
    name = "local:hashed-ngram-v1"

    def __init__(self, embed_dim: int = 1024) -> None:
        if embed_dim <= 0:
            raise ValueError("embed_dim must be positive")
        self._dim = embed_dim

    @property
    def embed_dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        """Hashed character-trigram frequency vector, L2-normalised.

        Deterministic across processes and machines: the hash is BLAKE2b over
        the n-gram bytes, not Python's randomised ``hash``.
        """
        vector = [0.0] * self._dim
        normalized = _normalize(text)
        if not normalized:
            return vector

        # Pad so short strings still yield trigrams.
        padded = f"  {normalized}  "
        for i in range(len(padded) - _NGRAM + 1):
            gram = padded[i : i + _NGRAM]
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self._dim
            # Signed contribution so unrelated n-grams can cancel rather than
            # only ever accumulating, which would make everything look similar.
            sign = 1.0 if digest[0] & 1 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> Completion:
        """Rule-based licence classification.

        The only generation ORIGIN needs offline is licence classification, so
        that is what this does. Anything else raises rather than returning
        plausible nonsense — a fallback that silently invents text is worse than
        one that refuses.
        """
        if "LICENCE_CLASSIFY" not in prompt:
            raise NotImplementedError(
                "the local provider only serves licence classification. Set "
                "ORIGIN_PROVIDER=bedrock for general generation."
            )

        raw = prompt.split("LICENCE_CLASSIFY:", 1)[1].strip()
        verdict, rationale = classify_license_text(raw)
        return Completion(
            text=f'{{"class": "{verdict}", "rationale": "{rationale}"}}',
            model_version=self.name,
        )


# Ordered most-specific first: "cc-by-nc-sa" must not match the "cc-by" rule.
_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"\bnc\b|non ?commercial"),
        "NONCOMMERCIAL",
        "explicit non-commercial restriction",
    ),
    (
        re.compile(r"\bnd\b|no ?deriv"),
        "NODERIVATIVES",
        "no-derivatives restriction; corpus inclusion is a derivative use",
    ),
    (
        # GFDL and ODbL are share-alike in effect. ODbL matters disproportionately
        # here: Open Data Commons licences are specific to open *data*, which is
        # exactly the material an AI corpus ingests.
        re.compile(
            r"\bgpl\b|\bagpl\b|copyleft|\bgfdl\b|\bodbl\b|open database licen[cs]e"
        ),
        "COPYLEFT",
        "copyleft or share-alike licence; downstream obligations attach",
    ),
    (
        re.compile(
            r"\bcc0\b|creative commons zero|public domain|\bunlicense\b|\bpddl\b"
        ),
        "PUBLIC_DOMAIN",
        "dedicated to the public domain",
    ),
    (
        re.compile(r"\bmit\b|\bbsd\b|\bapache\b|\bisc\b"),
        "PERMISSIVE",
        "permissive open-source licence",
    ),
    (
        re.compile(r"cc ?by ?sa|share ?alike"),
        "COPYLEFT",
        "share-alike; downstream obligations attach",
    ),
    (
        # Both the SPDX-style identifier and the spelled-out name, because
        # HuggingFace metadata carries either. Bare "creative commons" is
        # deliberately NOT matched — the family spans everything from CC0 to
        # CC-BY-NC-ND, so on its own it determines nothing.
        #
        # odc-by (Open Data Commons Attribution) is included because it is the
        # 4th most common licence among the 100 most-downloaded HuggingFace
        # datasets — omitting it sent 8% of a real sample to UNKNOWN.
        re.compile(
            r"cc ?by|creative commons attribution"
            r"|odc ?by|open data commons attribution"
        ),
        "ATTRIBUTION",
        "attribution required, otherwise unrestricted",
    ),
    (
        re.compile(r"proprietary|all rights reserved|\bcopyright\b"),
        "PROPRIETARY",
        "rights reserved; no grant of use identified",
    ),
]


def classify_license_text(raw: str) -> tuple[str, str]:
    """Classify a raw licence string into a permitted-use class.

    Returns ``(class, rationale)``. Unrecognised input returns UNKNOWN, which
    the policy layer treats as restrictive — see licensing/policy.py. Guessing
    permissively here is the single most dangerous thing this function could do.
    """
    normalized = _normalize(raw)
    if not normalized:
        return "UNKNOWN", "no licence text present"

    # "see LICENSE file" is extremely common and is not a licence.
    if re.search(r"see (the )?licen[cs]e|refer to licen[cs]e", normalized):
        return "UNKNOWN", "defers to an external file; not resolvable from metadata"

    for pattern, verdict, rationale in _RULES:
        if pattern.search(normalized):
            return verdict, rationale

    return "UNKNOWN", "no recognised licence family in the string"
