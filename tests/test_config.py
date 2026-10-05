import pytest

from kept.config import Settings
from kept.domain.models import Tier


def test_allowlist_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEPT_EGRESS_ALLOWLIST", "A.example.com, b.example.com ,")
    settings = Settings(_env_file=None)
    assert settings.egress_allowlist == ["a.example.com", "b.example.com"]


def test_model_for_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEPT_MODEL_ULTRA", "nvidia/ultra-test")
    settings = Settings(_env_file=None)
    assert settings.model_for(Tier.ULTRA) == "nvidia/ultra-test"
    assert settings.model_for(Tier.NANO).startswith("nvidia/")
