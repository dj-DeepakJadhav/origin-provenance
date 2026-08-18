"""The Article 53 report must not become an overclaim.

Most of these tests pin *honesty properties* rather than behaviour, because the
realistic failure mode here is not a crash. It is someone later tidying the
report into something that reads like a clean bill of health -- dropping the
"cannot populate" section because it looks negative, or describing the
bitemporal fallback in the same language as the MVCC path.

Both of those would still pass a smoke test and both would make the artifact
worse than useless, because a provenance report that overstates its own standing
is exactly the thing it exists to prevent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from origin import article53, corpus, db, ledger

NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


def make_summary(**overrides) -> article53.Summary:
    payload = dict(
        corpus_name="scratch",
        corpus_id="00000000-0000-0000-0000-000000000000",
        declared_use="commercial",
        as_of=NOW,
        membership_source="mvcc",
        detail_from_snapshot=True,
        document_count=2,
        sources=(
            article53.SourceGroup(
                source_system="huggingface",
                document_count=2,
                license_classes={"PERMISSIVE": 1, "UNKNOWN": 1},
                raw_licenses={"mit": 1, "(none declared)": 1},
                earliest_admission=NOW - timedelta(hours=3),
                latest_admission=NOW - timedelta(hours=1),
            ),
        ),
        gates=article53.GateHistory(
            allowed=1,
            blocked=1,
            violations=3,
            clauses=("Licence states non-commercial use only.",),
            last_decision_at=NOW - timedelta(minutes=30),
        ),
        takedown_count=1,
        takedown_affected_answers=4,
        generated_at=NOW,
    )
    payload.update(overrides)
    return article53.Summary(**payload)


class TestScopeIsNeverDropped:
    """Art 53(1)(d) is about training data. This corpus is not training data."""

    def test_the_report_says_so_before_any_figure(self):
        rendered = article53.render_markdown(make_summary())
        scope = rendered.index("retrieval corpus")
        first_table = rendered.index("| Corpus described as at")
        assert scope < first_table, (
            "the scope caveat must appear above the first table, not in a "
            "footnote below figures a reader has already taken at face value"
        )

    def test_the_report_does_not_call_itself_a_disclosure(self):
        rendered = article53.render_markdown(make_summary())
        assert "not an Article 53 disclosure" in rendered

    def test_the_json_form_carries_the_same_caveat(self):
        payload = article53.to_dict(make_summary())
        assert payload["scope"]["corpus_kind"] == "retrieval"
        assert "not training data" in payload["scope"]["note"]


class TestTheGapsAreRendered:
    def test_every_unpopulated_field_reaches_the_report(self):
        rendered = article53.render_markdown(make_summary())
        for _, field_name, _ in article53.CANNOT_POPULATE:
            assert field_name in rendered, (
                f"{field_name!r} is declared unpopulated but never rendered; a "
                "report that hides its own gaps reads as complete coverage"
            )

    def test_the_crawl_boundary_is_named_explicitly(self):
        """The single most consequential gap: DSM Art 4(3) opt-outs."""
        rendered = article53.render_markdown(make_summary())
        assert "robots.txt" in rendered
        assert "TDM Reservation Protocol" in rendered

    def test_the_json_form_lists_the_gaps_too(self):
        payload = article53.to_dict(make_summary())
        assert len(payload["cannot_populate"]) == len(article53.CANNOT_POPULATE)

    def test_every_gap_is_attached_to_a_real_template_section(self):
        for section, field_name, _ in article53.CANNOT_POPULATE:
            assert section in article53.TEMPLATE_SECTIONS, (
                f"{field_name!r} claims to sit under {section!r}, which is not "
                "one of the template's sections"
            )


class TestEvidentiaryGradeIsNotBlurred:
    """MVCC and the bitemporal columns are different grades of evidence."""

    def test_mvcc_is_described_as_not_requiring_trust(self):
        rendered = article53.render_markdown(make_summary(membership_source="mvcc"))
        assert "does not depend on trusting ORIGIN" in rendered

    def test_bitemporal_is_marked_asserted_not_verifiable(self):
        rendered = article53.render_markdown(
            make_summary(membership_source="bitemporal", detail_from_snapshot=False)
        )
        assert "Asserted, not verifiable" in rendered
        assert "inconclusive is not a pass" in rendered

    def test_the_two_paths_do_not_read_the_same(self):
        mvcc = article53.render_markdown(make_summary(membership_source="mvcc"))
        bitemporal = article53.render_markdown(
            make_summary(membership_source="bitemporal", detail_from_snapshot=False)
        )
        assert mvcc != bitemporal

    def test_only_mvcc_is_reported_as_verifiable_in_json(self):
        assert article53.to_dict(make_summary(membership_source="mvcc"))[
            "evidentiary_basis"
        ]["verifiable"]
        for path in ("bitemporal", "current"):
            assert not article53.to_dict(make_summary(membership_source=path))[
                "evidentiary_basis"
            ]["verifiable"]

    def test_present_day_detail_is_flagged_when_the_snapshot_could_not_reach(self):
        rendered = article53.render_markdown(
            make_summary(membership_source="bitemporal", detail_from_snapshot=False)
        )
        assert "present-day rows" in rendered


class TestSilenceIsNotAPass:
    def test_no_gate_history_is_reported_as_not_evidence(self):
        rendered = article53.render_markdown(
            make_summary(gates=article53.GateHistory())
        )
        assert "not" in rendered and "evidence of compliance" in rendered

    def test_a_gated_corpus_does_not_get_that_warning(self):
        rendered = article53.render_markdown(make_summary())
        assert "evidence of compliance" not in rendered

    def test_declared_use_is_marked_unverified(self):
        rendered = article53.render_markdown(make_summary())
        assert "unverified input" in rendered
        assert article53.to_dict(make_summary())["corpus"][
            "declared_use_is_verified"
        ] is False

    def test_the_ledger_to_index_binding_is_disclaimed(self):
        rendered = article53.render_markdown(make_summary())
        assert "is the corpus the" in rendered.replace("\n", " ")


class TestGrouping:
    def test_documents_fold_by_source_system(self):
        rows = [
            {
                "source_system": "huggingface",
                "license_class": "PERMISSIVE",
                "license_raw": "mit",
                "admitted_at": NOW,
            },
            {
                "source_system": "huggingface",
                "license_class": "PERMISSIVE",
                "license_raw": "apache-2.0",
                "admitted_at": NOW - timedelta(hours=2),
            },
            {
                "source_system": "arxiv",
                "license_class": None,
                "license_raw": None,
                "admitted_at": NOW,
            },
        ]
        groups = {g.source_system: g for g in article53._group_documents(rows)}

        assert groups["huggingface"].document_count == 2
        assert groups["huggingface"].license_classes == {"PERMISSIVE": 2}
        assert groups["huggingface"].earliest_admission == NOW - timedelta(hours=2)
        assert groups["huggingface"].latest_admission == NOW

    def test_a_missing_licence_becomes_unknown_not_blank(self):
        """UNKNOWN blocks the build. Blank would read as 'nothing to see'."""
        groups = article53._group_documents(
            [
                {
                    "source_system": "arxiv",
                    "license_class": None,
                    "license_raw": None,
                    "admitted_at": NOW,
                }
            ]
        )
        assert groups[0].license_classes == {"UNKNOWN": 1}
        assert groups[0].raw_licenses == {"(none declared)": 1}

    def test_no_documents_yields_no_groups(self):
        assert article53._group_documents([]) == ()


class TestViolationParsing:
    def test_jsonb_arriving_as_text_is_still_read(self):
        parsed = article53._iter_violations('[{"clause": "no commercial use"}]')
        assert parsed == [{"clause": "no commercial use"}]

    def test_a_single_object_is_accepted(self):
        assert article53._iter_violations({"clause": "x"}) == [{"clause": "x"}]

    def test_unparseable_json_is_dropped_rather_than_raised(self):
        """A malformed clause must not take the whole report down with it."""
        assert article53._iter_violations("{not json") == []

    def test_null_is_empty(self):
        assert article53._iter_violations(None) == []


# --------------------------------------------------------------------------
# against a live cluster
# --------------------------------------------------------------------------
@pytest.fixture
def scratch():
    name = f"a53-{uuid.uuid4().hex[:12]}"
    corpus_id = corpus.create_corpus(name=name, declared_use="commercial")
    doc_id = f"test:a53-{uuid.uuid4().hex[:8]}"

    ledger.admit_document(
        corpus_id=corpus_id,
        doc_id=doc_id,
        source_uri="https://example.invalid/a53",
        source_system="test",
        content=b"article 53 fixture",
        title="fixture",
        license_raw="MIT",
        storage_key=f"test/{doc_id.replace(':', '_')}.txt",
    )
    yield corpus_id, doc_id, name

    with db.transaction() as cur:
        cur.execute("DELETE FROM corpus_members WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM build_gates WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM corpora WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))


@pytest.mark.needs_cluster
class TestAgainstTheLedger:
    def test_the_present_summary_finds_the_admitted_document(self, scratch):
        corpus_id, _, name = scratch
        summary = article53.build_summary(corpus_id)

        assert summary.corpus_name == name
        assert summary.document_count == 1
        assert summary.membership_source == "current"
        assert summary.sources[0].raw_licenses == {"MIT": 1}

    def test_the_verbatim_licence_survives_into_the_report(self, scratch):
        """The derived class is ORIGIN's reading. The raw string is the evidence."""
        corpus_id, _, _ = scratch
        rendered = article53.render_markdown(article53.build_summary(corpus_id))
        assert "MIT" in rendered

    def test_reading_within_the_gc_window_uses_storage_history(self, scratch):
        corpus_id, _, _ = scratch
        summary = article53.build_summary(corpus_id, "-30s")

        assert summary.membership_source == "mvcc"
        assert summary.detail_from_snapshot is True

    def test_the_instant_comes_from_the_cluster_not_the_client(self, scratch):
        """`as_of` on the MVCC path is the pinned transaction's own timestamp."""
        corpus_id, _, _ = scratch
        summary = article53.build_summary(corpus_id, "-30s")

        drift = abs((summary.generated_at - summary.as_of).total_seconds())
        assert 10 < drift < 120, (
            f"expected the report to be pinned ~30s in the past, saw {drift}s"
        )

    def test_an_instant_before_the_corpus_existed_reports_nothing(self, scratch):
        corpus_id, _, _ = scratch
        summary = article53.build_summary(
            corpus_id, datetime(2026, 1, 1, tzinfo=timezone.utc)
        )

        assert summary.document_count == 0
        assert summary.membership_source == "bitemporal"
        assert summary.detail_from_snapshot is False
