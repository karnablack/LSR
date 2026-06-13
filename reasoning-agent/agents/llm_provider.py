"""
LSR LLM Provider — Vendor-Neutral Language-Model Access
=======================================================

LSR is deliberately **not** tied to any single AI vendor. Every reasoning call
goes through this thin abstraction, which speaks the OpenAI-compatible Chat
Completions contract used by virtually the entire ecosystem:

    * Azure OpenAI / Azure AI Foundry ...... LSR_LLM_PROVIDER=azure
    * OpenAI ............................... LSR_LLM_PROVIDER=openai
    * Local / self-hosted runtimes ......... LSR_LLM_PROVIDER=openai + LSR_LLM_BASE_URL
      (Ollama, LM Studio, vLLM, llama.cpp, OpenRouter, ...)
    * Deterministic offline mode ........... LSR_LLM_PROVIDER=disabled  (default)

Because the rest of the codebase depends only on ``LLMProvider.complete()``,
switching vendors — or running with no model at all — never touches agent logic.
The offline mode guarantees the system (and the demo) works with zero
configuration and zero external calls.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.config import LLMSettings, settings as global_settings

logger = logging.getLogger(__name__)


class LLMProvider:
    """Lazily-initialised, fail-safe wrapper around an OpenAI-compatible client."""

    def __init__(self, llm_settings: Optional[LLMSettings] = None):
        self._settings = llm_settings or global_settings.llm
        self._client = None

        if not self._settings.enabled:
            logger.info("LLM provider disabled — deterministic offline reasoning active.")
            return

        try:
            self._client = self._build_client(self._settings)
            logger.info(
                "LLM provider ready (provider=%s, model=%s).",
                self._settings.provider,
                self._settings.model,
            )
        except Exception as exc:  # never let model setup crash the service
            logger.warning("LLM provider init failed (%s); using deterministic mode.", exc)
            self._client = None

    @staticmethod
    def _build_client(cfg: LLMSettings):
        """Construct the right client for the configured provider."""
        if cfg.provider == "azure":
            from openai import AzureOpenAI

            if not cfg.api_version:
                # Azure requires an explicit api-version; we never hard-code one
                # because the right value depends on the operator's deployment.
                raise ValueError("LSR_LLM_API_VERSION is required for the azure provider.")
            return AzureOpenAI(
                api_key=cfg.api_key,
                azure_endpoint=cfg.base_url,
                api_version=cfg.api_version,
            )

        # "openai" provider also covers any OpenAI-compatible endpoint via base_url.
        from openai import OpenAI

        return OpenAI(
            api_key=cfg.api_key or "not-required",  # local runtimes ignore the key
            base_url=cfg.base_url,                   # None → api.openai.com
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def model_name(self) -> str:
        return self._settings.model

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
    ) -> Optional[str]:
        """
        Run a single grounded completion.

        Returns the model's text, or ``None`` when the model is unavailable or
        errors out — callers MUST provide a deterministic fallback so LSR never
        depends on an external model being reachable.
        """
        if not self._client:
            return None

        try:
            response = self._client.chat.completions.create(
                model=self._settings.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._settings.temperature if temperature is None else temperature,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.error("LLM completion failed (%s); caller will fall back.", exc)
            return None
