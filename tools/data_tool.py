"""
Data Processing Tool (Pandas)
=============================
Tool Integration #1: Uses Python/Pandas for data loading, cleaning, merging,
and feature computation. This is registered as an external tool for the
Data Processing Agent.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, Tuple
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, CONFIG

logger = get_logger("data_tool")


def load_all_datasets(data_dir: str = None) -> Dict[str, pd.DataFrame]:
    """
    Load all 5 CSV datasets from the data directory.
    
    Returns:
        Dictionary mapping dataset name to DataFrame.
    """
    if data_dir is None:
        data_dir = CONFIG["data_dir"]

    datasets = {}
    for name, path in CONFIG["files"].items():
        if data_dir != CONFIG["data_dir"]:
            path = os.path.join(data_dir, os.path.basename(path))
        try:
            datasets[name] = pd.read_csv(path)
            logger.info(f"Loaded {name}: {len(datasets[name])} rows")
        except FileNotFoundError:
            logger.error(f"File not found: {path}")
            datasets[name] = None
    return datasets


def clean_inventory(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """
    Clean inventory data: parse dates, handle nulls, fix types.
    
    Returns:
        Tuple of (cleaned DataFrame, quality report dict).
    """
    report = {"nulls_filled": 0, "type_corrections": 0, "duplicates_removed": 0}

    # Parse expiry dates
    df["expiry_date"] = pd.to_datetime(df["expiry_date"], errors="coerce")
    bad_dates = df["expiry_date"].isna().sum()
    if bad_dates > 0:
        report["type_corrections"] += int(bad_dates)
        logger.warning(f"Found {bad_dates} unparseable expiry dates")

    # Fill null quantities with 0
    null_qty = df["quantity"].isna().sum()
    if null_qty > 0:
        df["quantity"] = df["quantity"].fillna(0)
        report["nulls_filled"] += int(null_qty)

    # Ensure quantity is non-negative integer
    df["quantity"] = df["quantity"].astype(int).clip(lower=0)

    # Remove duplicates
    before = len(df)
    df = df.drop_duplicates(subset=["sku_id", "lot_id", "location"])
    report["duplicates_removed"] = before - len(df)

    return df, report


def clean_demand(df: pd.DataFrame) -> pd.DataFrame:
    """Clean demand forecast data."""
    df["forecast_demand"] = df["forecast_demand"].fillna(0).astype(int).clip(lower=0)
    df = df.drop_duplicates(subset=["sku_id", "location", "week"])
    return df


def clean_production(df: pd.DataFrame) -> pd.DataFrame:
    """Clean production plan data."""
    df["planned_production"] = df["planned_production"].fillna(0).astype(int).clip(lower=0)
    df = df.drop_duplicates(subset=["sku_id", "location", "week"])
    return df


def aggregate_and_merge(
    inventory_df: pd.DataFrame,
    demand_df: pd.DataFrame,
    production_df: pd.DataFrame,
    cost_df: pd.DataFrame,
    warehouse_df: pd.DataFrame,
    analysis_date: datetime = None,
) -> pd.DataFrame:
    """
    Aggregate data to SKU × Location level and merge all datasets.
    
    Steps:
        1. Aggregate inventory by (sku_id, location): sum quantity, min expiry
        2. Aggregate demand by (sku_id, location): sum forecast_demand
        3. Aggregate production by (sku_id, location): sum planned_production
        4. Merge all together with warehouse metadata
        5. Compute net_demand, inventory_gap, days_to_expiry
    
    Returns:
        Merged DataFrame ready for intelligence analysis.
    """
    if analysis_date is None:
        analysis_date = datetime.now()

    # ── Step 1: Aggregate inventory ──
    inv_agg = inventory_df.groupby(["sku_id", "location", "storage_type"]).agg(
        total_inventory=("quantity", "sum"),
        earliest_expiry=("expiry_date", "min"),
        lot_count=("lot_id", "count"),
    ).reset_index()

    # ── Step 2: Aggregate demand ──
    demand_agg = demand_df.groupby(["sku_id", "location"]).agg(
        total_forecast=("forecast_demand", "sum"),
    ).reset_index()

    # ── Step 3: Aggregate production ──
    prod_agg = production_df.groupby(["sku_id", "location"]).agg(
        total_production=("planned_production", "sum"),
    ).reset_index()

    # ── Step 4: Merge ──
    merged = inv_agg.merge(demand_agg, on=["sku_id", "location"], how="left")
    merged = merged.merge(prod_agg, on=["sku_id", "location"], how="left")
    merged = merged.merge(warehouse_df, on="location", how="left")

    # Fill NaN from left joins
    merged["total_forecast"] = merged["total_forecast"].fillna(0).astype(int)
    merged["total_production"] = merged["total_production"].fillna(0).astype(int)

    # ── Step 5: Compute derived fields ──
    merged["net_demand"] = merged["total_forecast"] - merged["total_production"]
    merged["inventory_gap"] = merged["total_inventory"] - merged["net_demand"]

    # Days to expiry
    merged["days_to_expiry"] = (merged["earliest_expiry"] - pd.Timestamp(analysis_date)).dt.days
    merged["days_to_expiry"] = merged["days_to_expiry"].fillna(999).astype(int)

    # Capacity headroom
    merged["capacity_headroom"] = (
        merged["max_capacity"] * (1 - merged["current_utilization_pct"] / 100)
    ).fillna(0).astype(int)

    # Storage compatibility flag
    merged["storage_compatible"] = merged.apply(
        lambda row: row["storage_type"] in str(row.get("storage_types_supported", "")),
        axis=1,
    )

    logger.info(f"Merged dataset: {len(merged)} rows, {merged.columns.tolist()}")
    return merged


def process_all_data(data_dir: str = None, analysis_date: datetime = None) -> Dict[str, Any]:
    """
    Full data processing pipeline: load → clean → merge → compute.
    
    This is the main entry point called by the Data Processing Agent.
    
    Args:
        data_dir: Path to data directory (default: config)
        analysis_date: Reference date for calculations (default: now)
    
    Returns:
        Dictionary with merged_data, cost_data, quality_report, and summary stats.
    """
    logger.info("=" * 60)
    logger.info("DATA PROCESSING PIPELINE START")
    logger.info("=" * 60)

    # Load
    datasets = load_all_datasets(data_dir)
    for name, df in datasets.items():
        if df is None:
            return {"error": f"Failed to load {name}.csv", "status": "FAIL"}

    # Clean
    inventory_clean, quality_report = clean_inventory(datasets["inventory"])
    demand_clean = clean_demand(datasets["demand_forecast"])
    production_clean = clean_production(datasets["production_plan"])

    # Merge
    merged = aggregate_and_merge(
        inventory_clean,
        demand_clean,
        production_clean,
        datasets["cost_data"],
        datasets["warehouse_metadata"],
        analysis_date,
    )

    # Summary stats
    summary = {
        "total_skus": merged["sku_id"].nunique(),
        "total_locations": merged["location"].nunique(),
        "total_rows": len(merged),
        "total_inventory_units": int(merged["total_inventory"].sum()),
        "total_forecast_demand": int(merged["total_forecast"].sum()),
        "total_planned_production": int(merged["total_production"].sum()),
    }

    logger.info(f"Processing complete. Summary: {json.dumps(summary)}")
    logger.info("=" * 60)

    return {
        "status": "SUCCESS",
        "merged_data": merged,
        "cost_data": datasets["cost_data"],
        "warehouse_metadata": datasets["warehouse_metadata"],
        "inventory_raw": inventory_clean,
        "quality_report": quality_report,
        "summary": summary,
    }


if __name__ == "__main__":
    result = process_all_data()
    if result["status"] == "SUCCESS":
        print(f"\nSummary: {json.dumps(result['summary'], indent=2)}")
        print(f"\nMerged data shape: {result['merged_data'].shape}")
        print(f"\nFirst 5 rows:\n{result['merged_data'].head()}")
    else:
        print(f"Error: {result.get('error')}")
