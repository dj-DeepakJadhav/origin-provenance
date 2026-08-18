"""HuggingFace parsing — pure functions, no network.

Every fixture below reflects a shape the Hub actually returns. The licence
extraction cases are the important ones: a parser that quietly picks one licence
when two are declared, or reports "none" because the request omitted cardData,
would make ORIGIN look like it was working when it was not.
"""

from __future__ import annotations

import pytest

from origin.ingest.huggingface import (
    extract_license,
    license_distribution,
    license_from_tags,
    parse_all,
    parse_dataset,
)


class TestLicenseFromTags:
    def test_extracts_the_license_tag(self):
        tags = ["task_categories:qa", "license:mit", "size_categories:10K<n<100K"]
        assert license_from_tags(tags) == "mit"

    def test_joins_multiple_license_tags(self):
        assert license_from_tags(["license:mit", "license:apache-2.0"]) == (
            "mit, apache-2.0"
        )

    def test_returns_none_when_absent(self):
        assert license_from_tags(["task_categories:qa"]) is None

    @pytest.mark.parametrize("bad", [None, "not-a-list", 42, {}])
    def test_tolerates_wrong_types(self, bad):
        assert license_from_tags(bad) is None

    def test_ignores_empty_license_tag(self):
        assert license_from_tags(["license:"]) is None


class TestExtractLicense:
    def test_prefers_card_data_over_tags(self):
        raw = {"cardData": {"license": "apache-2.0"}, "tags": ["license:mit"]}
        license_raw, conflict = extract_license(raw)
        assert license_raw == "apache-2.0"
        assert conflict is True, "disagreement must be reported, not resolved"

    def test_no_conflict_when_they_agree(self):
        raw = {"cardData": {"license": "mit"}, "tags": ["license:mit"]}
        assert extract_license(raw) == ("mit", False)

    def test_case_difference_is_not_a_conflict(self):
        raw = {"cardData": {"license": "MIT"}, "tags": ["license:mit"]}
        license_raw, conflict = extract_license(raw)
        assert license_raw == "MIT"
        assert conflict is False

    def test_punctuation_difference_is_not_a_conflict(self):
        raw = {"cardData": {"license": "apache-2.0"}, "tags": ["license:apache2.0"]}
        assert extract_license(raw)[1] is False

    def test_falls_back_to_tags(self):
        raw = {"cardData": {}, "tags": ["license:cc-by-nc-4.0"]}
        assert extract_license(raw) == ("cc-by-nc-4.0", False)

    def test_license_as_a_list_is_preserved_not_narrowed(self):
        """Picking one of two declared licences would be a silent legal call."""
        raw = {"cardData": {"license": ["mit", "apache-2.0"]}}
        assert extract_license(raw)[0] == "mit, apache-2.0"

    def test_missing_everywhere_returns_none(self):
        assert extract_license({}) == (None, False)

    def test_tolerates_card_data_that_is_not_a_dict(self):
        """The Hub occasionally returns a string or null here."""
        assert extract_license({"cardData": "junk"}) == (None, False)
        assert extract_license({"cardData": None}) == (None, False)

    def test_empty_string_license_is_none_not_empty(self):
        assert extract_license({"cardData": {"license": "   "}})[0] is None


class TestParseDataset:
    def test_parses_a_realistic_item(self):
        raw = {
            "id": "squad",
            "cardData": {"license": "cc-by-sa-4.0"},
            "tags": ["task_categories:question-answering", "license:cc-by-sa-4.0"],
            "description": "Stanford Question Answering Dataset",
            "downloads": 123456,
        }
        record = parse_dataset(raw)
        assert record is not None
        assert record.doc_id == "hf:squad"
        assert record.source_uri == "https://huggingface.co/datasets/squad"
        assert record.title == "squad"
        assert record.license_raw == "cc-by-sa-4.0"
        assert record.downloads == 123456
        assert record.license_conflict is False
        assert "squad" in record.content
        assert "Stanford Question Answering" in record.content

    def test_content_includes_tags_for_retrieval(self):
        raw = {"id": "x", "tags": ["language:en"], "description": "d"}
        assert "language:en" in parse_dataset(raw).content

    def test_survives_missing_description(self):
        record = parse_dataset({"id": "bare-dataset"})
        assert record is not None
        assert record.content.strip() == "# bare-dataset"
        assert record.license_raw is None

    def test_returns_none_for_item_with_no_id(self):
        """One malformed item must not abort a run of several hundred."""
        assert parse_dataset({"description": "orphan"}) is None

    def test_returns_none_for_non_string_id(self):
        assert parse_dataset({"id": 12345}) is None

    def test_non_integer_downloads_becomes_zero(self):
        assert parse_dataset({"id": "x", "downloads": "many"}).downloads == 0

    def test_non_string_description_is_coerced(self):
        record = parse_dataset({"id": "x", "description": {"nested": "object"}})
        assert record is not None
        assert isinstance(record.content, str)


class TestParseAll:
    def test_drops_unusable_items_and_keeps_the_rest(self):
        payload = [
            {"id": "good-one", "description": "a"},
            {"description": "no id"},
            {"id": "good-two"},
            {"id": 999},
        ]
        records = parse_all(payload)
        assert [r.doc_id for r in records] == ["hf:good-one", "hf:good-two"]

    def test_empty_payload(self):
        assert parse_all([]) == []


class TestLicenseDistribution:
    def test_counts_and_orders_by_frequency(self):
        payload = [
            {"id": "a", "cardData": {"license": "mit"}},
            {"id": "b", "cardData": {"license": "mit"}},
            {"id": "c", "cardData": {"license": "apache-2.0"}},
            {"id": "d"},
        ]
        dist = license_distribution(parse_all(payload))
        assert list(dist.items())[0] == ("mit", 2)
        assert dist["apache-2.0"] == 1
        assert dist["(none declared)"] == 1
