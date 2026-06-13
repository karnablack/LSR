"""
LSR Synaptic Response Center — API Core
=======================================

FastAPI service that triages an infrastructure alert across the three Microsoft
IQ intelligence layers and drives the response workflow:

    Fabric IQ   → business blast-radius (asset → process → SLA/financial weight)
    Foundry IQ  → grounded, validated remediation runbook
    Work IQ     → smart on-call routing to an available engineer

It then either auto-remediates low-risk incidents or routes a human-validation
card to Teams/Slack, and exposes a vendor-neutral assistant + audit trail to the
dashboard. The service is event-driven and holds a single active-incident state
in memory (swap for Redis/DB in a multi-replica deployment).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.analyzer import IncidentAnalyzer
from agents.executor import IncidentExecutor
from agents.llm_provider import LLMProvider
from core.config import settings
from core.notifications import NotificationService

# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("lsr")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FABRIC_PATH = os.path.join(DATA_DIR, "fabric_iq", "topology_graph.json")
FOUNDRY_DIR = os.path.join(DATA_DIR, "foundry_iq")
WORK_PATH = os.path.join(DATA_DIR, "work_iq", "on_call_graph.json")

# Shared, reusable singletons.
llm = LLMProvider()
analyzer = IncidentAnalyzer(FOUNDRY_DIR, llm=llm)
notifications = NotificationService(settings)

# Single in-memory incident state. Replace with a shared store for HA.
CURRENT_INCIDENT_STATE: dict = {
    "active": False,
    "data": None,
    "logs": [],
    "escalated": False,
    "incident_history": [],
}

app = FastAPI(
    title="LSR — Synaptic Response Center",
    description="Event-driven incident reasoning across Microsoft Fabric IQ, Foundry IQ and Work IQ.",
    version="1.1.0",
)

# Security: trust only explicitly-configured origins (never "*"). For local
# development we additionally allow any localhost/127.0.0.1 port via regex, so it
# doesn't matter which port the Vite dev server lands on (5173, 5174, ...).
# A remote site can never present a localhost origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Defense-in-depth response headers for every endpoint (incl. /docs)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


def require_api_key(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
):
    """
    Optional auth for state-changing / cost-incurring endpoints.

    - If `LSR_API_KEY` is NOT set: open mode (zero-config demo) — anyone can call.
    - If it IS set: callers must present it as `Authorization: Bearer <key>` or
      `X-API-Key: <key>`. Comparison is constant-time.

    Read-only endpoints (/api/incident, /api/config, /health) stay open so the
    dashboard can poll without embedding a secret in the browser.
    """
    expected = settings.api_key
    if not expected:
        return
    provided = x_api_key
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class InfrastructureAlert(BaseModel):
    """Strictly-bounded ingress contract: lengths capped, identifiers shape-checked."""

    asset_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-\.]+$")
    alert_message: str = Field(min_length=1, max_length=2000)
    environment: str = Field(default="production", max_length=32)
    severity: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")


class AssistantQuery(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class DemoTrigger(BaseModel):
    # Optional override so judges can fire a specific scenario from the UI.
    asset_id: Optional[str] = Field(default=None, max_length=64)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str, label: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        # Log full detail server-side; return a generic message (no path leakage).
        logger.error("Failed to load %s (%s): %s", label, path, exc)
        raise HTTPException(status_code=500, detail=f"Failed to load {label}.")


def _select_engineer(work_data: dict, audit_logs: list) -> Optional[dict]:
    """Work IQ routing: prefer the highest-priority Online + Available engineer."""
    directory = sorted(work_data.get("directory", []), key=lambda e: e.get("routing_priority", 99))
    engineer = next(
        (e for e in directory
         if e.get("m365_presence") == "Online" and e.get("calendar_status") == "Available"),
        None,
    )
    if engineer:
        audit_logs.append(f"✓ [WORK IQ] Routed to {engineer['display_name']} ({engineer['role']})")
        return engineer
    if directory:
        fallback = directory[0]
        audit_logs.append("⚠️ [WORK IQ] No Online/Available engineer; using priority fallback.")
        return fallback
    return None


def process_alert(alert: InfrastructureAlert) -> dict:
    """Run the full Fabric IQ → Foundry IQ → Work IQ triage pipeline."""
    global CURRENT_INCIDENT_STATE

    audit_logs: list = []
    timestamp = _now()
    audit_logs.append(f"📡 [INGRESS] Alert received for {alert.asset_id}")
    audit_logs.append(f"   Environment: {alert.environment} · Severity: {alert.severity}")

    # ---- Phase 1: Fabric IQ — business blast radius ---------------------- #
    fabric_data = _load_json(FABRIC_PATH, "Fabric IQ topology")
    target_asset = next(
        (n for n in fabric_data.get("nodes", []) if n["asset_id"] == alert.asset_id),
        None,
    )
    if not target_asset:
        audit_logs.append(f"❌ [FABRIC IQ] Asset {alert.asset_id} not present in topology.")
        CURRENT_INCIDENT_STATE = {
            "active": True, "data": None, "logs": audit_logs,
            "escalated": False,
            "incident_history": CURRENT_INCIDENT_STATE.get("incident_history", []),
        }
        return {"status": "UNMAPPED_ASSET", "asset_id": alert.asset_id}

    criticality_index = target_asset["criticality_index"]
    audit_logs.append(f"✓ [FABRIC IQ] {target_asset['asset_name']} → {target_asset['impacted_business_process']}")
    audit_logs.append(f"   Criticality index: {criticality_index:.2f}")

    # ---- Phase 2: Foundry IQ — grounded runbook -------------------------- #
    resolved_runbook = analyzer.evaluate_remediation_strategy(
        alert.asset_id, alert.alert_message, audit_logs
    )

    # ---- Phase 3: Work IQ — on-call routing ------------------------------ #
    work_data = _load_json(WORK_PATH, "Work IQ directory")
    engineer = _select_engineer(work_data, audit_logs)

    # ---- Phase 4: decision gateway --------------------------------------- #
    if "NONE" in resolved_runbook:
        posture = "ESCALATION_REQUIRED"
        summary = "No validated remediation signature. Manual review required."
    elif criticality_index >= 0.5:
        posture = "HUMAN_VALIDATION_REQUIRED"
        summary = f"High criticality ({criticality_index:.2f}); engineer approval required before action."
    elif not settings.auto_remediation_enabled:
        posture = "HUMAN_VALIDATION_REQUIRED"
        summary = "Auto-remediation disabled by policy; awaiting engineer approval."
    else:
        posture = "AUTO_REMEDIATION"
        summary = f"Low risk; executing validated runbook {resolved_runbook}."
        IncidentExecutor().execute_remediation(resolved_runbook, audit_logs)

    audit_logs.append(f"🛡️ [DECISION] {posture} — {summary}")

    incident_data = {
        "timestamp": timestamp,
        "asset_id": alert.asset_id,
        "asset_name": target_asset["asset_name"],
        "impacted_business_process": target_asset["impacted_business_process"],
        "blast_radius_index": criticality_index,
        "sla_tier": target_asset.get("sla_tier"),
        "sla_breach_threshold_seconds": target_asset.get(
            "sla_breach_threshold_seconds", settings.sla_breach_threshold_seconds
        ),
        "resolved_runbook": resolved_runbook,
        "assigned_engineer": engineer["display_name"] if engineer else "Unassigned",
        "assigned_engineer_presence": engineer["m365_presence"] if engineer else "Unknown",
        "incident_status": posture,
        "alert_message": alert.alert_message,
        "environment": alert.environment,
        "severity": alert.severity,
        # Topology snapshot powers the dashboard's blast-radius view (no money counters).
        "topology": fabric_data.get("nodes", []),
    }

    notifications.notify_incident(incident_data)

    CURRENT_INCIDENT_STATE = {
        "active": True,
        "data": incident_data,
        "logs": audit_logs,
        "escalated": False,
        "incident_history": CURRENT_INCIDENT_STATE.get("incident_history", []),
    }
    logger.info("Incident processed: asset=%s posture=%s", alert.asset_id, posture)
    return {
        "status": "processed",
        "incident_posture": posture,
        "incident_id": alert.asset_id,
        "asset_name": target_asset["asset_name"],
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.post("/webhook/alerts", dependencies=[Depends(require_api_key)])
async def handle_infrastructure_alert(alert: InfrastructureAlert):
    """Primary ingress for monitoring systems (Event Grid / Alertmanager / webhooks)."""
    return process_alert(alert)


@app.post("/api/demo/trigger", dependencies=[Depends(require_api_key)])
async def demo_trigger(trigger: DemoTrigger):
    """
    Self-contained demo entry point so a judge can fire a realistic incident
    straight from the dashboard — no external monitoring system required.
    """
    scenarios = {
        "db_5": "Socket closed unexpectedly. Connection timeouts on primary pool.",
        "gateway_2": "High packet congestion. Dynamic transit buffer queues are full.",
    }
    asset_id = trigger.asset_id or "db_5"
    if asset_id not in scenarios:  # strict allow-list: demo can only fire known scenarios
        raise HTTPException(status_code=400, detail="Unknown demo scenario.")
    return process_alert(InfrastructureAlert(asset_id=asset_id, alert_message=scenarios[asset_id]))


@app.post("/api/incident/escalate", dependencies=[Depends(require_api_key)])
async def escalate_incident():
    """
    Fire the SLA-breach follow-up: a calm reminder pushed to Teams/Slack when the
    on-call engineer has not acknowledged within the SLA window. Idempotent.
    """
    global CURRENT_INCIDENT_STATE
    if not CURRENT_INCIDENT_STATE["active"] or not CURRENT_INCIDENT_STATE["data"]:
        return {"status": "no_active_incident"}
    if CURRENT_INCIDENT_STATE.get("escalated"):
        return {"status": "already_escalated"}

    delivery = notifications.notify_escalation(CURRENT_INCIDENT_STATE["data"])
    CURRENT_INCIDENT_STATE["escalated"] = True
    CURRENT_INCIDENT_STATE["logs"].append("⏰ [SLA] Acknowledgement window exceeded; escalation sent.")
    logger.info("Escalation dispatched: %s", delivery)
    return {"status": "escalated", "delivery": delivery}


@app.post("/api/copilot/chat", dependencies=[Depends(require_api_key)])
async def assistant_chat(query: AssistantQuery):
    """
    Vendor-neutral incident assistant grounded on the active incident context.
    Falls back to a deterministic summary when no model is configured.
    """
    if not CURRENT_INCIDENT_STATE["active"] or not CURRENT_INCIDENT_STATE["data"]:
        return {"reply": "No active incident. LSR is monitoring ambient telemetry.", "confidence": 0.0}

    incident = CURRENT_INCIDENT_STATE["data"]
    context = (
        f"Active incident context:\n"
        f"- Asset: {incident['asset_id']} ({incident['asset_name']})\n"
        f"- Business impact: {incident['impacted_business_process']}\n"
        f"- Criticality: {incident['blast_radius_index']:.2f}\n"
        f"- Assigned engineer: {incident['assigned_engineer']}\n"
        f"- Runbook: {incident['resolved_runbook']}\n"
        f"- Status: {incident['incident_status']}\n"
    )
    system_instruction = (
        "You are the LSR incident assistant, an expert SRE copilot. Answer strictly "
        "from the provided incident facts. Be concise, professional and actionable. "
        "If asked something the context cannot answer, say so plainly."
    )

    reply = llm.complete(system_instruction, f"{context}\n\nEngineer question: {query.question}")
    if reply:
        return {"reply": reply, "confidence": 0.9, "model": llm.model_name}

    # Deterministic fallback (offline / model error).
    return {
        "reply": (
            f"Offline mode. Incident {incident['asset_id']} is {incident['incident_status']}. "
            f"Validated runbook: {incident['resolved_runbook']}. "
            f"Assigned to {incident['assigned_engineer']}."
        ),
        "confidence": 0.5,
    }


@app.get("/api/config")
async def get_configuration():
    """Non-sensitive runtime configuration for the dashboard settings panel."""
    return {
        "environment": settings.environment,
        "auto_remediation_enabled": settings.auto_remediation_enabled,
        "teams_webhook_configured": bool(settings.teams_webhook_url),
        "slack_webhook_configured": bool(settings.slack_webhook_url),
        "llm_enabled": llm.available,
        "llm_provider": settings.llm.provider if llm.available else "offline",
        "sla_breach_threshold_seconds": settings.sla_breach_threshold_seconds,
    }


@app.get("/api/incident")
async def get_current_incident():
    """Current active incident snapshot (dashboard polls this)."""
    return CURRENT_INCIDENT_STATE


@app.get("/api/incident/history")
async def get_incident_history(limit: int = 50):
    history = CURRENT_INCIDENT_STATE.get("incident_history", [])
    return {"incidents": history[-limit:], "total": len(history)}


@app.post("/api/incident/resolve", dependencies=[Depends(require_api_key)])
async def resolve_incident():
    """Mark the active incident resolved and archive it to history."""
    global CURRENT_INCIDENT_STATE
    if CURRENT_INCIDENT_STATE["active"] and CURRENT_INCIDENT_STATE["data"]:
        CURRENT_INCIDENT_STATE["incident_history"].append({
            "resolved_at": _now(),
            **CURRENT_INCIDENT_STATE["data"],
            "logs": CURRENT_INCIDENT_STATE.get("logs", []),
        })
        # Bound in-memory history so a long-running instance can't grow unbounded.
        del CURRENT_INCIDENT_STATE["incident_history"][:-200]
    CURRENT_INCIDENT_STATE = {
        "active": False, "data": None, "logs": [], "escalated": False,
        "incident_history": CURRENT_INCIDENT_STATE.get("incident_history", []),
    }
    logger.info("Incident resolved and archived.")
    return {"status": "resolved"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "LSR Synaptic Response Center",
        "version": "1.1.0",
        "timestamp": _now(),
    }
