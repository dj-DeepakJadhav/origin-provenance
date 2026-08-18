"""The permitted-use matrix: may this licence class enter this corpus?

This module is the "policy" in EU AI Act **Article 53(1)(c)** — the obligation on
GPAI providers to put in place a policy to comply with Union copyright law and to
identify and comply with rights reservations under Article 4(3) of the DSM
Directive (EU) 2019/790. A policy that cannot refuse anything is not a policy,
which is why this returns outcomes the build gate acts on rather than advice.
See docs/COMPLIANCE.md for the full mapping and, more importantly, its limits.

NOT LEGAL ADVICE. This encodes a deliberately conservative reading of common
licence families so that a machine can enforce *something* consistently, and so
that every decision is explainable and reviewable. Real deployment requires
counsel to own this matrix. The README says so too; it is not a detail to bury.

Two design decisions worth defending:

**UNKNOWN fails closed.** An unrecognised licence blocks the build. This is the
single most important line in the file. The tempting alternative — let it
through and log a warning — is precisely how unlicensed material ends up in a
shipped product, because warnings are not read.

**Some outcomes are REVIEW, not ALLOW or BLOCK.** Copyleft in a commercial
corpus is genuinely arguable, and a system that pretends otherwise is lying in
one direction or the other. REVIEW stops the build and names a human. Honest
uncertainty, surfaced, beats confident wrongness.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Permitted-use classes produced by the classifier. Keep in sync with
# providers/local.py::classify_license_text.
LICENSE_CLASSES = (
    "PUBLIC_DOMAIN",
    "PERMISSIVE",
    "ATTRIBUTION",
    "COPYLEFT",
    "NONCOMMERCIAL",
    "NODERIVATIVES",
    "PROPRIETARY",
    "UNKNOWN",
)

DECLARED_USES = ("commercial", "internal", "research")


class Outcome(str, Enum):
    ALLOW = "allow"
    #: Permitted, but a duty attaches (e.g. attribution). Build proceeds; the
    #: obligation is recorded so it can be discharged rather than forgotten.
    OBLIGATION = "obligation"
    #: Genuinely arguable. Build stops pending a human decision.
    REVIEW = "review"
    BLOCK = "block"

    @property
    def blocks_build(self) -> bool:
        return self in (Outcome.REVIEW, Outcome.BLOCK)


@dataclass(frozen=True)
class Ruling:
    outcome: Outcome
    #: The reason, phrased to be quoted verbatim on screen. This is what a
    #: reviewer reads and what the demo shows — so it is written for a human,
    #: not for a log parser.
    clause: str

    @property
    def blocks_build(self) -> bool:
        return self.outcome.blocks_build


_A = Outcome.ALLOW
_O = Outcome.OBLIGATION
_R = Outcome.REVIEW
_B = Outcome.BLOCK

# (license_class, declared_use) -> (outcome, clause)
_MATRIX: dict[tuple[str, str], tuple[Outcome, str]] = {
    # Public domain — no restriction anywhere.
    ("PUBLIC_DOMAIN", "commercial"): (_A, "Public domain: no restriction on use."),
    ("PUBLIC_DOMAIN", "internal"): (_A, "Public domain: no restriction on use."),
    ("PUBLIC_DOMAIN", "research"): (_A, "Public domain: no restriction on use."),
    # Permissive OSS — fine everywhere, notice obligations are mild but real.
    ("PERMISSIVE", "commercial"): (
        _O,
        "Permissive licence: commercial use granted; licence notice must be retained.",
    ),
    ("PERMISSIVE", "internal"): (_A, "Permissive licence: internal use granted."),
    ("PERMISSIVE", "research"): (_A, "Permissive licence: research use granted."),
    # Attribution required.
    ("ATTRIBUTION", "commercial"): (
        _O,
        "Attribution required: use granted only if the source is credited in "
        "outputs or documentation.",
    ),
    ("ATTRIBUTION", "internal"): (_O, "Attribution required: credit the source."),
    ("ATTRIBUTION", "research"): (_O, "Attribution required: credit the source."),
    # Copyleft — the genuinely arguable one for commercial corpora.
    ("COPYLEFT", "commercial"): (
        _R,
        "Copyleft licence in a commercial corpus: share-alike obligations may "
        "attach to derived outputs. Requires legal review, not an automated "
        "decision.",
    ),
    ("COPYLEFT", "internal"): (
        _O,
        "Copyleft licence: internal use permitted; obligations attach on "
        "distribution.",
    ),
    ("COPYLEFT", "research"): (_O, "Copyleft licence: research use permitted."),
    # Non-commercial — the headline block, and the demo's blocking case.
    ("NONCOMMERCIAL", "commercial"): (
        _B,
        "Licence states non-commercial use only. This corpus is declared "
        "commercial. Inclusion is not permitted.",
    ),
    ("NONCOMMERCIAL", "internal"): (
        _R,
        "Licence states non-commercial use only. Internal use at a commercial "
        "entity is frequently held to be commercial use. Requires review.",
    ),
    ("NONCOMMERCIAL", "research"): (
        _A,
        "Licence permits non-commercial use; corpus is declared research.",
    ),
    # No-derivatives — corpus inclusion is itself a derivative use.
    ("NODERIVATIVES", "commercial"): (
        _B,
        "No-derivatives licence: incorporating the work into a corpus and "
        "generating from it is a derivative use. Not permitted.",
    ),
    ("NODERIVATIVES", "internal"): (
        _B,
        "No-derivatives licence: corpus inclusion is a derivative use. Not "
        "permitted.",
    ),
    ("NODERIVATIVES", "research"): (
        _R,
        "No-derivatives licence: research exceptions vary by jurisdiction. "
        "Requires review.",
    ),
    # Proprietary — needs a separate negotiated agreement, which is not metadata.
    ("PROPRIETARY", "commercial"): (
        _B,
        "Rights reserved and no grant of use identified. A separate written "
        "agreement is required and none is recorded.",
    ),
    ("PROPRIETARY", "internal"): (
        _B,
        "Rights reserved and no grant of use identified. Not permitted without "
        "a recorded agreement.",
    ),
    ("PROPRIETARY", "research"): (
        _B,
        "Rights reserved and no grant of use identified. Not permitted without "
        "a recorded agreement.",
    ),
}

_UNKNOWN_CLAUSE = (
    "Licence could not be determined from the available metadata. Unknown "
    "licences are treated as restrictive: a document is not usable until its "
    "terms are known."
)


def evaluate(license_class: str, declared_use: str) -> Ruling:
    """Rule on one document's licence class against a corpus's declared use.

    Unknown classes and unknown uses both fail closed. An unrecognised input is
    a bug or a new licence family, and neither is a reason to permit use.
    """
    normalized_use = (declared_use or "").strip().lower()
    normalized_class = (license_class or "UNKNOWN").strip().upper()

    if normalized_use not in DECLARED_USES:
        return Ruling(
            Outcome.BLOCK,
            f"Corpus declares an unrecognised use {declared_use!r}. Permitted "
            f"values are {', '.join(DECLARED_USES)}.",
        )

    if normalized_class == "UNKNOWN":
        return Ruling(Outcome.BLOCK, _UNKNOWN_CLAUSE)

    ruling = _MATRIX.get((normalized_class, normalized_use))
    if ruling is None:
        # A class exists in the classifier but not in the matrix. Fail closed and
        # make the gap loud, rather than defaulting to permissive.
        return Ruling(
            Outcome.BLOCK,
            f"No policy defined for licence class {normalized_class!r} in a "
            f"{normalized_use!r} corpus. Treated as restrictive until the "
            "matrix is extended.",
        )

    outcome, clause = ruling
    return Ruling(outcome, clause)
