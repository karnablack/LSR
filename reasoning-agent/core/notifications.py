"""
LSR Notification Layer
======================

Delivers incident context to where the on-call engineer actually is — Microsoft
Teams and/or Slack — and drives the **SLA escalation** follow-up.

Design notes
------------
* Teams payloads use the modern **Adaptive Card** envelope accepted by Teams
  *Workflows* incoming webhooks.
* Every send is best-effort and fully isolated: a missing webhook or a network
  error degrades gracefully to a logged no-op and never breaks incident triage.
* The escalation message is the productive, human-friendly version of the
  "attention" idea: a calm follow-up nudge ("still awaiting acknowledgement").
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from core.config import Settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5


class NotificationService:
    """Best-effort multi-channel incident notifications."""

    def __init__(self, settings: Settings):
        self._teams_url = settings.teams_webhook_url
        self._slack_url = settings.slack_webhook_url
        self._dashboard_url = settings.dashboard_url
        self._escalation_image_url = settings.escalation_image_url

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def notify_incident(self, incident: dict) -> dict:
        """Send the initial incident card to all configured channels."""
        return {
            "teams": self._post(self._teams_url, self._teams_incident_card(incident)),
            "slack": self._post(self._slack_url, self._slack_incident_message(incident)),
        }

    def notify_escalation(self, incident: dict) -> dict:
        """Send the SLA-breach follow-up nudge to all configured channels."""
        return {
            "teams": self._post(self._teams_url, self._teams_escalation_card(incident)),
            "slack": self._post(self._slack_url, self._slack_escalation_message(incident)),
        }

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    @staticmethod
    def _post(url: Optional[str], payload: Optional[dict]) -> bool:
        if not url or payload is None:
            return False
        try:
            resp = requests.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
            if resp.status_code in (200, 202):
                return True
            logger.warning("Notification webhook returned HTTP %s.", resp.status_code)
            return False
        except requests.RequestException as exc:
            logger.error("Notification webhook error: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Teams Adaptive Cards
    # ------------------------------------------------------------------ #
    def _teams_incident_card(self, incident: dict) -> dict:
        criticality = incident.get("blast_radius_index", 0) or 0
        color = "Attention" if criticality >= 0.5 else "Warning"
        facts = [
            {"title": "Asset", "value": f"{incident.get('asset_name', '—')} ({incident.get('asset_id', '—')})"},
            {"title": "Business impact", "value": incident.get("impacted_business_process", "—")},
            {"title": "Criticality index", "value": f"{criticality:.2f}"},
            {"title": "Assigned engineer", "value": incident.get("assigned_engineer", "Unassigned")},
            {"title": "Runbook", "value": incident.get("resolved_runbook", "—")},
            {"title": "Status", "value": incident.get("incident_status", "—")},
        ]
        body = [
            {
                "type": "TextBlock",
                "size": "Large",
                "weight": "Bolder",
                "text": "🚨 LSR Incident Detected",
                "color": color,
                "wrap": True,
            },
            {"type": "FactSet", "facts": facts},
        ]
        return self._wrap_adaptive_card(body)

    def _teams_escalation_card(self, incident: dict) -> dict:
        body = [
            {
                "type": "TextBlock",
                "size": "Large",
                "weight": "Bolder",
                "text": "⏰ SLA Acknowledgement Pending",
                "color": "Attention",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "wrap": True,
                "text": (
                    f"Incident on **{incident.get('asset_name', incident.get('asset_id', 'asset'))}** "
                    f"is still awaiting acknowledgement. Please open the dashboard when you get a moment."
                ),
            },
        ]
        if self._escalation_image_url:
            body.append({
                "type": "Image",
                "url": self._escalation_image_url,
                "size": "Medium",
                "horizontalAlignment": "Center",
                "altText": "A gentle reminder to take a look",
            })
        return self._wrap_adaptive_card(body)

    def _wrap_adaptive_card(self, body: list) -> dict:
        """Wrap card body in the Teams Workflows-compatible message envelope."""
        actions = [{
            "type": "Action.OpenUrl",
            "title": "Open LSR Dashboard",
            "url": self._dashboard_url,
        }]
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": body,
                        "actions": actions,
                    },
                }
            ],
        }

    # ------------------------------------------------------------------ #
    # Slack messages
    # ------------------------------------------------------------------ #
    def _slack_incident_message(self, incident: dict) -> dict:
        criticality = incident.get("blast_radius_index", 0) or 0
        color = "#d92d20" if criticality >= 0.5 else "#f79009"
        return {
            "attachments": [
                {
                    "color": color,
                    "title": f"🚨 LSR Incident: {incident.get('asset_name', incident.get('asset_id', 'asset'))}",
                    "fields": [
                        {"title": "Asset ID", "value": incident.get("asset_id", "—"), "short": True},
                        {"title": "Business impact", "value": incident.get("impacted_business_process", "—"), "short": True},
                        {"title": "Criticality", "value": f"{criticality:.2f}", "short": True},
                        {"title": "Assigned", "value": incident.get("assigned_engineer", "Unassigned"), "short": True},
                        {"title": "Runbook", "value": incident.get("resolved_runbook", "—"), "short": False},
                        {"title": "Status", "value": incident.get("incident_status", "—"), "short": True},
                    ],
                    "actions": [
                        {"type": "button", "text": "Open Dashboard", "url": self._dashboard_url},
                    ],
                    "footer": "LSR — Synaptic Response Center",
                }
            ]
        }

    def _slack_escalation_message(self, incident: dict) -> dict:
        attachment = {
            "color": "#d92d20",
            "title": "⏰ SLA acknowledgement pending",
            "text": (
                f"Incident on *{incident.get('asset_name', incident.get('asset_id', 'asset'))}* "
                f"is still awaiting acknowledgement."
            ),
            "actions": [{"type": "button", "text": "Open Dashboard", "url": self._dashboard_url}],
            "footer": "LSR — Synaptic Response Center",
        }
        if self._escalation_image_url:
            attachment["image_url"] = self._escalation_image_url
        return {"attachments": [attachment]}
