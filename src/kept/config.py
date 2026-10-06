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
    # Appended to drafts after "Best,". Empty means just "Best,".
    user_name: str = ""
    web_dir: Path = Path("frontend/dist")

    egress_allowlist: Annotated[list[str], NoDecode] = [
        "api.tokenfactory.us-central1.nebius.com",
        "api.tavily.com",
    ]

    # Proactive keeping: draft promises due within this many days, at most this many per run.
    sweep_horizon_days: int = 3
    sweep_max_per_run: int = 5

    # Demo mode: every visitor gets a private, temporary workspace; email is forced off.
    demo_mode: bool = False
    demo_max_sessions: int = 200
    demo_session_minutes: int = 120
    demo_max_notes: int = 20
    demo_max_drafts: int = 40
    demo_max_checks: int = 10
    demo_max_manual: int = 50
    demo_max_concurrent: int = 4
    demo_max_note_chars: int = 8000
    # Optional. Entering it lifts a visitor's limits (put it in the submission's testing notes).
    demo_access_code: SecretStr = SecretStr("")

    # Outbound email. Off unless smtp_host and email_from are set.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    email_from: str = ""
    # Addresses or @domains Kept may send to. Empty means only email_from itself.
    email_allowed_recipients: Annotated[list[str], NoDecode] = []

    @field_validator("egress_allowlist", "email_allowed_recipients", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return value

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.email_from)

    @property
    def allowed_hosts(self) -> list[str]:
        """Every host this app may contact, including the mail server when sending is on."""
        hosts = [*self.egress_allowlist, *([self.smtp_host.lower()] if self.email_enabled else [])]
        return sorted(set(hosts))

    def model_for(self, tier: Tier) -> str:
        return {
            Tier.NANO: self.model_nano,
            Tier.SUPER: self.model_super,
            Tier.ULTRA: self.model_ultra,
        }[tier]


@lru_cache
def get_settings() -> Settings:
    return Settings()
