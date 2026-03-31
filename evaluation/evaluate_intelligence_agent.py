"""
Sub-Agent Evaluation: Inventory Intelligence Agent
===================================================
Evaluates the accuracy of excess/shortage/balanced/mismatch classification
using 20 manually curated test cases with ground-truth labels.

Metrics: Precision, Recall, F1-Score (per class and macro average)
"""

import pandas as pd
import numpy as np
import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.inventory_intelligence import classify_imbalances


def load_eval_dataset(path: str = None) -> pd.DataFrame:
    """Load the manually curated evaluation dataset."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_dataset.csv")
    return pd.read_csv(path)


def prepare_merged_df(eval_df: pd.DataFrame) -> pd.DataFrame:
    """Convert evaluation dataset into the merged DataFrame format expected by the agent."""
    merged = eval_df.rename(columns={
        "total_inventory": "total_inventory",
        "net_demand": "net_demand",
        "storage_type": "storage_type",
        "storage_compatible": "storage_compatible",
        "days_to_expiry": "days_to_expiry",
    })

    # Add fields expected by classify_imbalances
    merged["total_forecast"] = merged["net_demand"].clip(lower=0)
    merged["total_production"] = 0
    merged["max_capacity"] = 10000
    merged["current_utilization_pct"] = 50.0
    merged["storage_types_supported"] = merged.apply(
        lambda r: "dry,cold" if r["storage_compatible"] else "dry", axis=1
    )
    merged["lot_count"] = 1
    merged["earliest_expiry"] = pd.Timestamp("2026-04-01") + pd.to_timedelta(merged["days_to_expiry"], unit="D")
    merged["capacity_headroom"] = 5000

    return merged


def compute_metrics(y_true: list, y_pred: list, labels: list) -> dict:
    """
    Compute per-class Precision, Recall, F1, and macro averages.
    
    Args:
        y_true: Ground truth labels
        y_pred: Predicted labels
        labels: List of unique class labels
    
    Returns:
        Dictionary with per-class and macro metrics.
    """
    metrics = {}
    precisions, recalls, f1s = [], [], []

    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(1 for t in y_true if t == label),
            "tp": tp, "fp": fp, "fn": fn,
        }
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    metrics["macro_avg"] = {
        "precision": round(np.mean(precisions), 4),
        "recall": round(np.mean(recalls), 4),
        "f1": round(np.mean(f1s), 4),
    }
    metrics["accuracy"] = round(sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true), 4)

    return metrics


def run_evaluation():
    """Run the full evaluation pipeline."""
    print("=" * 70)
    print("SUB-AGENT EVALUATION: Inventory Intelligence Agent")
    print("=" * 70)

    # Load dataset
    eval_df = load_eval_dataset()
    print(f"\nEvaluation dataset: {len(eval_df)} test cases")

    # Prepare data
    merged_df = prepare_merged_df(eval_df)

    # Run the agent
    predictions = classify_imbalances(merged_df)

    # Extract predicted statuses (aligned with eval order)
    pred_statuses = [p["status"] for p in predictions]
    true_statuses = eval_df["expected_status"].tolist()

    # Also evaluate severity
    pred_severities = [p["severity"] for p in predictions]
    true_severities = eval_df["expected_severity"].tolist()

    # ── Status Classification Metrics ──
    status_labels = sorted(set(true_statuses + pred_statuses))
    status_metrics = compute_metrics(true_statuses, pred_statuses, status_labels)

    print("\n" + "-" * 70)
    print("STATUS CLASSIFICATION RESULTS")
    print("-" * 70)
    print(f"{'Class':<22} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
    print("-" * 62)
    for label in status_labels:
        m = status_metrics[label]
        print(f"{label:<22} {m['precision']:>10.4f} {m['recall']:>10.4f} {m['f1']:>10.4f} {m['support']:>10}")
    print("-" * 62)
    macro = status_metrics["macro_avg"]
    print(f"{'Macro Average':<22} {macro['precision']:>10.4f} {macro['recall']:>10.4f} {macro['f1']:>10.4f}")
    print(f"{'Accuracy':<22} {status_metrics['accuracy']:>10.4f}")

    # ── Severity Classification Metrics ──
    severity_labels = sorted(set(true_severities + pred_severities))
    severity_metrics = compute_metrics(true_severities, pred_severities, severity_labels)

    print("\n" + "-" * 70)
    print("SEVERITY CLASSIFICATION RESULTS")
    print("-" * 70)
    print(f"{'Class':<22} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
    print("-" * 62)
    for label in severity_labels:
        m = severity_metrics[label]
        print(f"{label:<22} {m['precision']:>10.4f} {m['recall']:>10.4f} {m['f1']:>10.4f} {m['support']:>10}")
    print("-" * 62)
    sev_macro = severity_metrics["macro_avg"]
    print(f"{'Macro Average':<22} {sev_macro['precision']:>10.4f} {sev_macro['recall']:>10.4f} {sev_macro['f1']:>10.4f}")
    print(f"{'Accuracy':<22} {severity_metrics['accuracy']:>10.4f}")

    # ── Detailed Comparison ──
    print("\n" + "-" * 70)
    print("DETAILED CASE-BY-CASE COMPARISON")
    print("-" * 70)
    mismatches = []
    for i, (true_s, pred_s, true_sev, pred_sev) in enumerate(
        zip(true_statuses, pred_statuses, true_severities, pred_severities)
    ):
        match_status = "✓" if true_s == pred_s else "✗"
        match_sev = "✓" if true_sev == pred_sev else "✗"
        test_id = eval_df.iloc[i]["test_id"]

        if true_s != pred_s or true_sev != pred_sev:
            mismatches.append({
                "test_id": test_id,
                "expected_status": true_s,
                "predicted_status": pred_s,
                "expected_severity": true_sev,
                "predicted_severity": pred_sev,
            })
            print(f"  {test_id}: Status {match_status} ({true_s} vs {pred_s}) | "
                  f"Severity {match_sev} ({true_sev} vs {pred_sev})")

    if not mismatches:
        print("  All 20 cases match perfectly!")

    # ── Failure Analysis ──
    print("\n" + "-" * 70)
    print("FAILURE ANALYSIS")
    print("-" * 70)
    if mismatches:
        print(f"Total mismatches: {len(mismatches)}/{len(eval_df)}")
        for m in mismatches:
            print(f"\n  {m['test_id']}:")
            if m['expected_status'] != m['predicted_status']:
                print(f"    Status: Expected {m['expected_status']}, Got {m['predicted_status']}")
                # Analyze why
                row = eval_df[eval_df["test_id"] == m["test_id"]].iloc[0]
                print(f"    Inventory={row['total_inventory']}, Net Demand={row['net_demand']}, "
                      f"Storage Compatible={row['storage_compatible']}")
            if m['expected_severity'] != m['predicted_severity']:
                print(f"    Severity: Expected {m['expected_severity']}, Got {m['predicted_severity']}")
    else:
        print("No failures — agent correctly classified all 20 test cases.")
        print("The deterministic computation logic (excess = inventory - net_demand)")
        print("combined with clear threshold rules produces reliable classifications.")

    # Save results
    results = {
        "status_metrics": status_metrics,
        "severity_metrics": severity_metrics,
        "mismatches": mismatches,
        "total_cases": len(eval_df),
        "accuracy": status_metrics["accuracy"],
    }

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == "__main__":
    run_evaluation()
