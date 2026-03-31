"""
Optimization Solver Tool (Pyomo + SciPy)
=========================================
Tool Integration #2: Uses Pyomo for multi-objective inventory transfer optimization.
Falls back to SciPy's linprog when no LP solver (GLPK/CBC) is installed.

Objective: Minimize α×(Holding + Transfer Cost) − β×(Demand Fulfillment)
Constraints: Supply, demand, capacity, storage compatibility, expiry priority.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, CONFIG

logger = get_logger("optimizer_tool")

# Always import scipy as fallback
from scipy.optimize import linprog

# Try importing Pyomo
PYOMO_AVAILABLE = False
try:
    from pyomo.environ import (
        ConcreteModel, Var, Objective, Constraint, SolverFactory,
        NonNegativeIntegers, minimize, value, TerminationCondition
    )
    PYOMO_AVAILABLE = True
    logger.info("Pyomo loaded successfully")
except ImportError:
    logger.warning("Pyomo not available, will use scipy-only solver")


def build_transfer_candidates(
    intelligence_output: Dict[str, Any],
    cost_df: pd.DataFrame,
    warehouse_df: pd.DataFrame,
) -> List[Dict]:
    """
    Build the list of valid (SKU, from, to) transfer candidates.
    
    Rules:
        - Only transfer FROM locations with excess
        - Only transfer TO locations with shortage
        - Must satisfy storage compatibility
        - Must not exceed warehouse capacity headroom
    
    Returns:
        List of candidate dictionaries with bounds and costs.
    """
    excess_items = [
        item for item in intelligence_output.get("imbalances", [])
        if item["status"] == "EXCESS"
    ]
    shortage_items = [
        item for item in intelligence_output.get("imbalances", [])
        if item["status"] == "SHORTAGE"
    ]

    # Build warehouse storage lookup
    wh_storage = {}
    wh_capacity = {}
    for _, row in warehouse_df.iterrows():
        wh_storage[row["location"]] = str(row["storage_types_supported"]).split(",")
        wh_capacity[row["location"]] = row.get("max_capacity", 99999) * (
            1 - row.get("current_utilization_pct", 0) / 100
        )

    candidates = []
    for excess in excess_items:
        for shortage in shortage_items:
            if excess["sku_id"] != shortage["sku_id"]:
                continue
            if excess["location"] == shortage["location"]:
                continue

            sku = excess["sku_id"]
            from_loc = excess["location"]
            to_loc = shortage["location"]
            storage_type = excess.get("storage_type", "dry")

            # Check storage compatibility
            if storage_type not in wh_storage.get(to_loc, []):
                logger.debug(f"Skipping {sku} {from_loc}→{to_loc}: storage mismatch")
                continue

            # Get transfer cost
            cost_row = cost_df[
                (cost_df["sku_id"] == sku) &
                (cost_df["from_location"] == from_loc) &
                (cost_df["to_location"] == to_loc)
            ]
            if cost_row.empty:
                transfer_cost = 20.0  # Default cost if not found
            else:
                transfer_cost = float(cost_row.iloc[0]["transfer_cost_per_unit"])

            holding_cost = float(
                cost_row.iloc[0]["holding_cost_per_unit_per_week"]
            ) if not cost_row.empty else 5.0

            max_transfer = min(abs(excess["gap"]), abs(shortage["gap"]))
            capacity_limit = int(wh_capacity.get(to_loc, 99999))
            max_transfer = min(max_transfer, capacity_limit)

            if max_transfer <= 0:
                continue

            candidates.append({
                "sku_id": sku,
                "from_location": from_loc,
                "to_location": to_loc,
                "max_transfer": int(max_transfer),
                "transfer_cost_per_unit": transfer_cost,
                "holding_cost_per_unit": holding_cost,
                "storage_type": storage_type,
                "shortage_gap": abs(shortage["gap"]),
                "expiry_priority": excess.get("expiry_priority", "LOW"),
            })

    logger.info(f"Built {len(candidates)} transfer candidates")
    return candidates


def solve_with_pyomo(
    candidates: List[Dict],
    alpha: float = 0.6,
    beta: float = 0.4,
    lambda_tradeoff: float = 10.0,
) -> Dict[str, Any]:
    """
    Solve the optimization problem using Pyomo with GLPK/CBC solver.
    Falls back to SciPy if no LP solver is installed.
    
    Objective: Minimize α×(transfer_cost + holding_cost) − β×(demand_fulfilled)
    """
    if not candidates:
        return {
            "status": "OPTIMAL",
            "transfers": [],
            "metrics": {"total_transfer_cost": 0, "demand_fulfillment_pct": 100,
                        "total_units_transferred": 0, "total_holding_saved": 0},
            "message": "No transfers needed — all locations balanced.",
        }

    model = ConcreteModel()

    # Index set
    N = range(len(candidates))
    model.N = N

    # Decision variables: how many units to transfer for each candidate
    model.transfer = Var(N, domain=NonNegativeIntegers)

    # Upper bounds
    for i in N:
        model.transfer[i].setub(candidates[i]["max_transfer"])

    # Objective: minimize cost - lambda * fulfilled demand
    total_shortage = sum(c["shortage_gap"] for c in candidates) or 1

    def objective_rule(m):
        transfer_cost = sum(
            m.transfer[i] * candidates[i]["transfer_cost_per_unit"]
            for i in N
        )
        holding_saved = sum(
            m.transfer[i] * candidates[i]["holding_cost_per_unit"] * 4  # 4 weeks saved
            for i in N
        )
        fulfillment = sum(m.transfer[i] for i in N) / total_shortage
        return alpha * (transfer_cost - holding_saved) - beta * lambda_tradeoff * fulfillment * 10000

    model.obj = Objective(rule=objective_rule, sense=minimize)

    # Constraint: Don't exceed excess at source (aggregate by SKU + from_location)
    source_groups = {}
    for i, c in enumerate(candidates):
        key = (c["sku_id"], c["from_location"])
        source_groups.setdefault(key, []).append(i)

    model.supply_constraints = Constraint(range(len(source_groups)))
    for idx, ((sku, loc), indices) in enumerate(source_groups.items()):
        max_excess = candidates[indices[0]]["max_transfer"]
        model.supply_constraints[idx] = (
            sum(model.transfer[i] for i in indices) <= max_excess
        )

    # Constraint: Don't exceed shortage at destination (aggregate by SKU + to_location)
    dest_groups = {}
    for i, c in enumerate(candidates):
        key = (c["sku_id"], c["to_location"])
        dest_groups.setdefault(key, []).append(i)

    model.demand_constraints = Constraint(range(len(dest_groups)))
    for idx, ((sku, loc), indices) in enumerate(dest_groups.items()):
        max_shortage = candidates[indices[0]]["shortage_gap"]
        model.demand_constraints[idx] = (
            sum(model.transfer[i] for i in indices) <= max_shortage
        )

    # Solve — try GLPK, then CBC, then fall back to SciPy
    solver = SolverFactory("glpk")
    if not solver.available():
        solver = SolverFactory("cbc")
    if not solver.available():
        logger.warning("No LP solver (GLPK/CBC) found, falling back to SciPy linprog")
        return solve_with_scipy(candidates, alpha, beta, lambda_tradeoff)

    try:
        result = solver.solve(model, tee=False)

        if result.solver.termination_condition == TerminationCondition.optimal:
            status = "OPTIMAL"
        elif result.solver.termination_condition == TerminationCondition.feasible:
            status = "FEASIBLE"
        else:
            status = "INFEASIBLE"
            return {
                "status": status,
                "transfers": [],
                "metrics": {},
                "message": f"Solver returned: {result.solver.termination_condition}",
            }
    except Exception as e:
        logger.error(f"Pyomo solver failed: {e}, falling back to SciPy")
        return solve_with_scipy(candidates, alpha, beta, lambda_tradeoff)

    # Extract solution
    transfers = []
    total_cost = 0
    total_units = 0
    total_holding_saved = 0

    for i in N:
        qty = int(value(model.transfer[i]))
        if qty > 0:
            cost = qty * candidates[i]["transfer_cost_per_unit"]
            holding_saved = qty * candidates[i]["holding_cost_per_unit"] * 4
            total_cost += cost
            total_units += qty
            total_holding_saved += holding_saved
            transfers.append({
                "sku_id": candidates[i]["sku_id"],
                "from_location": candidates[i]["from_location"],
                "to_location": candidates[i]["to_location"],
                "quantity": qty,
                "transfer_cost": round(cost, 2),
                "holding_cost_saved": round(holding_saved, 2),
                "expiry_priority": candidates[i]["expiry_priority"],
                "storage_type": candidates[i]["storage_type"],
            })

    fulfillment_pct = round((total_units / total_shortage) * 100, 1) if total_shortage > 0 else 100

    return {
        "status": status,
        "transfers": transfers,
        "metrics": {
            "total_transfer_cost": round(total_cost, 2),
            "total_holding_saved": round(total_holding_saved, 2),
            "net_cost": round(total_cost - total_holding_saved, 2),
            "demand_fulfillment_pct": fulfillment_pct,
            "total_units_transferred": total_units,
        },
        "solver_backend": "pyomo",
    }


def solve_with_scipy(
    candidates: List[Dict],
    alpha: float = 0.6,
    beta: float = 0.4,
    lambda_tradeoff: float = 10.0,
) -> Dict[str, Any]:
    """
    Fallback solver using scipy.optimize.linprog (HiGHS LP solver).
    Used when Pyomo/GLPK/CBC are not available.
    
    SciPy's HiGHS solver is bundled with scipy — no external install needed.
    """
    if not candidates:
        return {
            "status": "OPTIMAL", "transfers": [],
            "metrics": {"total_transfer_cost": 0, "demand_fulfillment_pct": 100,
                        "total_units_transferred": 0, "total_holding_saved": 0},
        }

    n = len(candidates)
    total_shortage = sum(c["shortage_gap"] for c in candidates) or 1

    # Objective coefficients: alpha * (transfer_cost - holding_saved) - beta * fulfillment
    c_obj = []
    for cand in candidates:
        tc = cand["transfer_cost_per_unit"]
        hs = cand["holding_cost_per_unit"] * 4
        fulfillment_bonus = beta * lambda_tradeoff / total_shortage * 10000
        c_obj.append(alpha * (tc - hs) - fulfillment_bonus)

    # Bounds: 0 to max_transfer
    bounds = [(0, cand["max_transfer"]) for cand in candidates]

    # Supply constraints: sum of transfers from each (sku, from_loc) <= max_transfer
    A_ub = []
    b_ub = []
    source_groups = {}
    for i, c in enumerate(candidates):
        key = (c["sku_id"], c["from_location"])
        source_groups.setdefault(key, []).append(i)

    for (sku, loc), indices in source_groups.items():
        row = [0.0] * n
        for i in indices:
            row[i] = 1.0
        A_ub.append(row)
        b_ub.append(candidates[indices[0]]["max_transfer"])

    # Demand constraints: sum of transfers to each (sku, to_loc) <= shortage_gap
    dest_groups = {}
    for i, c in enumerate(candidates):
        key = (c["sku_id"], c["to_location"])
        dest_groups.setdefault(key, []).append(i)

    for (sku, loc), indices in dest_groups.items():
        row = [0.0] * n
        for i in indices:
            row[i] = 1.0
        A_ub.append(row)
        b_ub.append(candidates[indices[0]]["shortage_gap"])

    try:
        result = linprog(
            c_obj,
            A_ub=A_ub if A_ub else None,
            b_ub=b_ub if b_ub else None,
            bounds=bounds,
            method="highs",
        )
        if not result.success:
            logger.error(f"SciPy solver failed: {result.message}")
            return {"status": "INFEASIBLE", "transfers": [], "metrics": {},
                    "message": "SciPy solver failed: " + str(result.message)}
    except Exception as e:
        logger.error(f"SciPy solver exception: {e}")
        return {"status": "ERROR", "transfers": [], "metrics": {},
                "message": f"Solver error: {e}"}

    # Extract solution (round to integers)
    transfers = []
    total_cost = 0
    total_units = 0
    total_holding_saved = 0

    for i, qty_float in enumerate(result.x):
        qty = int(round(qty_float))
        if qty > 0:
            cost = qty * candidates[i]["transfer_cost_per_unit"]
            holding_saved = qty * candidates[i]["holding_cost_per_unit"] * 4
            total_cost += cost
            total_units += qty
            total_holding_saved += holding_saved
            transfers.append({
                "sku_id": candidates[i]["sku_id"],
                "from_location": candidates[i]["from_location"],
                "to_location": candidates[i]["to_location"],
                "quantity": qty,
                "transfer_cost": round(cost, 2),
                "holding_cost_saved": round(holding_saved, 2),
                "expiry_priority": candidates[i]["expiry_priority"],
                "storage_type": candidates[i]["storage_type"],
            })

    fulfillment_pct = round((total_units / total_shortage) * 100, 1)

    return {
        "status": "OPTIMAL",
        "transfers": transfers,
        "metrics": {
            "total_transfer_cost": round(total_cost, 2),
            "total_holding_saved": round(total_holding_saved, 2),
            "net_cost": round(total_cost - total_holding_saved, 2),
            "demand_fulfillment_pct": fulfillment_pct,
            "total_units_transferred": total_units,
        },
        "solver_backend": "scipy_highs",
    }


def run_optimization(
    intelligence_output: Dict[str, Any],
    cost_df: pd.DataFrame,
    warehouse_df: pd.DataFrame,
    alpha: float = None,
    beta: float = None,
) -> Dict[str, Any]:
    """
    Main entry point for the Optimization Tool.
    
    Tries Pyomo (GLPK/CBC) first, falls back to SciPy HiGHS automatically.
    
    Args:
        intelligence_output: Output from Inventory Intelligence Agent
        cost_df: Cost data DataFrame
        warehouse_df: Warehouse metadata DataFrame
        alpha: Cost importance weight (default from config)
        beta: Service level weight (default from config)
    
    Returns:
        Optimization result with transfers, metrics, and status.
    """
    if alpha is None:
        alpha = CONFIG["optimization"]["alpha"]
    if beta is None:
        beta = CONFIG["optimization"]["beta"]
    lambda_tradeoff = CONFIG["optimization"]["lambda_tradeoff"]

    logger.info("=" * 60)
    logger.info("OPTIMIZATION SOLVER START")
    logger.info(f"  alpha={alpha}, beta={beta}, lambda={lambda_tradeoff}")
    logger.info("=" * 60)

    # Build candidates
    candidates = build_transfer_candidates(intelligence_output, cost_df, warehouse_df)

    if not candidates:
        logger.info("No valid transfer candidates found")
        return {
            "status": "OPTIMAL",
            "transfers": [],
            "metrics": {"total_transfer_cost": 0, "demand_fulfillment_pct": 100,
                        "total_units_transferred": 0, "total_holding_saved": 0},
            "message": "No transfers needed.",
        }

    # Solve: try Pyomo first, then SciPy
    if PYOMO_AVAILABLE:
        result = solve_with_pyomo(candidates, alpha, beta, lambda_tradeoff)
    else:
        result = solve_with_scipy(candidates, alpha, beta, lambda_tradeoff)

    logger.info(f"Optimization result: {result['status']}")
    logger.info(f"  Transfers: {len(result['transfers'])}")
    logger.info(f"  Metrics: {json.dumps(result.get('metrics', {}))}")
    logger.info(f"  Backend: {result.get('solver_backend', 'unknown')}")
    logger.info("=" * 60)

    return result
