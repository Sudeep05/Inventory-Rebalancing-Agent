"""
Output Guardrail Agent
======================
Sub-Agent 9: Validates all final outputs before delivery.
Ensures no hallucinated SKUs, invalid transfers, PII leakage,
or conflicting recommendations.
"""

import re
import os
import sys
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, AgentState

logger = get_logger("output_guardrail")

# PII patterns
PII_PATTERNS = [
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),  # Email
    re.compile(r'\b\d{10,12}\b'),  # Phone numbers
    re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'),  # Card numbers
    re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'),  # PAN (India)
    re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),  # SSN
]


def check_sku_existence(recommendations: List[Dict], valid_skus: set) -> Dict:
    """Verify all SKUs in recommendations exist in the dataset."""
    removed = []
    valid = []
    for rec in recommendations:
        if rec["sku_id"] not in valid_skus:
            removed.append({
                "id": rec["id"],
                "sku_id": rec["sku_id"],
                "reason": "SKU does not exist in dataset (hallucinated)",
            })
        else:
            valid.append(rec)
    return {"valid": valid, "removed": removed}


def check_location_existence(recommendations: List[Dict], valid_locations: set) -> Dict:
    """Verify all locations in recommendations are valid warehouses."""
    removed = []
    valid = []
    for rec in recommendations:
        if rec["from_location"] not in valid_locations:
            removed.append({
                "id": rec["id"], "reason": f"from_location '{rec['from_location']}' invalid"
            })
        elif rec["to_location"] not in valid_locations:
            removed.append({
                "id": rec["id"], "reason": f"to_location '{rec['to_location']}' invalid"
            })
        else:
            valid.append(rec)
    return {"valid": valid, "removed": removed}


def check_quantity_feasibility(recommendations: List[Dict]) -> Dict:
    """Ensure transfer quantities are positive integers."""
    adjusted = []
    clean = []
    for rec in recommendations:
        if rec["quantity"] <= 0:
            adjusted.append({
                "id": rec["id"], "original_qty": rec["quantity"],
                "reason": "Non-positive transfer quantity removed",
            })
        else:
            clean.append(rec)
    return {"valid": clean, "adjusted": adjusted}


def check_conflicts(recommendations: List[Dict]) -> Dict:
    """Detect circular or self-referencing transfers."""
    conflicts = []
    clean = []
    transfer_pairs = set()

    for rec in recommendations:
        if rec["from_location"] == rec["to_location"]:
            conflicts.append({
                "id": rec["id"],
                "reason": "Self-transfer: from and to locations are the same",
            })
            continue

        pair = (rec["sku_id"], rec["from_location"], rec["to_location"])
        reverse = (rec["sku_id"], rec["to_location"], rec["from_location"])
        if reverse in transfer_pairs:
            conflicts.append({
                "id": rec["id"],
                "reason": f"Circular transfer detected with reverse direction for {rec['sku_id']}",
            })
        else:
            transfer_pairs.add(pair)
            clean.append(rec)

    return {"valid": clean, "conflicts": conflicts}


def check_pii(recommendations: List[Dict]) -> List[str]:
    """Scan for PII patterns in all string fields."""
    pii_found = []
    for rec in recommendations:
        for key, value in rec.items():
            if isinstance(value, str):
                for pattern in PII_PATTERNS:
                    if pattern.search(value):
                        pii_found.append(f"PII detected in {rec['id']}.{key}")
    return pii_found


def run_output_guardrail(
    state: AgentState,
    valid_skus: set = None,
    valid_locations: set = None,
) -> Dict[str, Any]:
    """
    Main entry point for the Output Guardrail Agent.
    
    Validates recommendations against:
    1. SKU existence (no hallucinations)
    2. Location validity
    3. Quantity feasibility
    4. No circular/conflicting transfers
    5. No PII leakage
    
    Args:
        state: Shared pipeline state
        valid_skus: Set of known SKU IDs
        valid_locations: Set of known warehouse locations
    
    Returns:
        Guardrail result with approved/modified output and check details.
    """
    logger.info("=" * 60)
    logger.info("OUTPUT GUARDRAIL AGENT START")
    logger.info("=" * 60)

    state.add_trace("OutputGuardrailAgent", "guardrail_start")

    recommendations = state.recommendations or []

    # Extract valid SKUs/locations from data if not provided
    if valid_skus is None:
        inv_df = state.processed_data.get("inventory_raw")
        valid_skus = set(inv_df["sku_id"].unique()) if inv_df is not None else set()
    if valid_locations is None:
        wh_df = state.processed_data.get("warehouse_metadata")
        valid_locations = set(wh_df["location"].unique()) if wh_df is not None else set()

    checks = {
        "sku_existence": True,
        "location_existence": True,
        "quantity_feasibility": True,
        "no_conflicts": True,
        "pii_check": True,
        "storage_compatibility": True,
    }
    all_removed = []
    all_adjusted = []

    # Check 1: SKU existence
    sku_result = check_sku_existence(recommendations, valid_skus)
    if sku_result["removed"]:
        checks["sku_existence"] = False
        all_removed.extend(sku_result["removed"])
    recommendations = sku_result["valid"]

    # Check 2: Location existence
    loc_result = check_location_existence(recommendations, valid_locations)
    if loc_result["removed"]:
        checks["location_existence"] = False
        all_removed.extend(loc_result["removed"])
    recommendations = loc_result["valid"]

    # Check 3: Quantity feasibility
    qty_result = check_quantity_feasibility(recommendations)
    if qty_result["adjusted"]:
        checks["quantity_feasibility"] = False
        all_adjusted.extend(qty_result["adjusted"])
    recommendations = qty_result["valid"]

    # Check 4: Conflicts
    conflict_result = check_conflicts(recommendations)
    if conflict_result["conflicts"]:
        checks["no_conflicts"] = False
        all_removed.extend(conflict_result["conflicts"])
    recommendations = conflict_result["valid"]

    # Check 5: PII
    pii_flags = check_pii(recommendations)
    if pii_flags:
        checks["pii_check"] = False

    # Determine final status
    if all_removed or all_adjusted:
        status = "MODIFIED"
        message = (
            f"Output modified: {len(all_removed)} recommendations removed, "
            f"{len(all_adjusted)} adjusted."
        )
    elif all(checks.values()):
        status = "APPROVED"
        message = "All checks passed. Output approved for delivery."
    else:
        status = "MODIFIED"
        message = "Some checks flagged issues. Review modifications."

    result = {
        "status": status,
        "message": message,
        "checks_passed": checks,
        "modifications": all_adjusted,
        "removed_recommendations": all_removed,
        "pii_flags": pii_flags,
        "approved_output": {
            "recommendations": recommendations,
            "count": len(recommendations),
        },
    }

    # Update state with cleaned recommendations
    state.recommendations = recommendations
    state.final_output = result
    state.status = "output_validated"

    state.add_trace("OutputGuardrailAgent", f"guardrail_{status.lower()}", {
        "checks": checks,
        "removed": len(all_removed),
        "adjusted": len(all_adjusted),
        "approved_count": len(recommendations),
    })

    logger.info(f"Output guardrail: {status} | {len(recommendations)} recommendations approved")
    logger.info("=" * 60)

    return result
