"""Licence classification and the permitted-use policy.

The behaviour under test that actually matters is failing closed. A permissive
mistake here is the failure mode ORIGIN exists to prevent, so the negative cases
get more attention than the positive ones.
"""

from __future__ import annotations

import pytest

from origin.licensing import policy
from origin.providers.local import classify_license_text


class TestClassification:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("MIT", "PERMISSIVE"),
            ("Apache-2.0", "PERMISSIVE"),
            ("BSD 3-Clause", "PERMISSIVE"),
            ("CC0-1.0", "PUBLIC_DOMAIN"),
            ("Public Domain", "PUBLIC_DOMAIN"),
            ("CC-BY-4.0", "ATTRIBUTION"),
            ("cc by 4.0", "ATTRIBUTION"),
            ("Creative Commons Attribution 4.0", "ATTRIBUTION"),
            ("CC-BY-SA-4.0", "COPYLEFT"),
            ("GPL-3.0", "COPYLEFT"),
            ("AGPL-3.0", "COPYLEFT"),
            ("CC-BY-NC-4.0", "NONCOMMERCIAL"),
            ("non-commercial use only", "NONCOMMERCIAL"),
            ("CC-BY-ND-4.0", "NODERIVATIVES"),
            ("All rights reserved", "PROPRIETARY"),
            # Spelled-out forms, as they actually appear in HuggingFace metadata.
            ("Creative Commons Attribution Share Alike 4.0", "COPYLEFT"),
            ("Creative Commons Attribution-NonCommercial 4.0", "NONCOMMERCIAL"),
            ("Creative Commons Zero v1.0 Universal", "PUBLIC_DOMAIN"),
            # Open Data Commons family. Observed live in the 100 most-downloaded
            # HuggingFace datasets: odc-by was the 4th most common licence and
            # was originally being sent to UNKNOWN.
            ("odc-by", "ATTRIBUTION"),
            ("odc-by-1.0", "ATTRIBUTION"),
            ("Open Data Commons Attribution License", "ATTRIBUTION"),
            ("odc-odbl", "COPYLEFT"),
            ("ODbL-1.0", "COPYLEFT"),
            ("odc-pddl", "PUBLIC_DOMAIN"),
            # GNU Free Documentation License, seen dual-licensed with CC-BY-SA.
            ("gfdl", "COPYLEFT"),
        ],
    )
    def test_recognises_real_licence_families(self, raw, expected):
        verdict, rationale = classify_license_text(raw)
        assert verdict == expected
        assert rationale, "every determination must carry a rationale"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "see LICENSE file",
            "refer to license",
            "wibble",
            # "Creative Commons" alone spans CC0 through CC-BY-NC-ND, so it
            # determines nothing and must not be read as permissive.
            "Creative Commons",
        ],
    )
    def test_unrecognised_input_is_unknown_not_guessed(self, raw):
        verdict, _ = classify_license_text(raw)
        assert verdict == "UNKNOWN"

    def test_cosmetic_variation_does_not_change_the_verdict(self):
        """The whole point of normalisation: these are the same licence."""
        variants = ["CC-BY-4.0", "cc by 4.0", "CC BY 4.0", "  cc-by-4.0  "]
        verdicts = {classify_license_text(v)[0] for v in variants}
        assert verdicts == {"ATTRIBUTION"}

    def test_more_specific_family_wins(self):
        """CC-BY-NC must not be classified as plain attribution."""
        assert classify_license_text("CC-BY-NC-SA-4.0")[0] == "NONCOMMERCIAL"
        assert classify_license_text("CC-BY-ND-4.0")[0] == "NODERIVATIVES"

    def test_dual_licence_resolves_to_the_more_restrictive(self):
        """Observed live on the Hub: 'cc-by-sa-3.0, gfdl'. Both are share-alike,
        and the answer must not be the permissive read of either half."""
        assert classify_license_text("cc-by-sa-3.0, gfdl")[0] == "COPYLEFT"

    @pytest.mark.parametrize("raw", ["other", "unknown", "Other", "UNKNOWN"])
    def test_meaningless_declarations_are_unknown(self, raw):
        """'other' and 'unknown' are literal values on the Hub. They look like
        declarations and determine nothing."""
        assert classify_license_text(raw)[0] == "UNKNOWN"


class TestPolicy:
    def test_noncommercial_in_commercial_corpus_is_blocked(self):
        """The demo's blocking case. If this ever passes, the demo is a lie."""
        ruling = policy.evaluate("NONCOMMERCIAL", "commercial")
        assert ruling.outcome is policy.Outcome.BLOCK
        assert ruling.blocks_build
        assert "non-commercial" in ruling.clause.lower()

    def test_unknown_licence_fails_closed(self):
        ruling = policy.evaluate("UNKNOWN", "commercial")
        assert ruling.outcome is policy.Outcome.BLOCK
        assert ruling.blocks_build

    def test_unknown_licence_fails_closed_even_for_research(self):
        """Permissiveness must not leak in via the least-restrictive use."""
        for use in policy.DECLARED_USES:
            assert policy.evaluate("UNKNOWN", use).blocks_build

    def test_unrecognised_declared_use_fails_closed(self):
        ruling = policy.evaluate("PERMISSIVE", "whatever")
        assert ruling.outcome is policy.Outcome.BLOCK

    def test_class_missing_from_matrix_fails_closed(self):
        ruling = policy.evaluate("SOME_NEW_FAMILY", "commercial")
        assert ruling.outcome is policy.Outcome.BLOCK
        assert "no policy defined" in ruling.clause.lower()

    def test_permissive_is_allowed_everywhere(self):
        for use in policy.DECLARED_USES:
            assert not policy.evaluate("PERMISSIVE", use).blocks_build

    def test_copyleft_commercial_is_review_not_a_silent_allow(self):
        """Genuine legal ambiguity must stop the build, not be papered over."""
        ruling = policy.evaluate("COPYLEFT", "commercial")
        assert ruling.outcome is policy.Outcome.REVIEW
        assert ruling.blocks_build

    def test_obligations_do_not_block(self):
        ruling = policy.evaluate("ATTRIBUTION", "commercial")
        assert ruling.outcome is policy.Outcome.OBLIGATION
        assert not ruling.blocks_build

    def test_every_class_and_use_pair_has_a_defined_outcome(self):
        """No silent gaps: the matrix must cover the classifier's whole range."""
        for licence in policy.LICENSE_CLASSES:
            for use in policy.DECLARED_USES:
                ruling = policy.evaluate(licence, use)
                assert isinstance(ruling.outcome, policy.Outcome)
                assert ruling.clause.strip(), (
                    f"{licence}/{use} produced an empty clause; the clause is "
                    "what a reviewer reads"
                )

    def test_case_and_whitespace_are_tolerated(self):
        assert (
            policy.evaluate("  noncommercial ", " COMMERCIAL ").outcome
            is policy.Outcome.BLOCK
        )
