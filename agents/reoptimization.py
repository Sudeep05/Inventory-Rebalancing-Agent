"""
Re-Optimization Agent (Loop Pattern)
=====================================
Sub-Agent 8: Manages the iterative re-optimization loop.
After each round of accepted decisions, checks if further
optimization is needed and triggers re-runs until:
  - No more shortages remain, OR
  - Maximum iterations reached, OR
  - Planner stops the loop

This implements the LOOP orchestration pattern.
"""

import os
import sys
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, AgentState

logger = get_logger("reoptimization")


def should_reoptimize(state: AgentState, memory_result: Dict) -> bool:
    """
    Determine if another optimization round is needed.
    
    Conditions to continue:
    1. Memory agent says there are remaining shortages
    2. We haven't hit max iterations
    3. Last optimization produced meaningful transfers
    """
    if state.iteration >= state.max_iterations:
        logger.info(f"Max iterations ({state.max_iterations}) reached. Stopping loop.")
        return False

    if not memory_result.get("should_continue_loop", False):
        logger.info("Memory agent says no more shortages. Stopping loop.")
        return False

    # Check if last optimization actually made progress
    last_opt = state.optimization_result
    if last_opt and not last_opt.get("transfers"):
        logger.info("Last optimization produced no transfers. Stopping loop.")
        return False

    return True


def run_reoptimization_agent(
    state: AgentState,
    memory_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Main entry point for the Re-Optimization Agent.
    
    Decides whether to trigger another optimization loop and
    increments the iteration counter.
    
    Args:
        state: Shared pipeline state
        memory_result: Output from Memory Agent
    
    Returns:
        Loop decision with reason and iteration info.
    """
    logger.info("=" * 60)
    logger.info(f"RE-OPTIMIZATION AGENT — Iteration {state.iteration}")
    logger.info("=" * 60)

    state.add_trace("ReOptimizationAgent", "loop_check", {
        "iteration": state.iteration,
        "remaining_shortages": memory_result.get("remaining_imbalances", {}).get("remaining_count", 0),
    })

    reoptimize = should_reoptimize(state, memory_result)

    if reoptimize:
        state.iteration += 1
        result = {
            "status": "CONTINUE",
            "message": f"Re-optimization triggered. Starting iteration {state.iteration}.",
            "iteration": state.iteration,
            "remaining_shortages": memory_result.get("remaining_imbalances", {}).get("details", []),
        }
        state.status = "reoptimizing"
        logger.info(f"LOOP CONTINUE → Iteration {state.iteration}")
    else:
        reason = []
        if state.iteration >= state.max_iterations:
            reason.append("max iterations reached")
        if not memory_result.get("should_continue_loop"):
            reason.append("no remaining shortages")

        result = {
            "status": "STOP",
            "message": f"Loop terminated after {state.iteration} iteration(s). Reason: {', '.join(reason)}.",
            "iteration": state.iteration,
            "total_accepted_transfers": len(state.accepted_transfers),
        }
        state.status = "loop_complete"
        logger.info(f"LOOP STOP → {', '.join(reason)}")

    state.add_trace("ReOptimizationAgent", f"loop_{result['status'].lower()}", {
        "iteration": state.iteration,
        "reason": result["message"],
    })

    logger.info("=" * 60)
    return result
