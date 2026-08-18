"""The HTTP surface — the part a judge actually clicks.

This file exists because its absence had a cost. The dashboard shipped with
``/ask`` and ``/takedown`` returning hardcoded answers, invented user emails and
a fabricated blast radius, and nothing failed, because nothing tested it. The
engine underneath was real the whole time; only the wrapper was theatre.

So the first test here is a regression guard against exactly that: it reads the
source and fails if the fabricated fixtures ever come back.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

APP_SOURCE = pathlib.Path(__file__).parent.parent / "src" / "origin" / "api" / "app.py"


def _client(monkeypatch, token: str | None = None):
    """A client over a freshly reloaded app, so module-level config is re-read."""
    monkeypatch.setenv("ORIGIN_WRITE_TOKEN", token or "")
    import origin.api.app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


class TestNoFabricatedData:
    """The answers must come from the cluster, not from string literals."""

    def test_invented_users_and_answer_ids_are_gone(self):
        source = APP_SOURCE.read_text(encoding="utf-8")
        for fabricated in [
            "dr.smith@hospital.org",
            "research.team@pharma.com",
            "ans_901248",
            "ans_901592",
            "42% response rate",
        ]:
            assert fabricated not in source, (
                f"{fabricated!r} is back in the API. These were invented values "
                "presented to users as provenance records."
            )

    def test_the_engine_is_actually_imported(self):
        source = APP_SOURCE.read_text(encoding="utf-8")
        assert "retrieval.ask(" in source, "/ask must run a real retrieval"
        assert "corpus_mod.record_takedown(" in source, "takedown must be real"
        assert "corpus_mod.takedown_impact(" in source, "blast radius must be real"


class TestWriteToken:
    """Reads stay open so judges can browse; writes are gated in deployment."""

    def test_writes_rejected_without_token(self, monkeypatch):
        client = _client(monkeypatch, token="s3cret")
        assert client.post("/api/v1/ask", json={"question": "x"}).status_code == 401
        assert client.post("/api/v1/takedown", json={"doc_id": "x"}).status_code == 401

    def test_wrong_token_rejected(self, monkeypatch):
        client = _client(monkeypatch, token="s3cret")
        response = client.post(
            "/api/v1/ask", json={"question": "x"}, headers={"X-Origin-Token": "nope"}
        )
        assert response.status_code == 401

    def test_reads_stay_open(self, monkeypatch):
        client = _client(monkeypatch, token="s3cret")
        # Health degrades rather than 500s when the cluster is unreachable, so
        # this is safe to assert without one.
        assert client.get("/api/v1/health").status_code == 200

    def test_unset_token_leaves_writes_open_for_local_development(self, monkeypatch):
        client = _client(monkeypatch, token=None)
        assert client.get("/api/v1/health").json()["writes_protected"] is False


class TestHealth:
    def test_reports_its_dependencies_not_just_liveness(self, monkeypatch):
        body = _client(monkeypatch).get("/api/v1/health").json()
        # A health check that only proves the process is up would say "ok" for a
        # deployment that cannot reach its own memory layer.
        assert "cluster" in body and "reachable" in body["cluster"]
        assert body["status"] in {"ok", "degraded"}


@pytest.mark.needs_cluster
class TestAgainstCluster:
    def test_ask_returns_receipts_from_the_ledger(self, monkeypatch):
        client = _client(monkeypatch)
        body = client.post(
            "/api/v1/ask", json={"question": "which datasets are about robotics?"}
        ).json()
        assert body["answer_id"], "the answer must be persisted, not synthesised"
        assert body["receipts"], "an answer with no receipts defeats the point"
        for receipt in body["receipts"]:
            assert receipt["doc_id"]
            assert receipt["license_class"]
            assert 0.0 <= receipt["similarity"] <= 1.0

    def test_extractive_answers_are_declared(self, monkeypatch):
        client = _client(monkeypatch)
        body = client.post("/api/v1/ask", json={"question": "robotics"}).json()
        # Presenting an extractive answer as a generated one would be a lie about
        # provenance in a tool built to prevent those.
        assert isinstance(body["extractive"], bool)

    def test_memory_recall_does_not_teach_the_memory(self, monkeypatch):
        client = _client(monkeypatch)
        before = client.get("/api/v1/memory/rulings").json()["total_remembered"]
        client.post(
            "/api/v1/memory/recall",
            json={"license_raw": "Entirely novel licence text, probe only"},
        )
        after = client.get("/api/v1/memory/rulings").json()["total_remembered"]
        assert after == before, (
            "the recall probe must not persist rulings; a public endpoint that "
            "learned whatever a stranger typed would corrupt the memory"
        )

    def test_recall_reuses_an_exact_prior_ruling(self, monkeypatch):
        client = _client(monkeypatch)
        rulings = client.get("/api/v1/memory/rulings?limit=1").json()["rulings"]
        if not rulings:
            pytest.skip("no rulings remembered yet")
        body = client.post(
            "/api/v1/memory/recall", json={"license_raw": rulings[0]["license_raw"]}
        ).json()
        assert body["outcome"] == "memory:exact"
        assert body["would_call_model"] is False

    def test_impact_is_read_only(self, monkeypatch):
        client = _client(monkeypatch)
        body = client.get("/api/v1/impact/hf:does-not-exist").json()
        assert body["affected_answers_count"] == 0
        assert body["blast_radius"] == []


class TestMetricsEndpoint:
    """Every metric must resolve against the real schema.

    This class exists because ``/api/v1/metrics`` shipped querying a table named
    ``takedown_notices``, which has never existed — the schema calls it
    ``takedowns``. The endpoint returned 500 on the deployed API while the whole
    suite stayed green, because nothing requested it. A metrics endpoint that is
    never called by a test is indistinguishable from a broken one.
    """

    def test_metrics_returns_every_documented_counter(self, monkeypatch):
        client = _client(monkeypatch)
        response = client.get("/api/v1/metrics")

        assert response.status_code == 200, response.text
        body = response.json()

        for field in (
            "rulings_remembered",
            "rulings_reinforced_reuse",
            "memory_hit_rate_pct",
            "total_answers_recorded",
            "answers_with_no_match",
            "answers_missing_attributions",
            "total_takedowns_processed",
            "total_sessions",
            "total_session_turns",
        ):
            assert field in body, f"{field} missing from /api/v1/metrics"
            assert isinstance(body[field], (int, float)), field

        assert "atomic_attribution_integrity_verified" in body
        assert isinstance(body["atomic_attribution_integrity_verified"], bool)

    def test_memory_hit_rate_is_a_percentage(self, monkeypatch):
        """Guards the ``max(1, ...)`` divisor as much as the arithmetic."""
        client = _client(monkeypatch)
        rate = client.get("/api/v1/metrics").json()["memory_hit_rate_pct"]
        assert 0.0 <= rate <= 100.0, f"hit rate out of range: {rate}"
