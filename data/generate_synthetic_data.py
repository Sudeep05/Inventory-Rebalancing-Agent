"""
Synthetic Data Generator for Agentic Inventory Rebalancing System
=================================================================
Generates 5 relational datasets with intentional edge cases for testing.

Datasets:
  1. inventory.csv        — SKU × Lot × Location level inventory
  2. demand_forecast.csv   — Weekly demand at SKU × Location level
  3. production_plan.csv   — Incoming supply (planned production)
  4. cost_data.csv         — Holding + transfer costs between locations
  5. warehouse_metadata.csv — Capacity and storage type constraints

Edge Cases Injected:
  - Zero inventory (shortage detection)
  - Excess inventory (redistribution)
  - Near-expiry lots (priority transfers)
  - Zero demand (no unnecessary transfers)
  - Demand spikes (shortage prioritization)
  - Storage mismatch (cold SKU in dry-only warehouse)
  - Capacity violations (warehouse over-capacity)
  - Balanced scenario (no action needed)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

# Fixed seed for reproducibility
SEED = 42
np.random.seed(SEED)

# ── Configuration ────────────────────────────────────────────────────
SKUS = [f"SKU{str(i).zfill(3)}" for i in range(1, 16)]  # 15 SKUs
LOCATIONS = ["Mumbai", "Pune", "Delhi", "Bangalore", "Chennai"]
WEEKS = ["W1", "W2", "W3", "W4"]
LOTS_PER_SKU = 2
BASE_DATE = datetime(2026, 4, 1)

# Storage type mapping for SKUs
SKU_STORAGE = {
    "SKU001": "dry", "SKU002": "dry", "SKU003": "cold",
    "SKU004": "dry", "SKU005": "cold", "SKU006": "dry",
    "SKU007": "dry", "SKU008": "cold", "SKU009": "dry",
    "SKU010": "dry", "SKU011": "cold", "SKU012": "dry",
    "SKU013": "dry", "SKU014": "cold", "SKU015": "dry",
}

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))


def generate_inventory():
    """Generate inventory data with edge cases at lot level."""
    rows = []
    for sku in SKUS:
        storage_type = SKU_STORAGE[sku]
        for loc in LOCATIONS:
            for lot_idx in range(1, LOTS_PER_SKU + 1):
                lot_id = f"{sku}-L{lot_idx}"

                # ── Edge case: Zero inventory ──
                if sku == "SKU005" and loc == "Delhi":
                    qty = 0
                # ── Edge case: Excess inventory ──
                elif sku == "SKU001" and loc == "Mumbai":
                    qty = 5000
                # ── Normal ──
                else:
                    qty = int(np.random.uniform(50, 800))

                # ── Edge case: Near-expiry lots ──
                if sku == "SKU003" and lot_idx == 1:
                    expiry = BASE_DATE + timedelta(days=5)  # Expires very soon
                elif sku == "SKU008" and loc == "Chennai":
                    expiry = BASE_DATE + timedelta(days=3)  # Critical expiry
                else:
                    expiry = BASE_DATE + timedelta(days=np.random.randint(30, 180))

                rows.append({
                    "sku_id": sku,
                    "lot_id": lot_id,
                    "location": loc,
                    "quantity": qty,
                    "expiry_date": expiry.strftime("%Y-%m-%d"),
                    "storage_type": storage_type,
                })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUTPUT_DIR, "inventory.csv"), index=False)
    print(f"  inventory.csv: {len(df)} rows")
    return df


def generate_demand_forecast():
    """Generate weekly demand forecasts with edge cases."""
    rows = []
    for sku in SKUS:
        for loc in LOCATIONS:
            for week in WEEKS:
                # ── Edge case: Zero demand ──
                if sku == "SKU012" and loc == "Pune":
                    demand = 0
                # ── Edge case: Demand spike ──
                elif sku == "SKU005" and loc == "Delhi" and week == "W2":
                    demand = 3000  # Huge spike + zero inventory = critical shortage
                # ── Edge case: Balanced (demand ≈ supply) ──
                elif sku == "SKU010" and loc == "Bangalore":
                    demand = 200  # Will match production closely
                # ── Normal ──
                else:
                    demand = int(np.random.uniform(50, 500))

                rows.append({
                    "sku_id": sku,
                    "location": loc,
                    "week": week,
                    "forecast_demand": demand,
                })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUTPUT_DIR, "demand_forecast.csv"), index=False)
    print(f"  demand_forecast.csv: {len(df)} rows")
    return df


def generate_production_plan():
    """Generate production plan with intermittent supply."""
    rows = []
    for sku in SKUS:
        for loc in LOCATIONS:
            for week in WEEKS:
                # Not all locations produce all SKUs
                if np.random.random() < 0.3:
                    production = 0  # No production this week
                # ── Edge case: Balanced scenario ──
                elif sku == "SKU010" and loc == "Bangalore":
                    production = 190  # Close to demand (200)
                else:
                    production = int(np.random.uniform(0, 400))

                rows.append({
                    "sku_id": sku,
                    "location": loc,
                    "week": week,
                    "planned_production": production,
                })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUTPUT_DIR, "production_plan.csv"), index=False)
    print(f"  production_plan.csv: {len(df)} rows")
    return df


def generate_cost_data():
    """Generate holding and transfer cost matrix between locations."""
    rows = []
    # Distance-based transfer costs (approximate relative costs)
    distance_map = {
        ("Mumbai", "Pune"): 5, ("Mumbai", "Delhi"): 25,
        ("Mumbai", "Bangalore"): 20, ("Mumbai", "Chennai"): 22,
        ("Pune", "Delhi"): 28, ("Pune", "Bangalore"): 18,
        ("Pune", "Chennai"): 20, ("Delhi", "Bangalore"): 30,
        ("Delhi", "Chennai"): 32, ("Bangalore", "Chennai"): 8,
    }

    for sku in SKUS:
        storage_type = SKU_STORAGE[sku]
        # Holding cost: cold storage costs more
        holding_cost = round(np.random.uniform(2, 5), 2) if storage_type == "dry" else round(np.random.uniform(6, 12), 2)

        for from_loc in LOCATIONS:
            for to_loc in LOCATIONS:
                if from_loc == to_loc:
                    continue

                pair = tuple(sorted([from_loc, to_loc]))
                base_distance = distance_map.get(pair, 20)
                # Cold chain transfer costs 1.5x more
                multiplier = 1.5 if storage_type == "cold" else 1.0
                transfer_cost = round(base_distance * multiplier * np.random.uniform(0.8, 1.2), 2)

                rows.append({
                    "sku_id": sku,
                    "from_location": from_loc,
                    "to_location": to_loc,
                    "transfer_cost_per_unit": transfer_cost,
                    "holding_cost_per_unit_per_week": holding_cost,
                })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUTPUT_DIR, "cost_data.csv"), index=False)
    print(f"  cost_data.csv: {len(df)} rows")
    return df


def generate_warehouse_metadata():
    """Generate warehouse capacity and storage type constraints."""
    rows = [
        # ── Edge case: Chennai only supports dry (but has cold SKUs assigned) ──
        {"location": "Chennai", "max_capacity": 8000, "storage_types_supported": "dry",
         "current_utilization_pct": 72.0, "dock_slots": 4},
        # ── Edge case: Pune has very low capacity ──
        {"location": "Pune", "max_capacity": 2000, "storage_types_supported": "dry,cold",
         "current_utilization_pct": 88.0, "dock_slots": 2},
        # ── Normal warehouses ──
        {"location": "Mumbai", "max_capacity": 15000, "storage_types_supported": "dry,cold",
         "current_utilization_pct": 65.0, "dock_slots": 6},
        {"location": "Delhi", "max_capacity": 12000, "storage_types_supported": "dry,cold",
         "current_utilization_pct": 55.0, "dock_slots": 5},
        {"location": "Bangalore", "max_capacity": 10000, "storage_types_supported": "dry,cold",
         "current_utilization_pct": 60.0, "dock_slots": 4},
    ]

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUTPUT_DIR, "warehouse_metadata.csv"), index=False)
    print(f"  warehouse_metadata.csv: {len(df)} rows")
    return df


def main():
    """Generate all synthetic datasets."""
    print("Generating synthetic datasets...")
    print(f"  Random seed: {SEED}")
    print(f"  SKUs: {len(SKUS)}, Locations: {len(LOCATIONS)}, Weeks: {len(WEEKS)}")
    print()

    generate_inventory()
    generate_demand_forecast()
    generate_production_plan()
    generate_cost_data()
    generate_warehouse_metadata()

    print("\nAll datasets generated successfully!")
    print(f"Output directory: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
