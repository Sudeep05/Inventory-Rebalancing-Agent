"""
Inventory Intelligence Agent
=============================
Sub-Agent 3: Analyzes processed data to identify excess inventory,
shortages, expiry risks, and storage mismatches across all
SKU-location combinations.

This agent is selected for Sub-Agent Evaluation (Precision/Recall/F1).
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, List
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, AgentState, gemini, load_prompt

logger = get_logger("inventory_intelligence")

# Threshold: if gap < BALANCE_THRESHOLD % of demand, consider balanced
BALANCE_THRESHOLD_PCT = 0.05

# Load the prompt template for LLM-based analysis
_INTELLIGENCE_PROMPT = load_prompt("inventory_intelligence")


def classify_imbalances(merged_df: pd.DataFrame) -> List[Dict]:
    """
    Classify each SKU-location pair as EXCESS, SHORTAGE, BALANCED, or STORAGE_MISMATCH.
    
    Logic:
        Net Demand = Total Forecast Demand - Total Planned Production
        If Inventory > Net Demand → EXCESS (gap = Inventory - Net Demand)
        If Net Demand > Inventory → SHORTAGE (gap = Net Demand - Inventory)
        If approximately equal    → BALANCED
        If storage incompatible   → STORAGE_MISMATCH (must transfer)
    
    Returns:
        List of imbalance dictionaries with status, gap, and severity.
    """
    imbalances = []

    for _, row in merged_df.iterrows():
        sku = row["sku_id"]
        loc = row["location"]
        inventory = int(row["total_inventory"])
        net_demand = int(row["net_demand"])
        gap = inventory - net_demand
        storage_compatible = row.get("storage_compatible", True)
        storage_type = row.get("storage_type", "dry")
        days_to_expiry = int(row.get("days_to_expiry", 999))

        # Determine expiry priority
        if days_to_expiry <= 7:
            expiry_priority = "CRITICAL"
        elif days_to_expiry <= 14:
            expiry_priority = "HIGH"
        elif days_to_expiry <= 30:
            expiry_priority = "MEDIUM"
        else:
            expiry_priority = "LOW"

        # Storage mismatch takes top priority
        if not storage_compatible:
            imbalances.append({
                "sku_id": sku,
                "location": loc,
                "status": "STORAGE_MISMATCH",
                "total_inventory": inventory,
                "net_demand": net_demand,
                "gap": abs(gap),
                "severity": "CRITICAL",
                "expiry_priority": expiry_priority,
                "days_to_expiry": days_to_expiry,
                "storage_type": storage_type,
                "storage_compatible": False,
                "flag": "MUST_TRANSFER",
            })
        elif gap > 0:
            # EXCESS: more inventory than needed
            threshold = max(net_demand * BALANCE_THRESHOLD_PCT, 10)
            if gap <= threshold:
                status = "BALANCED"
                severity = "NONE"
            else:
                status = "EXCESS"
                if gap > 2000:
                    severity = "HIGH"
                elif gap > 500:
                    severity = "MEDIUM"
                else:
                    severity = "LOW"

            imbalances.append({
                "sku_id": sku,
                "location": loc,
                "status": status,
                "total_inventory": inventory,
                "net_demand": net_demand,
                "gap": gap,
                "severity": severity,
                "expiry_priority": expiry_priority,
                "days_to_expiry": days_to_expiry,
                "storage_type": storage_type,
                "storage_compatible": True,
            })
        elif gap < 0:
            # SHORTAGE: demand exceeds inventory
            shortage = abs(gap)
            if inventory == 0 or shortage > 1000:
                severity = "CRITICAL"
            elif shortage > 500:
                severity = "HIGH"
            elif shortage > 100:
                severity = "MEDIUM"
            else:
                severity = "LOW"

            imbalances.append({
                "sku_id": sku,
                "location": loc,
                "status": "SHORTAGE",
                "total_inventory": inventory,
                "net_demand": net_demand,
                "gap": -shortage,  # Negative indicates shortage
                "severity": severity,
                "expiry_priority": expiry_priority,
                "days_to_expiry": days_to_expiry,
                "storage_type": storage_type,
                "storage_compatible": True,
            })
        else:
            # Perfectly balanced
            imbalances.append({
                "sku_id": sku,
                "location": loc,
                "status": "BALANCED",
                "total_inventory": inventory,
                "net_demand": net_demand,
                "gap": 0,
                "severity": "NONE",
                "expiry_priority": expiry_priority,
                "days_to_expiry": days_to_expiry,
                "storage_type": storage_type,
                "storage_compatible": True,
            })

    return imbalances


def get_expiry_alerts(merged_df: pd.DataFrame) -> List[Dict]:
    """Identify lots with critical or high expiry urgency."""
    alerts = []
    for _, row in merged_df.iterrows():
        days = int(row.get("days_to_expiry", 999))
        if days <= 14:
            alerts.append({
                "sku_id": row["sku_id"],
                "location": row["location"],
                "days_to_expiry": days,
                "quantity": int(row["total_inventory"]),
                "priority": "CRITICAL" if days <= 7 else "HIGH",
                "storage_type": row.get("storage_type", "unknown"),
            })
    return sorted(alerts, key=lambda x: x["days_to_expiry"])


def get_storage_mismatches(merged_df: pd.DataFrame) -> List[Dict]:
    """Identify SKUs stored in incompatible warehouse types."""
    mismatches = []
    for _, row in merged_df.iterrows():
        if not row.get("storage_compatible", True):
            mismatches.append({
                "sku_id": row["sku_id"],
                "location": row["location"],
                "sku_storage_type": row.get("storage_type", "unknown"),
                "warehouse_supports": row.get("storage_types_supported", "unknown"),
                "quantity": int(row["total_inventory"]),
            })
    return mismatches


def run_inventory_intelligence(state: AgentState) -> Dict[str, Any]:
    """
    Main entry point for the Inventory Intelligence Agent.
    
    Takes processed merged data and produces:
    - Classification of all SKU-location pairs (excess/shortage/balanced/mismatch)
    - Expiry alerts for urgent lots
    - Storage mismatch flags
    - Summary statistics
    
    Args:
        state: Shared pipeline state (expects processed_data to be populated)
    
    Returns:
        Intelligence output with imbalances, alerts, and summary.
    """
    logger.info("=" * 60)
    logger.info("INVENTORY INTELLIGENCE AGENT START")
    logger.info("=" * 60)

    state.add_trace("InventoryIntelligenceAgent", "analysis_start")

    merged_df = state.processed_data.get("merged_data")
    if merged_df is None or merged_df.empty:
        error_msg = "No processed data available for analysis"
        state.add_error("InventoryIntelligenceAgent", error_msg)
        state.status = "intelligence_failed"
        return {"status": "FAIL", "error": error_msg}

    # ── Run analysis ──
    imbalances = classify_imbalances(merged_df)
    expiry_alerts = get_expiry_alerts(merged_df)
    storage_mismatches = get_storage_mismatches(merged_df)

    # ── Compute summary ──
    status_counts = {}
    severity_counts = {}
    for item in imbalances:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
        if item["severity"] != "NONE":
            severity_counts[item["severity"]] = severity_counts.get(item["severity"], 0) + 1

    summary = {
        "total_sku_location_pairs": len(imbalances),
        "excess_count": status_counts.get("EXCESS", 0),
        "shortage_count": status_counts.get("SHORTAGE", 0),
        "balanced_count": status_counts.get("BALANCED", 0),
        "storage_mismatches": status_counts.get("STORAGE_MISMATCH", 0),
        "critical_expiry_lots": len([a for a in expiry_alerts if a["priority"] == "CRITICAL"]),
        "severity_breakdown": severity_counts,
    }

    result = {
        "status": "SUCCESS",
        "summary": summary,
        "imbalances": imbalances,
        "expiry_alerts": expiry_alerts,
        "storage_mismatches": storage_mismatches,
    }

    # ── LLM Enhancement: Generate natural language analysis ──
    if gemini.is_available:
        try:
            top_shortages = sorted([i for i in imbalances if i["status"] == "SHORTAGE"], key=lambda x: x["gap"])[:5]
            top_excess = sorted([i for i in imbalances if i["status"] == "EXCESS"], key=lambda x: -x["gap"])[:5]
            shortage_lines = "\n".join(f"  - {s['sku_id']} at {s['location']}: shortage={abs(s['gap'])} units, severity={s['severity']}" for s in top_shortages)
            excess_lines = "\n".join(f"  - {e['sku_id']} at {e['location']}: excess={e['gap']} units, severity={e['severity']}" for e in top_excess)

            llm_prompt = (
                f"You are an inventory intelligence analyst. Summarize these findings in 3-4 sentences "
                f"for a supply chain planner. Be specific about which SKUs and locations need urgent attention.\n\n"
                f"Network: 5 warehouses (Mumbai, Pune, Delhi, Bangalore, Chennai), 15 SKUs\n"
                f"Overall: {summary['excess_count']} excess, {summary['shortage_count']} shortage, "
                f"{summary['storage_mismatches']} storage mismatches, {summary['critical_expiry_lots']} critical expiry\n\n"
                f"Top Shortages:\n{shortage_lines}\n\nTop Excess:\n{excess_lines}\n\n"
                f"Respond with ONLY the summary paragraph, no headings or bullet points."
            )
            llm_summary = gemini.generate(llm_prompt, system_prompt=_INTELLIGENCE_PROMPT, max_tokens=300)
            if llm_summary:
                result["llm_analysis"] = llm_summary
                logger.info(f"LLM analysis generated ({len(llm_summary)} chars)")
        except Exception as e:
            logger.debug(f"LLM analysis skipped: {e}")
    else:
        logger.debug("LLM not available for intelligence summary")

    # Store in state
    state.intelligence_output = result
    state.status = "intelligence_complete"

    state.add_trace("InventoryIntelligenceAgent", "analysis_complete", {
        "excess": summary["excess_count"],
        "shortage": summary["shortage_count"],
        "balanced": summary["balanced_count"],
        "mismatches": summary["storage_mismatches"],
        "critical_expiry": summary["critical_expiry_lots"],
    })

    logger.info(f"Intelligence complete: {summary}")
    logger.info("=" * 60)

    return result
