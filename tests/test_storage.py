"""Filesystem document store.

The path-traversal cases are the ones that matter: document keys are derived
from external source identifiers (arXiv ids, HuggingFace dataset names), so they
are untrusted input that becomes a filesystem path.
"""

from __future__ import annotations

import pytest

from origin.storage.local_fs import LocalDocumentStore


@pytest.fixture
def store(tmp_path) -> LocalDocumentStore:
    return LocalDocumentStore(tmp_path / "docs")


class TestRoundTrip:
    def test_put_then_get(self, store):
        store.put("arxiv/2401.00001.txt", b"hello")
        assert store.get("arxiv/2401.00001.txt") == b"hello"

    def test_put_is_idempotent(self, store):
        """Ingestion is re-run constantly and must not be punished for it."""
        first = store.put("a/b.txt", b"payload")
        second = store.put("a/b.txt", b"payload")
        assert first == second
        assert store.get("a/b.txt") == b"payload"

    def test_put_overwrites_with_new_content(self, store):
        store.put("a/b.txt", b"old")
        store.put("a/b.txt", b"new")
        assert store.get("a/b.txt") == b"new"

    def test_exists(self, store):
        assert not store.exists("nope.txt")
        store.put("nope.txt", b"x")
        assert store.exists("nope.txt")

    def test_missing_key_raises_keyerror(self, store):
        with pytest.raises(KeyError):
            store.get("absent.txt")

    def test_no_partial_files_left_behind(self, store):
        """Write-then-rename: a truncated document would hash differently than
        the ledger recorded, which would read as tampering."""
        store.put("a/b.txt", b"payload")
        leftovers = list(store._root.rglob("*.partial"))
        assert leftovers == []

    def test_creates_nested_directories(self, store):
        store.put("deep/nested/path/doc.txt", b"x")
        assert store.get("deep/nested/path/doc.txt") == b"x"


class TestKeyValidation:
    @pytest.mark.parametrize(
        "hostile",
        [
            "../escape.txt",
            "a/../../escape.txt",
            "/absolute/path.txt",
            "",
            "   ",
            "a\\b.txt",  # backslash is a separator on Windows
            "a/b<c>.txt",
            "a|b.txt",
            "-leading-dash.txt",
            "/",
        ],
    )
    def test_rejects_unsafe_keys(self, store, hostile):
        """Reject rather than sanitise. A key that could escape the root is a
        caller bug, and rewriting it silently would hide that."""
        with pytest.raises(ValueError):
            store.put(hostile, b"x")

    def test_accepts_realistic_source_identifiers(self, store):
        for key in [
            "arxiv/2401.00001v2.txt",
            "huggingface/squad/train-00000.json",
            "arxiv/cs.LG/2401.00001.txt",
        ]:
            store.put(key, b"x")
            assert store.exists(key)


class TestUri:
    def test_uri_is_stable_and_absolute(self, store):
        uri = store.uri("a/b.txt")
        assert uri.startswith("file:///")
        assert uri == store.put("a/b.txt", b"x")

    def test_uri_available_before_the_document_exists(self, store):
        assert store.uri("not/yet.txt").startswith("file:///")
