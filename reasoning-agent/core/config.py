"""
LSR Core Configuration
======================

Centralised, environment-driven settings. LSR never hard-codes secrets or a
specific AI vendor: every value is read from the process environment, optionally
seeded from a local ``.env`` file (which is git-ignored).

All knobs share the ``LSR_`` prefix so they are easy to discover and unlikely to
collide with other tooling on a shared host.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

try:  # python-dotenv is optional; the app still runs from real env vars without it.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is a convenience, not a requirement.
    pass


def _get_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _get_csv(name: str, default: tuple) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class LLMSettings:
    """Vendor-neutral language-model configuration (OpenAI-compatible)."""

    provider: str               # "disabled" | "openai" | "azure"
    api_key: Optional[str]
    base_url: Optional[str]     # set for Azure endpoint or local runtimes (Ollama, vLLM, LM Studio)
    model: str
    api_version: Optional[str]  # Azure OpenAI only
    temperature: float

    @property
    def enabled(self) -> bool:
        """A model is usable only if a provider, a model name and credentials/endpoint are set."""
        if self.provider == "disabled" or not self.model:
            return False
        return bool(self.api_key or self.base_url)


@dataclass(frozen=True)
class Settings:
    environment: str
    log_level: str
    cors_origins: List[str]
    api_key: Optional[str]          # optional bearer/API key for mutating endpoints
    llm: LLMSettings
    teams_webhook_url: Optional[str]
    slack_webhook_url: Optional[str]
    escalation_image_url: Optional[str]
    auto_remediation_enabled: bool
    sla_breach_threshold_seconds: int
    dashboard_url: str


def load_settings() -> Settings:
    """Build the immutable settings object from the current environment."""
    llm = LLMSettings(
        provider=os.getenv("LSR_LLM_PROVIDER", "disabled").strip().lower(),
        api_key=os.getenv("LSR_LLM_API_KEY") or None,
        base_url=os.getenv("LSR_LLM_BASE_URL") or None,
        # No default model name on purpose: the operator always chooses the
        # model/deployment that matches their own provider and era.
        model=os.getenv("LSR_LLM_MODEL", ""),
        api_version=os.getenv("LSR_LLM_API_VERSION") or None,
        temperature=float(os.getenv("LSR_LLM_TEMPERATURE", "0.1")),
    )
    return Settings(
        environment=os.getenv("LSR_ENVIRONMENT", "development"),
        log_level=os.getenv("LSR_LOG_LEVEL", "INFO").upper(),
        # Secure default: only the local Vite dev server is trusted. Override in prod.
        cors_origins=_get_csv(
            "LSR_CORS_ORIGINS",
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        ),
        # Optional: when set, mutating endpoints require this key. Unset = open
        # demo mode (so judges/users can run with zero configuration).
        api_key=os.getenv("LSR_API_KEY") or None,
        llm=llm,
        teams_webhook_url=os.getenv("LSR_TEAMS_WEBHOOK_URL") or None,
        slack_webhook_url=os.getenv("LSR_SLACK_WEBHOOK_URL") or None,
        escalation_image_url=os.getenv("LSR_ESCALATION_IMAGE_URL") or None,
        auto_remediation_enabled=_get_bool("LSR_AUTO_REMEDIATION", True),
        sla_breach_threshold_seconds=int(os.getenv("LSR_SLA_BREACH_SECONDS", "30")),
        dashboard_url=os.getenv("LSR_DASHBOARD_URL", "http://localhost:5173"),
    )


# Module-level singleton: import `settings` anywhere in the app.
settings = load_settings()
