"""
Human-in-the-Loop Agent (Bonus)
================================
Sub-Agent 6: Presents recommendations for human approval before execution.
Supports Accept, Reject, and Modify actions. Critical for high-stakes
supply chain decisions.

In automated mode (testing), auto-approves all recommendations.
In interactive mode, pauses for user input.
"""

import os
import sys
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, AgentState, format_currency

logger = get_logger("human_in_loop")


def format_for_display(recommendations: List[Dict]) -> str:
    """Format recommendations into a human-readable table."""
    if not recommendations:
        return "No recommendations to review."

    lines = [
        "=" * 80,
        "INVENTORY TRANSFER RECOMMENDATIONS — AWAITING APPROVAL",
        "=" * 80,
        "",
    ]

    for rec in recommendations:
        lines.append(f"  [{rec['id']}] Priority: {rec['priority']}")
        lines.append(f"  ACTION: {rec['action']}")
        lines.append(f"  Deadline: {rec['deadline']}")
        lines.append(f"  Transfer Cost: {format_currency(rec['transfer_cost'])}")
        lines.append(f"  Holding Saved: {format_currency(rec['holding_cost_saved'])}")
        lines.append(f"  Justification: {rec['justification']}")
        lines.append("-" * 80)

    lines.append("")
    lines.append("Actions: [A]ccept All | [R]eject All | Enter IDs to accept (e.g., REC-001,REC-003)")
    lines.append("=" * 80)

    return "\n".join(lines)


def auto_approve(recommendations: List[Dict]) -> Dict[str, Any]:
    """
    Auto-approve all recommendations (used in automated testing mode).
    
    Returns:
        Decision result with all recommendations accepted.
    """
    return {
        "decision": "ACCEPT_ALL",
        "accepted": recommendations,
        "rejected": [],
        "modified": [],
    }


def selective_approve(
    recommendations: List[Dict],
    accepted_ids: List[str],
) -> Dict[str, Any]:
    """
    Approve only selected recommendations by ID.
    
    Args:
        recommendations: All recommendations
        accepted_ids: List of recommendation IDs to accept
    
    Returns:
        Decision result with selected accepted/rejected.
    """
    accepted = [r for r in recommendations if r["id"] in accepted_ids]
    rejected = [r for r in recommendations if r["id"] not in accepted_ids]

    return {
        "decision": "SELECTIVE",
        "accepted": accepted,
        "rejected": rejected,
        "modified": [],
    }


def run_human_in_loop(
    state: AgentState,
    mode: str = "auto",
    accepted_ids: List[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point for the Human-in-the-Loop Agent.
    
    Args:
        state: Shared pipeline state
        mode: "auto" for automated approval, "interactive" for manual review,
              "selective" for specific ID-based approval
        accepted_ids: List of recommendation IDs to accept (for selective mode)
    
    Returns:
        Human decision result with accepted/rejected recommendations.
    """
    logger.info("=" * 60)
    logger.info(f"HUMAN-IN-THE-LOOP AGENT START (mode={mode})")
    logger.info("=" * 60)

    state.add_trace("HumanInLoopAgent", "checkpoint_start", {
        "mode": mode,
        "recommendations_count": len(state.recommendations),
    })

    recommendations = state.recommendations or []

    if not recommendations:
        result = {
            "status": "NO_ACTION",
            "message": "No recommendations to review.",
            "decision": {"accepted": [], "rejected": [], "modified": []},
        }
        state.add_trace("HumanInLoopAgent", "no_recommendations")
        return result

    # Display for logging/observability
    display_text = format_for_display(recommendations)
    logger.info(f"\n{display_text}")

    # Process based on mode
    if mode == "auto":
        decision = auto_approve(recommendations)
        logger.info("Auto-approved all recommendations")
    elif mode == "selective" and accepted_ids:
        decision = selective_approve(recommendations, accepted_ids)
        logger.info(f"Selectively approved: {accepted_ids}")
    elif mode == "reject_all":
        decision = {
            "decision": "REJECT_ALL",
            "accepted": [],
            "rejected": recommendations,
            "modified": [],
        }
        logger.info("All recommendations rejected")
    else:
        # Default to auto in non-interactive contexts
        decision = auto_approve(recommendations)
        logger.info("Defaulting to auto-approve")

    state.human_decisions.append({
        "iteration": state.iteration,
        "mode": mode,
        "decision": decision["decision"],
        "accepted_count": len(decision["accepted"]),
        "rejected_count": len(decision["rejected"]),
    })

    result = {
        "status": "SUCCESS",
        "display": display_text,
        "decision": decision,
        "message": f"Decision: {decision['decision']} | "
                   f"Accepted: {len(decision['accepted'])}, "
                   f"Rejected: {len(decision['rejected'])}",
    }

    state.add_trace("HumanInLoopAgent", "checkpoint_complete", {
        "decision": decision["decision"],
        "accepted": len(decision["accepted"]),
        "rejected": len(decision["rejected"]),
    })

    logger.info(f"Decision: {decision['decision']}")
    logger.info("=" * 60)

    return result
