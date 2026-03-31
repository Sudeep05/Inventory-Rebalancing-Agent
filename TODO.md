# Assignment 1: Agentic Inventory Rebalancing System — TODO

## PHASE 1: FOUNDATION
- [x] 1.1  Create project folder structure
- [x] 1.2  Generate synthetic datasets (5 CSV files)
- [x] 1.3  Write prompt .md files for each agent (few-shot + reasoning)
- [x] 1.4  Create utils/helpers.py (shared utilities, logging, state)
- [x] 1.5  Create requirements.txt

## PHASE 2: CORE AGENTS
- [x] 2.1  agents/input_guardrail.py
- [x] 2.2  agents/data_processing.py
- [x] 2.3  agents/inventory_intelligence.py
- [x] 2.4  agents/optimization.py
- [x] 2.5  agents/recommendation.py
- [x] 2.6  agents/output_guardrail.py

## PHASE 3: TOOLS + ORCHESTRATION
- [x] 3.1  tools/data_tool.py (Pandas — Tool #1)
- [x] 3.2  tools/optimizer_tool.py (Pyomo/SciPy — Tool #2)
- [x] 3.3  agents/memory.py
- [x] 3.4  agents/human_in_loop.py (bonus)
- [x] 3.5  agents/reoptimization.py
- [x] 3.6  pipeline/orchestrator.py (Hybrid: Sequential + Conditional + Loop + HITL)

## PHASE 4: TESTING + EVALUATION
- [x] 4.1  6 scenario tests — ALL PASSED
- [x] 4.2  eval_dataset.csv (20 cases)
- [x] 4.3  evaluate_intelligence_agent.py
- [x] 4.4  Results: 95% accuracy, Macro F1 = 0.958

## PHASE 5: DOCUMENTATION
- [x] 5.1  runner.ipynb (executed with captured outputs — 125KB)
- [x] 5.2  design_document.pdf (10 pages, all 9 required sections)
        - Problem statement & business context ✓
        - Architecture diagram ✓
        - Sub-agent descriptions (all 9) ✓
        - Guardrail strategy (10 guardrails) ✓
        - Orchestration pattern justification (Paragraph-wrapped) ✓
        - Scenario test results (6 scenarios) ✓
        - Sub-agent evaluation + failure analysis ✓
        - Observability: REAL log traces, all 9 agents + 2 tools ✓
        - Development journey (what went wrong & fixes) ✓
        - Reflections & limitations ✓
- [x] 5.3  Observability: 12 log files (274KB), 29 trace entries/run
- [x] 5.4  README.md
- [x] 5.5  main.py
- [ ] 5.6  **Push to GitHub** ← DO THIS NOW
- [ ] 5.7  Fill Peer Evaluation Form on LMS (before April 13)

## RESULTS SUMMARY
| Metric | Value |
|--------|-------|
| Sub-agents | 9 |
| Tools integrated | 2 (Pandas + Pyomo/SciPy) |
| Orchestration patterns | 4 (Sequential + Conditional + Loop + HITL) |
| Scenario tests | 6/6 passed |
| Evaluation dataset | 20 curated cases |
| Status accuracy | 95.0% |
| Macro F1 (status) | 0.958 |
| Prompt files | 6 (.md with few-shot examples) |
| Edge cases in data | 14 |
| Log files | 12 (274KB total) |
| Trace entries/run | 29 (Happy Path) |
