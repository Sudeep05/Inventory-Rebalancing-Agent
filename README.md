# Agentic Inventory Rebalancing System

> **AMPBA Batch-24, Term-4 — CT2 Group Assignment (Assignment 1)**  
> Multi-agent system for automated warehouse inventory rebalancing using Google ADK + Gemini

## Problem Statement

A supply chain planner needs to rebalance inventory across 5 warehouses (Mumbai, Pune, Delhi, Bangalore, Chennai) to minimize holding + transfer costs while maximizing demand fulfillment. The current manual process is slow and error-prone.

This system automates: data validation → excess/shortage detection → optimization → recommendations → human approval → iterative refinement.

## Architecture

```
Planner Input → Input Guardrail → Data Processing → Inventory Intelligence
                     ↓ (reject)         (Pandas Tool)          ↓
               Ask Correction                          Optimization Agent
                                                        (Pyomo Solver)
                                                             ↓
                                                    Recommendation Agent
                                                             ↓
                                                   Human-in-the-Loop ★
                                                             ↓
                                                       Memory Agent
                                                             ↓
                                                    ◆ More Imbalance?
                                                     ↓ Yes       ↓ No
                                               Re-Optimize    Output Guardrail
                                                                   ↓
                                                          Final Recommendations
```

**Orchestration Pattern**: Hybrid (Sequential + Conditional Routing + Loop + Human-in-the-Loop)

## Sub-Agents

| # | Agent | Role | Tool |
|---|-------|------|------|
| 1 | Input Guardrail | Schema validation, prompt injection detection | — |
| 2 | Data Processing | Clean, merge, compute features | Pandas (Tool #1) |
| 3 | Inventory Intelligence | Excess/shortage/expiry classification | — |
| 4 | Optimization | Multi-objective transfer planning | Pyomo/SciPy (Tool #2) |
| 5 | Recommendation | Human-readable action items | — |
| 6 | Human-in-the-Loop | Approval checkpoint (bonus) | — |
| 7 | Memory | State tracking, duplicate prevention | — |
| 8 | Re-Optimization | Iterative loop until resolved | — |
| 9 | Output Guardrail | Validate output, no hallucinations | — |

## Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd Logistics-Agent

# Install dependencies
pip install -r requirements.txt

# Generate synthetic data
python data/generate_synthetic_data.py

# Run the full pipeline
python pipeline/orchestrator.py

# Run scenario tests
python tests/scenario_tests.py

# Run sub-agent evaluation
python evaluation/evaluate_intelligence_agent.py
```

## Project Structure

```
Logistics-Agent/
├── README.md
├── requirements.txt
├── TODO.md
├── agents/                      # Sub-agent modules
│   ├── input_guardrail.py
│   ├── data_processing.py
│   ├── inventory_intelligence.py
│   ├── optimization.py
│   ├── recommendation.py
│   ├── human_in_loop.py
│   ├── memory.py
│   ├── reoptimization.py
│   └── output_guardrail.py
├── tools/                       # External tool integrations
│   ├── data_tool.py             # Tool #1: Pandas data processing
│   └── optimizer_tool.py        # Tool #2: Pyomo/SciPy solver
├── prompts/                     # Agent prompts in .md format
│   ├── input_guardrail.md
│   ├── data_processing.md
│   ├── inventory_intelligence.md
│   ├── optimization.md
│   ├── recommendation.md
│   └── output_guardrail.md
├── pipeline/
│   └── orchestrator.py          # Main pipeline orchestrator
├── utils/
│   └── helpers.py               # Shared utilities, state, config
├── data/
│   ├── generate_synthetic_data.py
│   ├── inventory.csv
│   ├── demand_forecast.csv
│   ├── production_plan.csv
│   ├── cost_data.csv
│   └── warehouse_metadata.csv
├── evaluation/
│   ├── eval_dataset.csv         # 20 curated test cases
│   ├── evaluate_intelligence_agent.py
│   └── eval_results.json
├── tests/
│   ├── scenario_tests.py        # 6 scenario tests
│   └── scenario_results.json
├── docs/
│   └── design_document.pdf
├── logs/                        # Execution logs (auto-generated)
└── runner.ipynb                 # Entry-point notebook
```

## Key Features

- **Dual-objective optimization**: Minimizes costs while maximizing service levels using weighted multi-objective formulation
- **Iterative re-optimization**: Loop pattern re-runs optimization after each decision round until all shortages are resolved
- **Input/Output guardrails**: Prompt injection detection, schema validation, hallucination checks, PII scanning
- **Human-in-the-loop**: Approval checkpoint with Accept/Reject/Modify support for high-stakes decisions
- **Full observability**: Execution trace with timestamps for every agent call, decision, and tool invocation
- **Edge case coverage**: 14 edge cases baked into synthetic data (zero inventory, demand spikes, storage mismatches, capacity violations, near-expiry, adversarial inputs)

## Evaluation Results

**Inventory Intelligence Agent** (20 test cases):
- Status classification accuracy: **95.0%**
- Macro F1 (status): **0.958**
- Severity classification accuracy: **85.0%**

## Team

AMPBA Batch-24

## License

Academic use only — ISB Honor Code 3N-a applies.
