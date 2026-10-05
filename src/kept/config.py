from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from kept.domain.models import Tier


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KEPT_", env_file=".env", extra="ignore")

    nebius_api_key: SecretStr = SecretStr("")
    nebius_base_url: str = "https://api.tokenfactory.us-central1.nebius.com/v1/"

    model_nano: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    model_super: str = "nvidia/nemotron-3-super-120b-a12b"
    model_ultra: str = "nvidia/Nemotron-3-Ultra-550b-a55b"

    tavily_api_key: SecretStr = SecretStr("")

    db_path: Path = Path("data/kept.db")
    web_dir: Path = Path("web")

    egress_allowlist: Annotated[list[str], NoDecode] = [
        "api.tokenfactory.us-central1.nebius.com",
        "api.tavily.com",
    ]

    @field_validator("egress_allowlist", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [host.strip().lower() for host in value.split(",") if host.strip()]
        return value

    def model_for(self, tier: Tier) -> str:
        return {
            Tier.NANO: self.model_nano,
            Tier.SUPER: self.model_super,
            Tier.ULTRA: self.model_ultra,
        }[tier]


@lru_cache
def get_settings() -> Settings:
    return Settings()
