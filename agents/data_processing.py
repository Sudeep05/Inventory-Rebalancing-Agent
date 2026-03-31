"""
Data Processing Agent
=====================
Sub-Agent 2: Cleans, structures, and merges all input datasets
using the Pandas Data Tool. Prepares analysis-ready data for
the Inventory Intelligence Agent.
"""

import pandas as pd
import os
import sys
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import get_logger, AgentState
from tools.data_tool import process_all_data

logger = get_logger("data_processing")


def run_data_processing(state: AgentState, data_dir: str = None) -> Dict[str, Any]:
    """
    Main entry point for the Data Processing Agent.
    
    Uses the Pandas Data Tool to:
    1. Load all CSV files
    2. Clean and type-cast data
    3. Handle missing values and duplicates
    4. Merge into unified SKU x Location DataFrame
    5. Compute derived fields (net_demand, days_to_expiry, etc.)
    """
    logger.info("=" * 60)
    logger.info("DATA PROCESSING AGENT START")
    logger.info("=" * 60)

    state.add_trace("DataProcessingAgent", "processing_start")

    try:
        result = process_all_data(data_dir=data_dir)

        if result["status"] != "SUCCESS":
            error_msg = result.get("error", "Unknown data processing error")
            state.add_error("DataProcessingAgent", error_msg)
            state.add_trace("DataProcessingAgent", "processing_failed", {"error": error_msg})
            state.status = "processing_failed"
            logger.error(f"Data processing failed: {error_msg}")
            return result

        state.processed_data = {
            "merged_data": result["merged_data"],
            "cost_data": result["cost_data"],
            "warehouse_metadata": result["warehouse_metadata"],
            "inventory_raw": result["inventory_raw"],
            "quality_report": result["quality_report"],
            "summary": result["summary"],
        }
        state.status = "data_processed"

        state.add_trace("DataProcessingAgent", "processing_complete", {
            "rows": len(result["merged_data"]),
            "skus": result["summary"]["total_skus"],
            "locations": result["summary"]["total_locations"],
            "total_inventory": result["summary"]["total_inventory_units"],
            "total_demand": result["summary"]["total_forecast_demand"],
        })

        logger.info(f"Data processing complete: {len(result['merged_data'])} merged rows")
        logger.info(f"  Quality: {result['quality_report']}")
        logger.info("=" * 60)

        return result

    except Exception as e:
        error_msg = f"Data processing exception: {str(e)}"
        state.add_error("DataProcessingAgent", error_msg)
        state.add_trace("DataProcessingAgent", "processing_exception", {"error": str(e)})
        state.status = "processing_failed"
        logger.exception(error_msg)
        return {"status": "FAIL", "error": error_msg}
