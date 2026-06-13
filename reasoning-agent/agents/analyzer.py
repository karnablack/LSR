"""
Foundry IQ Layer: Knowledge-Grounded Runbook Analysis
=====================================================

Matches an infrastructure alert to a *validated* remediation runbook.

Two reasoning paths, identical guarantees:

  1. **Grounded semantic matching** — when a language model is configured, the
     model reads the runbook knowledge base and selects the best match.
  2. **Deterministic signature matching** — when no model is available (offline
     demo) or the model errors, LSR matches on the runbook ``Target Signature``.

In *both* paths the result is validated against the set of runbook references
that actually exist on disk. A model can never invent ("hallucinate") a runbook
token that LSR would then try to execute — this is enforced structurally, not
just by prompt wording.
"""
from __future__ import annotations

import glob
import logging
import os
import re
from typing import List, Optional, Set

from agents.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

NO_MATCH = "RUNBOOK_REF: NONE"

# Deterministic fallback map: asset-id signature -> runbook reference.
# Mirrors the ``Target Signature`` header declared inside each runbook markdown.
_SIGNATURE_RUNBOOKS = (
    ("db_", "RUNBOOK_REF: RB_DOCKER_RESTART_VALIDATED"),
    ("gateway_", "RUNBOOK_REF: RB_GATEWAY_FLUSH"),
)

_RUNBOOK_REF_PATTERN = re.compile(r"RUNBOOK_REF:\s*([A-Z0-9_]+)")


class IncidentAnalyzer:
    """Resolve incidents to grounded, executable runbook references."""

    def __init__(self, foundry_directory: str, llm: Optional[LLMProvider] = None):
        self.foundry_directory = foundry_directory
        # Inject a provider for testing/reuse; otherwise build from global settings.
        self.llm = llm if llm is not None else LLMProvider()

    # ------------------------------------------------------------------ #
    # Knowledge base loading
    # ------------------------------------------------------------------ #
    def _runbook_files(self) -> List[str]:
        return sorted(glob.glob(os.path.join(self.foundry_directory, "*.md")))

    def fetch_validated_runbooks(self) -> str:
        """Concatenate every runbook markdown file into a single grounding context."""
        context = ""
        files = self._runbook_files()
        logger.info("Loading %d runbook(s) from Foundry IQ store.", len(files))
        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    context += f"\n\n--- FILE: {os.path.basename(path)} ---\n{fh.read()}"
            except OSError as exc:
                logger.error("Could not read runbook %s: %s", path, exc)
        return context

    def _known_references(self) -> Set[str]:
        """The allow-list of runbook tokens that physically exist on disk."""
        refs: Set[str] = {"NONE"}
        for path in self._runbook_files():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    refs.update(_RUNBOOK_REF_PATTERN.findall(fh.read()))
            except OSError:
                continue
        return refs

    # ------------------------------------------------------------------ #
    # Matching
    # ------------------------------------------------------------------ #
    def _deterministic_match(self, asset_id: str) -> str:
        for signature, runbook in _SIGNATURE_RUNBOOKS:
            if signature in asset_id:
                return runbook
        return NO_MATCH

    def _validate(self, candidate: str, known_refs: Set[str]) -> Optional[str]:
        """Return a clean ``RUNBOOK_REF: <TOKEN>`` only if the token really exists."""
        match = _RUNBOOK_REF_PATTERN.search(candidate or "")
        if not match:
            return None
        token = match.group(1)
        if token in known_refs:
            return f"RUNBOOK_REF: {token}"
        return None

    def evaluate_remediation_strategy(
        self,
        asset_id: str,
        alert_message: str,
        audit_logs: Optional[List[str]] = None,
    ) -> str:
        """Return a validated runbook reference for the given incident."""
        if audit_logs is None:
            audit_logs = []

        audit_logs.append("🧠 [FOUNDRY IQ] Grounding alert against validated runbook store...")

        # ---- Deterministic path (no model configured) -------------------- #
        if not self.llm.available:
            result = self._deterministic_match(asset_id)
            audit_logs.append(f"🛡️ [FOUNDRY IQ] Deterministic signature match → {result}")
            return result

        # ---- Grounded semantic path -------------------------------------- #
        knowledge_base = self.fetch_validated_runbooks()
        if not knowledge_base.strip():
            audit_logs.append("⚠️ [FOUNDRY IQ] Knowledge base empty; defaulting to NONE.")
            return NO_MATCH

        system_instruction = (
            "You are the LSR Foundry IQ analytical engine.\n"
            "1. Read the provided infrastructure runbooks (validated remediation procedures).\n"
            "2. Select the single most appropriate runbook for the incident alert.\n"
            "3. Respond with ONLY the reference string, format: RUNBOOK_REF: <TOKEN>\n\n"
            "Rules:\n"
            "- Output ONLY the reference string. No prose, no markdown.\n"
            "- If nothing matches, output exactly: RUNBOOK_REF: NONE\n"
            "- Never invent a runbook token. Use only tokens present in the knowledge base.\n"
            "- This output is safety-critical: prefer NONE over a weak guess."
        )
        user_prompt = (
            f"Asset Identifier: {asset_id}\n"
            f"Alert Message: {alert_message}\n\n"
            f"Available Runbooks:\n{knowledge_base}\n\n"
            f"Return the best matching runbook reference."
        )

        raw = self.llm.complete(system_instruction, user_prompt)
        known_refs = self._known_references()
        validated = self._validate(raw, known_refs) if raw is not None else None

        if validated is None:
            # Model unavailable, errored, or returned an unknown/hallucinated token.
            result = self._deterministic_match(asset_id)
            audit_logs.append(
                f"🛡️ [FOUNDRY IQ] Model output unusable; deterministic fallback → {result}"
            )
            return result

        audit_logs.append(f"📖 [FOUNDRY IQ] Grounded match ({self.llm.model_name}) → {validated}")
        return validated
