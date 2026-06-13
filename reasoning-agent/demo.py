"""
LSR Demo: Multi-Agent Incident Response Simulation

Demonstrates the orchestration pipeline:
  1. Infrastructure alerts ingested (Fabric IQ context)
  2. Foundry IQ analyzes and matches runbooks
  3. Work IQ routes to available engineers
  4. Auto-remediation or human escalation triggered
"""
import sys
import time
import logging
from agents.orchestrator import handle_incident

# Ensure emoji/Unicode render on legacy Windows consoles (cp1251/cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def run_demo():
    """Execute demonstration scenarios."""
    
    print("\n" + "="*70)
    print("🚀 LSR INCIDENT RESPONSE DEMO")
    print("="*70 + "\n")
    
    # ====================================================================
    # SCENARIO 1: LOW-RISK INFRASTRUCTURE ALERT
    # Status: AUTO-REMEDIATION (fast, low blast radius)
    # ====================================================================
    print("📌 SCENARIO 1: Low-Risk Alert → Auto-Remediation")
    print("-" * 70)
    print("Description: Edge gateway experiencing packet congestion.\n")
    time.sleep(1)
    
    result_1 = handle_incident(
        asset_id="gateway_2",
        alert_message="High packet congestion detected. Dynamic transit buffer queues are full."
    )
    
    print(f"\n✓ Result: {result_1['execution_status']}")
    print(f"  Runbook: {result_1['resolved_runbook']}")
    
    print("\n" + "="*70 + "\n")
    time.sleep(2)
    
    # ====================================================================
    # SCENARIO 2: HIGH-RISK INFRASTRUCTURE ALERT
    # Status: HUMAN_VALIDATION_REQUIRED (financial impact, SLA-critical)
    # ====================================================================
    print("📌 SCENARIO 2: High-Risk Alert → Requires Human Approval")
    print("-" * 70)
    print("Description: Primary database cluster connection failure.\n")
    time.sleep(1)
    
    result_2 = handle_incident(
        asset_id="db_5",
        alert_message="Socket closed unexpectedly. Connection timeouts detected on primary pool."
    )
    
    print(f"\n✓ Result: {result_2['execution_status']}")
    print(f"  Runbook: {result_2['resolved_runbook']}")
    print("  Note: High criticality triggers Teams notification & human approval gate.\n")
    
    print("="*70)
    print("🏁 DEMO EXECUTION COMPLETED")
    print("="*70 + "\n")
    
    print("📊 Summary:")
    print(f"  • Scenario 1 (Gateway): {result_1['execution_status']}")
    print(f"  • Scenario 2 (Database): {result_2['execution_status']}")
    print("\n✨ Full audit logs available via LSR Dashboard UI.\n")

if __name__ == "__main__":
    run_demo()
