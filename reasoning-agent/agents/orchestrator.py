"""
LSR Multi-Agent Orchestrator

Coordinates the workflow across Fabric IQ, Foundry IQ, and Work IQ layers
for intelligent incident response.
"""
import logging
from datetime import datetime
from .analyzer import IncidentAnalyzer
from .executor import IncidentExecutor

logger = logging.getLogger(__name__)

def handle_incident(asset_id: str, alert_message: str, foundry_dir: str = "data/foundry_iq") -> dict:
    """
    Main orchestration function: routes alert through multi-agent pipeline.
    
    Args:
        asset_id: Infrastructure asset identifier (e.g., 'db_5', 'gateway_2')
        alert_message: Human-readable alert message from monitoring system
        foundry_dir: Path to Foundry IQ knowledge base directory
    
    Returns:
        dict: Result containing incident assessment and action recommendations
    """
    
    logger.info(f"🎯 Orchestrating incident for asset: {asset_id}")
    audit_logs = []
    
    # ================================================================
    # FOUNDRY IQ: Analyze alert and retrieve runbook
    # ================================================================
    audit_logs.append(f"📡 [ORCHESTRATOR] Processing alert: '{alert_message}'")
    
    analyzer = IncidentAnalyzer(foundry_dir)
    resolved_runbook = analyzer.evaluate_remediation_strategy(
        asset_id,
        alert_message,
        audit_logs
    )
    
    logger.info(f"✓ Runbook resolved: {resolved_runbook}")
    
    # ================================================================
    # Action execution (low-risk incidents only)
    # ================================================================
    execution_status = "PENDING"
    
    if "NONE" not in resolved_runbook and "RUNBOOK_REF" in resolved_runbook:
        executor = IncidentExecutor()
        if executor.execute_remediation(resolved_runbook, audit_logs):
            execution_status = "SUCCESS"
            logger.info(f"✓ Remediation executed successfully for {asset_id}")
        else:
            execution_status = "FAILED"
            logger.warning(f"⚠ Remediation execution failed for {asset_id}")
    else:
        execution_status = "MANUAL_REVIEW_REQUIRED"
        audit_logs.append("🛡️ [ORCHESTRATOR] No validated runbook found. Escalating to human review.")
    
    # ================================================================
    # Return incident assessment
    # ================================================================
    result = {
        "timestamp": datetime.now().isoformat(),
        "asset_id": asset_id,
        "alert_message": alert_message,
        "resolved_runbook": resolved_runbook,
        "execution_status": execution_status,
        "audit_logs": audit_logs
    }
    
    logger.info(f"✓ Incident orchestration complete: {result}")
    return result
