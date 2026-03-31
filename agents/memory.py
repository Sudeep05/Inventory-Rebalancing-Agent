"""
Memory Agent
============
Sub-Agent 7: Maintains state across iterations. Stores accepted decisions,
updates inventory positions, and prevents duplicate or conflicting transfers.
Critical for the iterative re-optimization loop pattern.
"""

import os
import sys
from typing import Dict, Any, List
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, AgentState

logger = get_logger("memory_agent")


def record_accepted_transfers(state: AgentState, accepted: List[Dict]) -> Dict[str, Any]:
    """
    Record transfers accepted by the human-in-the-loop or auto-approved.
    Updates the inventory state to reflect accepted moves.
    
    Args:
        state: Shared pipeline state
        accepted: List of accepted recommendation dicts
    
    Returns:
        Updated memory state summary.
    """
    new_count = 0
    duplicate_count = 0

    for transfer in accepted:
        # Check for duplicates
        is_dup = any(
            t["sku_id"] == transfer["sku_id"]
            and t["from_location"] == transfer["from_location"]
            and t["to_location"] == transfer["to_location"]
            for t in state.accepted_transfers
        )

        if is_dup:
            duplicate_count += 1
            logger.warning(
                f"Duplicate transfer skipped: {transfer['sku_id']} "
                f"{transfer['from_location']}→{transfer['to_location']}"
            )
            continue

        state.accepted_transfers.append({
            "sku_id": transfer["sku_id"],
            "from_location": transfer["from_location"],
            "to_location": transfer["to_location"],
            "quantity": transfer["quantity"],
            "iteration": state.iteration,
        })
        new_count += 1

    return {
        "new_accepted": new_count,
        "duplicates_skipped": duplicate_count,
        "total_accepted": len(state.accepted_transfers),
    }


def check_remaining_imbalances(state: AgentState) -> Dict[str, Any]:
    """
    Check if there are still unresolved shortages after accepted transfers.
    Used to decide whether to loop (re-optimize) or exit.
    
    Returns:
        Dict with has_remaining_shortages flag and details.
    """
    intelligence = state.intelligence_output
    if not intelligence:
        return {"has_remaining_shortages": False, "reason": "No intelligence data"}

    imbalances = intelligence.get("imbalances", [])
    remaining_shortages = []

    for item in imbalances:
        if item["status"] != "SHORTAGE":
            continue

        sku = item["sku_id"]
        loc = item["location"]
        original_gap = abs(item["gap"])

        # Subtract accepted transfers to this location for this SKU
        fulfilled = sum(
            t["quantity"] for t in state.accepted_transfers
            if t["sku_id"] == sku and t["to_location"] == loc
        )

        remaining = original_gap - fulfilled
        if remaining > 10:  # Threshold to avoid trivial remainders
            remaining_shortages.append({
                "sku_id": sku,
                "location": loc,
                "original_shortage": original_gap,
                "fulfilled": fulfilled,
                "remaining": remaining,
            })

    return {
        "has_remaining_shortages": len(remaining_shortages) > 0,
        "remaining_count": len(remaining_shortages),
        "details": remaining_shortages,
    }


def run_memory_agent(
    state: AgentState,
    accepted_recommendations: List[Dict] = None,
) -> Dict[str, Any]:
    """
    Main entry point for the Memory Agent.
    
    Records decisions and determines if re-optimization is needed.
    
    Args:
        state: Shared pipeline state
        accepted_recommendations: List of recommendations accepted by human/auto
    
    Returns:
        Memory update result with loop decision.
    """
    logger.info("=" * 60)
    logger.info("MEMORY AGENT START")
    logger.info("=" * 60)

    state.add_trace("MemoryAgent", "memory_update_start", {
        "iteration": state.iteration,
        "incoming_accepts": len(accepted_recommendations) if accepted_recommendations else 0,
    })

    # Record accepted transfers
    if accepted_recommendations:
        record_result = record_accepted_transfers(state, accepted_recommendations)
    else:
        record_result = {"new_accepted": 0, "duplicates_skipped": 0,
                         "total_accepted": len(state.accepted_transfers)}

    # Check remaining imbalances
    remaining = check_remaining_imbalances(state)

    # Loop decision
    should_continue = (
        remaining["has_remaining_shortages"]
        and state.iteration < state.max_iterations
    )

    result = {
        "status": "SUCCESS",
        "record_result": record_result,
        "remaining_imbalances": remaining,
        "should_continue_loop": should_continue,
        "iteration": state.iteration,
        "reason": (
            "Remaining shortages found, re-optimization recommended"
            if should_continue
            else "All shortages resolved or max iterations reached"
        ),
    }

    state.add_trace("MemoryAgent", "memory_update_complete", {
        "accepted": record_result["total_accepted"],
        "remaining_shortages": remaining["remaining_count"],
        "should_loop": should_continue,
    })

    logger.info(f"Memory update: {record_result['total_accepted']} total accepted transfers")
    logger.info(f"Loop decision: {'CONTINUE' if should_continue else 'STOP'}")
    logger.info("=" * 60)

    return result
