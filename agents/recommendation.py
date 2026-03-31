"""
Recommendation Agent
====================
Sub-Agent 5: Converts optimization solver output into clear, prioritized,
human-readable transfer recommendations for supply chain planners.
"""

import os
import sys
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, AgentState, format_currency, gemini, load_prompt

logger = get_logger("recommendation_agent")

PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Load the prompt template for LLM-based recommendation enrichment
_RECOMMENDATION_PROMPT = load_prompt("recommendation")


def generate_recommendations(optimization_result: Dict[str, Any]) -> List[Dict]:
    """
    Convert optimization transfers into actionable recommendations.
    
    Each recommendation includes:
    - Clear action statement
    - Priority level
    - Deadline
    - Cost and benefit analysis
    - Justification
    """
    transfers = optimization_result.get("transfers", [])
    if not transfers:
        return []

    recommendations = []
    for idx, transfer in enumerate(transfers):
        sku = transfer["sku_id"]
        from_loc = transfer["from_location"]
        to_loc = transfer["to_location"]
        qty = transfer["quantity"]
        cost = transfer.get("transfer_cost", 0)
        holding_saved = transfer.get("holding_cost_saved", 0)
        expiry_priority = transfer.get("expiry_priority", "LOW")

        # Determine priority and deadline
        if expiry_priority == "CRITICAL":
            priority = "CRITICAL"
            deadline = "Within 2 days"
            justification = (
                f"URGENT: Near-expiry inventory. Lot expires soon. "
                f"If not transferred, {format_currency(qty * 75)} in inventory at risk of write-off."
            )
        elif expiry_priority == "HIGH":
            priority = "HIGH"
            deadline = "Within this week"
            justification = (
                f"Expiry approaching within 2 weeks. Transfer avoids potential waste "
                f"and fulfills shortage at {to_loc}."
            )
        elif qty > 500:
            priority = "HIGH"
            deadline = "Before Week 2"
            justification = (
                f"Large shortage at {to_loc} ({qty} units needed). "
                f"Transfer cost: {format_currency(cost)}, holding saved: {format_currency(holding_saved)}."
            )
        else:
            priority = "MEDIUM"
            deadline = "Before Week 3"
            justification = (
                f"Rebalancing opportunity: {from_loc} has excess, {to_loc} has shortage. "
                f"Net cost: {format_currency(cost - holding_saved)}."
            )

        net_benefit = holding_saved - cost
        benefit_text = (
            f"Net saving: {format_currency(net_benefit)}" if net_benefit > 0
            else f"Net cost: {format_currency(abs(net_benefit))}, justified by demand fulfillment"
        )

        recommendations.append({
            "id": f"REC-{str(idx + 1).zfill(3)}",
            "priority": priority,
            "action": f"Transfer {qty} units of {sku} from {from_loc} → {to_loc}",
            "sku_id": sku,
            "from_location": from_loc,
            "to_location": to_loc,
            "quantity": qty,
            "deadline": deadline,
            "transfer_cost": round(cost, 2),
            "holding_cost_saved": round(holding_saved, 2),
            "net_benefit": round(net_benefit, 2),
            "justification": justification,
            "expected_benefit": benefit_text,
            "storage_type": transfer.get("storage_type", "dry"),
        })

    # Sort by priority
    recommendations.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 99))
    return recommendations


def run_recommendation_agent(state: AgentState) -> Dict[str, Any]:
    """
    Main entry point for the Recommendation Agent.
    
    Args:
        state: Shared pipeline state (expects optimization_result)
    
    Returns:
        Recommendation output with prioritized action items and summary.
    """
    logger.info("=" * 60)
    logger.info("RECOMMENDATION AGENT START")
    logger.info("=" * 60)

    state.add_trace("RecommendationAgent", "recommendation_start")

    opt_result = state.optimization_result
    if not opt_result:
        error_msg = "No optimization result available"
        state.add_error("RecommendationAgent", error_msg)
        return {"status": "FAIL", "error": error_msg}

    if opt_result.get("status") in ("INFEASIBLE", "ERROR"):
        state.add_trace("RecommendationAgent", "no_feasible_solution")
        return {
            "status": "NO_ACTION",
            "message": "Optimization found no feasible solution. " + opt_result.get("message", ""),
            "recommendations": [],
            "summary": {},
        }

    # Generate recommendations
    recommendations = generate_recommendations(opt_result)

    if not recommendations:
        result = {
            "status": "NO_ACTION",
            "message": "All SKU-location pairs are within acceptable balance. No transfers needed.",
            "recommendations": [],
            "summary": {"total_recommendations": 0},
        }
    else:
        # Build summary
        priority_counts = {}
        for rec in recommendations:
            priority_counts[rec["priority"]] = priority_counts.get(rec["priority"], 0) + 1

        metrics = opt_result.get("metrics", {})
        result = {
            "status": "SUCCESS",
            "summary": {
                "total_recommendations": len(recommendations),
                "critical_count": priority_counts.get("CRITICAL", 0),
                "high_count": priority_counts.get("HIGH", 0),
                "medium_count": priority_counts.get("MEDIUM", 0),
                "low_count": priority_counts.get("LOW", 0),
                "total_transfer_cost": metrics.get("total_transfer_cost", 0),
                "total_holding_saved": metrics.get("total_holding_saved", 0),
                "demand_fulfillment_pct": metrics.get("demand_fulfillment_pct", 0),
            },
            "recommendations": recommendations,
        }

    state.recommendations = recommendations
    state.status = "recommendations_ready"

    # ── LLM Enhancement: Enrich top recommendations with natural language ──
    if gemini.is_available and recommendations:
        try:
            top_recs = recommendations[:5]  # Enrich top 5 only (API cost management)
            recs_text = "\n".join(
                f"- {r['id']}: Transfer {r['quantity']} units of {r['sku_id']} "
                f"from {r['from_location']} to {r['to_location']}, "
                f"cost={format_currency(r['transfer_cost'])}, saved={format_currency(r['holding_cost_saved'])}, "
                f"priority={r['priority']}"
                for r in top_recs
            )
            llm_prompt = (
                f"You are a supply chain advisor. For each of these transfer recommendations, "
                f"write a brief 1-sentence business justification that a warehouse planner would find useful. "
                f"Focus on why this specific transfer matters (cost saving, expiry risk, demand fulfillment).\n\n"
                f"Recommendations:\n{recs_text}\n\n"
                f"Respond with one line per recommendation in format: REC-XXX: [justification]"
            )
            llm_response = gemini.generate(llm_prompt, system_prompt=_RECOMMENDATION_PROMPT, max_tokens=500)
            if llm_response:
                # Parse LLM justifications and merge into recommendations
                for line in llm_response.strip().split("\n"):
                    line = line.strip()
                    if ":" in line and line.startswith("REC-"):
                        rec_id = line.split(":")[0].strip()
                        llm_justification = ":".join(line.split(":")[1:]).strip()
                        for rec in recommendations:
                            if rec["id"] == rec_id:
                                rec["llm_justification"] = llm_justification
                                break
                logger.info(f"LLM enriched {len(top_recs)} recommendations")
        except Exception as e:
            logger.debug(f"LLM enrichment skipped: {e}")
    else:
        if not gemini.is_available:
            logger.debug("LLM not available for recommendation enrichment")

    state.add_trace("RecommendationAgent", "recommendations_complete", {
        "count": len(recommendations),
        "priorities": {r["priority"] for r in recommendations} if recommendations else set(),
    })

    logger.info(f"Generated {len(recommendations)} recommendations")
    logger.info("=" * 60)

    return result
