"""Central configuration — loads secrets and settings from the environment.

Values are read from a `.env` file (see `.env.example`) via python-dotenv,
falling back to real environment variables. Import `settings` anywhere in the
backend rather than reading os.environ directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load the .env that sits at the repo root (one level above backend/).
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)
# Also load a plain .env from the current working directory if present.
load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # ── Core API keys ──────────────────────────────────────────
    bright_data_api_key: str = field(default_factory=lambda: _get("BRIGHT_DATA_API_KEY"))
    aiml_api_key: str = field(default_factory=lambda: _get("AIML_API_KEY"))
    cognee_api_key: str = field(default_factory=lambda: _get("COGNEE_API_KEY"))
    solana_rpc_url: str = field(
        default_factory=lambda: _get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    )
    # Optional signer key: base58 string or JSON byte array. If unset, an
    # ephemeral keypair is generated (testing only).
    solana_private_key: str = field(default_factory=lambda: _get("SOLANA_PRIVATE_KEY"))

    # ── Bright Data zones / proxy ──────────────────────────────
    bright_data_serp_zone: str = field(
        default_factory=lambda: _get("BRIGHT_DATA_SERP_ZONE", "serp_api")
    )
    bright_data_unlocker_zone: str = field(
        default_factory=lambda: _get("BRIGHT_DATA_UNLOCKER_ZONE", "web_unlocker")
    )
    bright_data_proxy_host: str = field(
        default_factory=lambda: _get("BRIGHT_DATA_PROXY_HOST", "brd.superproxy.io")
    )
    bright_data_proxy_port: int = field(
        default_factory=lambda: int(_get("BRIGHT_DATA_PROXY_PORT", "33335") or "33335")
    )
    bright_data_customer_id: str = field(
        default_factory=lambda: _get("BRIGHT_DATA_CUSTOMER_ID")
    )
    bright_data_proxy_password: str = field(
        default_factory=lambda: _get("BRIGHT_DATA_PROXY_PASSWORD")
    )

    # ── AI/ML API ──────────────────────────────────────────────
    aiml_api_base: str = field(
        default_factory=lambda: _get("AIML_API_BASE", "https://api.aimlapi.com/v1")
    )
    aiml_model: str = field(default_factory=lambda: _get("AIML_MODEL", "gpt-4o"))

    # ── Cognee (evidence graph) ────────────────────────────────
    cognee_llm_api_key: str = field(default_factory=lambda: _get("COGNEE_LLM_API_KEY"))
    cognee_vector_db_provider: str = field(
        default_factory=lambda: _get("COGNEE_VECTOR_DB_PROVIDER", "lancedb")
    )
    cognee_llm_endpoint: str = field(default_factory=lambda: _get("COGNEE_LLM_ENDPOINT"))
    cognee_llm_model: str = field(
        default_factory=lambda: _get("COGNEE_LLM_MODEL", "gpt-4o")
    )

    # ── Bright Data Direct API endpoint ────────────────────────
    bright_data_request_url: str = "https://api.brightdata.com/request"

    def proxy_username(self) -> str:
        """Build the super-proxy username for the Web Unlocker zone."""
        return f"brd-customer-{self.bright_data_customer_id}-zone-{self.bright_data_unlocker_zone}"

    def proxy_url(self) -> str:
        """Full proxy URL usable by httpx for the Web Unlocker zone."""
        return (
            f"http://{self.proxy_username()}:{self.bright_data_proxy_password}"
            f"@{self.bright_data_proxy_host}:{self.bright_data_proxy_port}"
        )


settings = Settings()
