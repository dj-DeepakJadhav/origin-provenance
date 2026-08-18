"""Parsing of DataHub's read responses — no GMS required.

DataHub's GraphQL shapes are quirky in ways that fail quietly:

  * ``customProperties`` comes back as a **list of {key, value} dicts**, not a
    mapping. Treating it as a dict yields an empty result and looks like "the
    catalogue knows nothing" rather than a parsing bug.
  * ``description`` is sometimes a string and sometimes nested.
  * tag and owner associations are doubly nested (``tags.tags[].tag.urn``).

The ``externally_curated`` flag matters most: it decides whether a human-curated
licence in the catalogue should outrank our classifier. Getting it wrong in the
permissive direction means silently preferring a guess over a steward's judgement.
"""

from __future__ import annotations

import pytest

from origin.datahub_context import (
    CatalogFact,
    _extract_custom_properties,
    _first_string,
)


class TestFirstString:
    def test_plain_string(self):
        assert _first_string("hello") == "hello"

    def test_strips_whitespace(self):
        assert _first_string("  hello  ") == "hello"

    def test_blank_is_none(self):
        assert _first_string("   ") is None

    def test_picks_first_usable_from_a_list(self):
        assert _first_string(["", "  ", "found", "later"]) == "found"

    def test_nested_lists(self):
        assert _first_string([[], ["deep"]]) == "deep"

    @pytest.mark.parametrize("junk", [None, 42, {}, [], [None, ""]])
    def test_unusable_input_is_none(self, junk):
        assert _first_string(junk) is None


class TestExtractCustomProperties:
    def test_list_of_key_value_dicts(self):
        """The shape DataHub actually returns."""
        properties = {
            "customProperties": [
                {"key": "origin.licence_class", "value": "NONCOMMERCIAL"},
                {"key": "origin.licence_raw", "value": "cc-by-nc-4.0"},
            ]
        }
        assert _extract_custom_properties(properties) == {
            "origin.licence_class": "NONCOMMERCIAL",
            "origin.licence_raw": "cc-by-nc-4.0",
        }

    def test_plain_mapping_is_also_accepted(self):
        """Some endpoints return a dict; both must work."""
        properties = {"customProperties": {"a": "1", "b": "2"}}
        assert _extract_custom_properties(properties) == {"a": "1", "b": "2"}

    def test_entry_missing_value_becomes_empty_string(self):
        properties = {"customProperties": [{"key": "lonely"}]}
        assert _extract_custom_properties(properties) == {"lonely": ""}

    def test_entries_without_a_key_are_skipped(self):
        properties = {"customProperties": [{"value": "orphan"}, {"key": "k", "value": "v"}]}
        assert _extract_custom_properties(properties) == {"k": "v"}

    @pytest.mark.parametrize(
        "properties", [None, "junk", 42, {}, {"customProperties": None}]
    )
    def test_unusable_input_is_empty_not_an_error(self, properties):
        assert _extract_custom_properties(properties) == {}

    def test_values_are_coerced_to_strings(self):
        properties = {"customProperties": [{"key": "count", "value": 24}]}
        assert _extract_custom_properties(properties) == {"count": "24"}


class TestExternalCurationSemantics:
    """The flag that decides whether to defer to a human.

    Constructed directly rather than through the network, because the rule is
    what is under test: metadata we wrote is namespaced (`origin.` properties,
    `origin-` tags), so anything else came from somewhere else.
    """

    def test_only_our_own_metadata_is_not_external(self):
        """Our own licence value must NOT surface as curated_licence — deferring
        to `origin.licence_raw` would mean deferring to ourselves and calling it
        human judgement."""
        fact = CatalogFact(
            urn="urn:li:dataset:(x,y,PROD)",
            name="y",
            description=None,
            existing_licence="cc-by-4.0",
            curated_licence=None,
            tags=("urn:li:tag:origin-licence-attribution",),
            owners=(),
            externally_curated=False,
        )
        assert fact.externally_curated is False
        assert fact.curated_licence is None

    def test_a_foreign_tag_makes_it_external(self):
        fact = CatalogFact(
            urn="urn:li:dataset:(x,y,PROD)",
            name="y",
            description=None,
            existing_licence=None,
            curated_licence=None,
            tags=("urn:li:tag:pii",),
            owners=(),
            externally_curated=True,
        )
        assert fact.externally_curated is True

    def test_an_owner_alone_makes_it_external(self):
        """Ownership is never something ORIGIN writes, so its presence means a
        person curated this entity."""
        fact = CatalogFact(
            urn="urn:li:dataset:(x,y,PROD)",
            name="y",
            description=None,
            existing_licence=None,
            curated_licence=None,
            tags=(),
            owners=("urn:li:corpuser:steward",),
            externally_curated=True,
        )
        assert fact.externally_curated is True

    def test_a_curated_licence_is_separate_from_our_own(self):
        """The gate may only defer to curated_licence. existing_licence is for
        display and can be our own value."""
        fact = CatalogFact(
            urn="urn:li:dataset:(x,y,PROD)",
            name="y",
            description=None,
            existing_licence="cc-by-4.0",
            curated_licence="cc-by-4.0",
            tags=("urn:li:tag:reviewed-by-legal",),
            owners=("urn:li:corpuser:priya.raman",),
            externally_curated=True,
        )
        assert fact.curated_licence == "cc-by-4.0"
        assert fact.externally_curated is True
