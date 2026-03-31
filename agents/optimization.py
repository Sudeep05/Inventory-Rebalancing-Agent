"""
Optimization Agent
==================
Sub-Agent 4: Formulates and solves the multi-objective inventory transfer
optimization problem using the Pyomo/OR-Tools solver tool.

Objective: Minimize a x (Holding + Transfer Cost) - b x (Demand Fulfillment)
"""

import os
import sys
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, AgentState, CONFIG
from tools.optimizer_tool import run_optimization

logger = get_logger("optimization_agent")


def run_optimization_agent(state: AgentState, alpha: float = None, beta: float = None) -> Dict[str, Any]:
    logger.info("=" * 60)
    logger.info("OPTIMIZATION AGENT START")
    logger.info("=" * 60)

    state.add_trace("OptimizationAgent", "optimization_start", {
        "alpha": alpha or CONFIG["optimization"]["alpha"],
        "beta": beta or CONFIG["optimization"]["beta"],
    })

    intelligence_output = state.intelligence_output
    if not intelligence_output or intelligence_output.get("status") != "SUCCESS":
        error_msg = "Intelligence output not available or failed"
        state.add_error("OptimizationAgent", error_msg)
        state.status = "optimization_failed"
        return {"status": "ERROR", "error": error_msg}

    cost_df = state.processed_data.get("cost_data")
    warehouse_df = state.processed_data.get("warehouse_metadata")
    if cost_df is None or warehouse_df is None:
        error_msg = "Cost data or warehouse metadata not available"
        state.add_error("OptimizationAgent", error_msg)
        state.status = "optimization_failed"
        return {"status": "ERROR", "error": error_msg}

    if state.accepted_transfers:
        intelligence_output = _adjust_for_accepted_transfers(intelligence_output, state.accepted_transfers)

    try:
        result = run_optimization(
            intelligence_output=intelligence_output,
            cost_df=cost_df, warehouse_df=warehouse_df,
            alpha=alpha, beta=beta,
        )
        state.optimization_result = result
        state.status = f"optimization_{result['status'].lower()}"

        state.add_trace("OptimizationAgent", f"optimization_{result['status'].lower()}", {
            "transfers_count": len(result.get("transfers", [])),
            "metrics": result.get("metrics", {}),
            "solver_backend": result.get("solver_backend", "unknown"),
        })

        logger.info(f"Optimization complete: {result['status']}")
        if result.get("metrics"):
            logger.info(f"  Total cost: {result['metrics'].get('total_transfer_cost', 0)}")
            logger.info(f"  Fulfillment: {result['metrics'].get('demand_fulfillment_pct', 0)}%")
        logger.info("=" * 60)
        return result

    except Exception as e:
        error_msg = f"Optimization exception: {str(e)}"
        state.add_error("OptimizationAgent", error_msg)
        state.add_trace("OptimizationAgent", "optimization_exception", {"error": str(e)})
        state.status = "optimization_failed"
        logger.exception(error_msg)
        return {"status": "ERROR", "error": error_msg, "transfers": [], "metrics": {}}


def _adjust_for_accepted_transfers(intelligence_output: Dict, accepted_transfers: list) -> Dict:
    adjusted = intelligence_output.copy()
    adjusted_imbalances = []
    for item in adjusted.get("imbalances", []):
        item_copy = item.copy()
        for transfer in accepted_transfers:
            if transfer["sku_id"] == item["sku_id"]:
                if transfer["from_location"] == item["location"] and item["status"] == "EXCESS":
                    item_copy["gap"] = max(0, item_copy["gap"] - transfer["quantity"])
                elif transfer["to_location"] == item["location"] and item["status"] == "SHORTAGE":
                    item_copy["gap"] = max(0, abs(item_copy["gap"]) - transfer["quantity"])
                    item_copy["gap"] = -item_copy["gap"]
        adjusted_imbalances.append(item_copy)
    adjusted["imbalances"] = adjusted_imbalances
    return adjusted
