"""Configuration, and the two submission profiles.

``require_aws_for_cockroachdb`` exists because the product demos perfectly well
with no AWS at all — which is correct for the DataHub submission and
disqualifying for the CockroachDB one. Without this guard the failure mode is
silent: record the video, submit, get rejected on a requirement nobody checked.
"""

from __future__ import annotations

import pytest

from origin import config


@pytest.fixture(autouse=True)
def clear_config_cache():
    """``config.load`` is cached; each test needs a fresh read of the env."""
    config.load.cache_clear()
    yield
    config.load.cache_clear()


@pytest.fixture
def env(monkeypatch):
    """A minimal valid environment. Tests override individual keys."""
    for key in [
        "ORIGIN_PROVIDER",
        "ORIGIN_STORAGE",
        "ORIGIN_S3_BUCKET",
        "ORIGIN_EMBED_DIM",
        "DATABASE_URL",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:26257/origin")
    return monkeypatch


class TestSubmissionProfiles:
    def test_datahub_profile_uses_no_aws(self, env):
        env.setenv("ORIGIN_PROVIDER", "local")
        env.setenv("ORIGIN_STORAGE", "local")
        cfg = config.load()
        assert cfg.uses_aws is False

    def test_datahub_profile_is_rejected_for_the_cockroachdb_submission(self, env):
        env.setenv("ORIGIN_PROVIDER", "local")
        env.setenv("ORIGIN_STORAGE", "local")
        with pytest.raises(config.ConfigError, match="no AWS service"):
            config.load().require_aws_for_cockroachdb()

    def test_bedrock_alone_satisfies_the_aws_requirement(self, env):
        env.setenv("ORIGIN_PROVIDER", "bedrock")
        env.setenv("ORIGIN_STORAGE", "local")
        cfg = config.load()
        assert cfg.uses_aws is True
        cfg.require_aws_for_cockroachdb()  # must not raise

    def test_s3_alone_satisfies_the_aws_requirement(self, env):
        env.setenv("ORIGIN_PROVIDER", "local")
        env.setenv("ORIGIN_STORAGE", "s3")
        env.setenv("ORIGIN_S3_BUCKET", "some-bucket")
        cfg = config.load()
        assert cfg.uses_aws is True
        cfg.require_aws_for_cockroachdb()  # must not raise


class TestValidation:
    def test_rejects_unknown_provider(self, env):
        env.setenv("ORIGIN_PROVIDER", "openai")
        with pytest.raises(config.ConfigError, match="ORIGIN_PROVIDER"):
            config.load()

    def test_rejects_unknown_storage(self, env):
        env.setenv("ORIGIN_STORAGE", "gcs")
        with pytest.raises(config.ConfigError, match="ORIGIN_STORAGE"):
            config.load()

    def test_s3_storage_requires_a_bucket(self, env):
        env.setenv("ORIGIN_STORAGE", "s3")
        with pytest.raises(config.ConfigError, match="ORIGIN_S3_BUCKET"):
            config.load()

    def test_embed_dim_must_match_the_schema(self, env):
        """Drifting from VECTOR(1024) produces an insert-time error that reads
        as a database problem, so it is caught here instead."""
        env.setenv("ORIGIN_EMBED_DIM", "512")
        with pytest.raises(config.ConfigError, match="VECTOR\\(1024\\)"):
            config.load()

    def test_embed_dim_must_be_an_integer(self, env):
        env.setenv("ORIGIN_EMBED_DIM", "wide")
        with pytest.raises(config.ConfigError, match="integer"):
            config.load()

    def test_missing_database_url_is_reported_actionably(self, env):
        env.delenv("DATABASE_URL", raising=False)
        with pytest.raises(config.ConfigError, match="CockroachDB Cloud"):
            config.load().require_database()

    def test_gms_url_trailing_slash_is_normalised(self, env):
        env.setenv("DATAHUB_GMS_URL", "http://localhost:8080/")
        assert config.load().datahub_gms_url == "http://localhost:8080"
