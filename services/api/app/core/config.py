import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRONTIER_", extra="ignore", hide_input_in_errors=True
    )

    env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://frontier:frontier_local@localhost:5432/frontier"
    )
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    fake_provider: bool = True
    mock_auth: bool = False
    password_auth: bool = True
    llm_provider: Literal["local_rules", "openai_responses"] = "local_rules"
    openai_api_key: SecretStr | None = None
    openai_model: str = ""
    model_user_calls_per_day: int = 10
    model_user_tokens_per_day: int = 50_000
    model_global_calls_per_day: int = 100
    model_global_tokens_per_day: int = 200_000
    github_app_id: str = ""
    github_client_id: str = ""
    github_client_secret: SecretStr | None = None
    github_private_key: SecretStr | None = None
    github_app_slug: str = ""
    public_api_url: str = "http://127.0.0.1:8000"
    public_web_url: str = "http://localhost:5173"
    writeback_enabled: bool = False
    encryption_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        github_values = [
            self.github_app_id,
            self.github_client_id,
            self.github_client_secret,
            self.github_private_key,
            self.github_app_slug,
        ]
        if any(github_values) and not all(github_values):
            raise ValueError("Configure all GitHub App credentials together")
        if self.github_app_id:
            if not self.github_app_id.isdigit() or not re.fullmatch(
                r"[a-zA-Z0-9_-]{1,100}", self.github_app_slug
            ):
                raise ValueError("Invalid GitHub App identifier")
            urls = [urlsplit(self.public_api_url), urlsplit(self.public_web_url)]
            for url in urls:
                if (
                    url.scheme not in {"https", "http"}
                    or not url.hostname
                    or url.username
                    or url.password
                    or url.path not in {"", "/"}
                    or url.query
                    or url.fragment
                ):
                    raise ValueError("Public service URLs must be trusted origins")
                if url.scheme != "https" and (
                    self.env == "production" or url.hostname not in {"localhost", "127.0.0.1"}
                ):
                    raise ValueError("GitHub App requires HTTPS except loopback development")
            if urls[0].hostname != urls[1].hostname or urls[0].scheme != urls[1].scheme:
                raise ValueError("OAuth browser binding requires the same API/Web host and scheme")
            if self.public_web_url.rstrip("/") not in self.allowed_origins:
                raise ValueError("Public Web origin must be explicitly allowed")
        if self.llm_provider == "openai_responses" and (
            not self.openai_api_key or not self.openai_model.strip()
        ):
            raise ValueError("OpenAI provider requires a server key and explicit model")
        if any(
            not 1 <= n <= 1_000_000
            for n in (
                self.model_user_calls_per_day,
                self.model_user_tokens_per_day,
                self.model_global_calls_per_day,
                self.model_global_tokens_per_day,
            )
        ):
            raise ValueError("Invalid daily model budget")
        if self.encryption_key is not None and self.encryption_key.get_secret_value():
            try:
                Fernet(self.encryption_key.get_secret_value().encode())
            except (ValueError, TypeError):
                raise ValueError("Invalid credential encryption key") from None
        if self.env == "production":
            if self.mock_auth:
                raise ValueError("Mock identity is forbidden in production")
            if self.encryption_key is None or not self.encryption_key.get_secret_value():
                raise ValueError("Production requires a configured encryption key")
            if "frontier_local" in self.database_url.get_secret_value():
                raise ValueError("Production requires dedicated database credentials")
            if self.password_auth and any(
                not origin.startswith("https://") for origin in self.allowed_origins
            ):
                raise ValueError("Production password login requires HTTPS Web origins")
        if not self.database_url.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("A PostgreSQL asyncpg URL is required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
