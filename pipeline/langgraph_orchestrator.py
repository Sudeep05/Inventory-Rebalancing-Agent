"""
LangGraph Pipeline Orchestrator
================================
Wraps the existing 9-agent pipeline in a LangGraph StateGraph.
Implements the same hybrid orchestration pattern:
  - Sequential flow (stages 1-9)
  - Conditional routing (input guardrail PASS/REJECT, solver fallback)
  - Iterative loop (stages 4-8 re-optimization)
  - Human-in-the-Loop (stage 6 approval checkpoint)

All existing agent functions remain unchanged — LangGraph provides
the orchestration graph while agents provide the domain logic.
"""

import os
import sys
from typing import TypedDict, Literal, List, Optional, Any
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.graph import StateGraph, END

from utils.helpers import get_logger, AgentState, CONFIG
from tools.data_tool import load_all_datasets
from agents.input_guardrail import run_input_guardrail
from agents.data_processing import run_data_processing
from agents.inventory_intelligence import run_inventory_intelligence
from agents.optimization import run_optimization_agent
from agents.recommendation import run_recommendation_agent
from agents.human_in_loop import run_human_in_loop
from agents.memory import run_memory_agent
from agents.reoptimization import run_reoptimization_agent
from agents.output_guardrail import run_output_guardrail

logger = get_logger("langgraph_orchestrator")


# ══════════════════════════════════════════════════════════════
# STATE DEFINITION
# ══════════════════════════════════════════════════════════════

class PipelineState(TypedDict):
    """LangGraph state passed through all nodes."""
    agent_state: Any            # AgentState object (mutable, shared across nodes)
    user_query: str
    data_dir: Optional[str]
    mode: str                   # "auto", "selective", "reject_all"
    alpha: Optional[float]
    beta: Optional[float]
    max_iterations: int
    accepted_ids: Optional[List[str]]
    # Routing signals
    guardrail_status: str       # "PASS", "FAIL", "REJECTED"
    loop_status: str            # "CONTINUE", "STOP"
    all_recommendations: list   # Accumulated across iterations


# ══════════════════════════════════════════════════════════════
# NODE FUNCTIONS (thin wrappers around existing agents)
# ══════════════════════════════════════════════════════════════

def node_input_guardrail(state: PipelineState) -> dict:
    """Node 1: Input validation + prompt injection detection (regex + LLM)."""
    logger.info(">>> STAGE 1: Input Guardrail")
    agent_state = state["agent_state"]
    datasets = load_all_datasets(state["data_dir"])
    result = run_input_guardrail(agent_state, datasets, state["user_query"])
    return {"guardrail_status": result["status"]}


def node_data_processing(state: PipelineState) -> dict:
    """Node 2: Clean, merge, compute features using Pandas Tool (#1)."""
    logger.info(">>> STAGE 2: Data Processing")
    run_data_processing(state["agent_state"], state["data_dir"])
    return {}


def node_intelligence(state: PipelineState) -> dict:
    """Node 3: Classify excess/shortage + LLM analysis summary."""
    logger.info(">>> STAGE 3: Inventory Intelligence")
    run_inventory_intelligence(state["agent_state"])
    return {}


def node_optimization(state: PipelineState) -> dict:
    """Node 4: Solve transfer LP using Pyomo/SciPy Tool (#2)."""
    agent_state = state["agent_state"]
    logger.info(f">>> Stage 4 (iter {agent_state.iteration}): Optimization")
    run_optimization_agent(agent_state, alpha=state["alpha"], beta=state["beta"])
    return {}


def node_recommendation(state: PipelineState) -> dict:
    """Node 5: Generate prioritized recommendations + LLM enrichment."""
    agent_state = state["agent_state"]
    logger.info(f">>> Stage 5 (iter {agent_state.iteration}): Recommendation")
    run_recommendation_agent(agent_state)
    return {}


def node_human_in_loop(state: PipelineState) -> dict:
    """Node 6: Human approval checkpoint (auto/selective/reject_all)."""
    agent_state = state["agent_state"]
    logger.info(f">>> Stage 6 (iter {agent_state.iteration}): Human-in-the-Loop")
    result = run_human_in_loop(agent_state, mode=state["mode"], accepted_ids=state["accepted_ids"])
    accepted = result.get("decision", {}).get("accepted", [])
    all_recs = state["all_recommendations"] + accepted
    return {"all_recommendations": all_recs}


def node_memory(state: PipelineState) -> dict:
    """Node 7: Record decisions, detect duplicates, check remaining shortages."""
    agent_state = state["agent_state"]
    logger.info(f">>> Stage 7 (iter {agent_state.iteration}): Memory Update")
    accepted = agent_state.human_decisions[-1] if agent_state.human_decisions else {}
    # Get the accepted recommendations from the HITL decision
    hitl_accepted = []
    if agent_state.recommendations:
        if state["mode"] == "selective" and state["accepted_ids"]:
            hitl_accepted = [r for r in agent_state.recommendations if r.get("id") in state["accepted_ids"]]
        elif state["mode"] != "reject_all":
            hitl_accepted = agent_state.recommendations
    run_memory_agent(agent_state, accepted_recommendations=hitl_accepted)
    return {}


def node_reoptimization(state: PipelineState) -> dict:
    """Node 8: Decide whether to loop back to optimization."""
    agent_state = state["agent_state"]
    logger.info(f">>> Stage 8 (iter {agent_state.iteration}): Re-optimization Check")
    from agents.memory import check_remaining_imbalances
    remaining = check_remaining_imbalances(agent_state)
    memory_result = {
        "should_continue_loop": (
            remaining["has_remaining_shortages"]
            and agent_state.iteration < agent_state.max_iterations
        ),
        "remaining_imbalances": remaining,
    }
    result = run_reoptimization_agent(agent_state, memory_result)
    return {"loop_status": result["status"]}


def node_output_guardrail(state: PipelineState) -> dict:
    """Node 9: Validate final output — no hallucinations, PII, circular transfers."""
    logger.info(">>> STAGE 9: Output Guardrail")
    agent_state = state["agent_state"]
    agent_state.recommendations = state["all_recommendations"]
    run_output_guardrail(agent_state)
    return {}


# ══════════════════════════════════════════════════════════════
# CONDITIONAL ROUTING FUNCTIONS
# ══════════════════════════════════════════════════════════════

def route_after_guardrail(state: PipelineState) -> Literal["data_processing", "__end__"]:
    """Conditional routing: PASS → continue, FAIL/REJECTED → end."""
    if state["guardrail_status"] == "PASS":
        return "data_processing"
    logger.warning(f"Pipeline ABORTED at Input Guardrail: {state['guardrail_status']}")
    return END


def route_after_reoptimization(state: PipelineState) -> Literal["optimization", "output_guardrail"]:
    """Loop routing: CONTINUE → back to optimization, STOP → output guardrail."""
    if state["loop_status"] == "CONTINUE":
        logger.info(f"LOOP CONTINUE → Iteration {state['agent_state'].iteration}")
        return "optimization"
    logger.info("LOOP STOP → Output Guardrail")
    return "output_guardrail"


# ══════════════════════════════════════════════════════════════
# GRAPH CONSTRUCTION
# ══════════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    """
    Build the LangGraph StateGraph for the inventory rebalancing pipeline.

    Graph structure:
        START → input_guardrail → [PASS/REJECT]
            REJECT → END
            PASS → data_processing → intelligence → optimization
                → recommendation → human_in_loop → memory → reoptimization
                    → [CONTINUE/STOP]
                        CONTINUE → optimization (loop back)
                        STOP → output_guardrail → END
    """
    graph = StateGraph(PipelineState)

    # Add all 9 agent nodes
    graph.add_node("input_guardrail", node_input_guardrail)
    graph.add_node("data_processing", node_data_processing)
    graph.add_node("intelligence", node_intelligence)
    graph.add_node("optimization", node_optimization)
    graph.add_node("recommendation", node_recommendation)
    graph.add_node("human_in_loop", node_human_in_loop)
    graph.add_node("memory", node_memory)
    graph.add_node("reoptimization", node_reoptimization)
    graph.add_node("output_guardrail", node_output_guardrail)

    # Entry point
    graph.set_entry_point("input_guardrail")

    # Conditional: guardrail PASS/REJECT
    graph.add_conditional_edges("input_guardrail", route_after_guardrail)

    # Sequential: data_processing → intelligence → optimization
    graph.add_edge("data_processing", "intelligence")
    graph.add_edge("intelligence", "optimization")

    # Sequential through the loop body: optimize → recommend → HITL → memory → reopt
    graph.add_edge("optimization", "recommendation")
    graph.add_edge("recommendation", "human_in_loop")
    graph.add_edge("human_in_loop", "memory")
    graph.add_edge("memory", "reoptimization")

    # Conditional: loop back or exit to output guardrail
    graph.add_conditional_edges("reoptimization", route_after_reoptimization)

    # Output guardrail → END
    graph.add_edge("output_guardrail", END)

    return graph


# ══════════════════════════════════════════════════════════════
# PIPELINE ENTRY POINT
# ══════════════════════════════════════════════════════════════

# Compile graph once at module load
_compiled_graph = build_graph().compile()


def run_pipeline(
    user_query: str = "Rebalance inventory across all warehouses",
    data_dir: str = None,
    mode: str = "auto",
    alpha: float = None,
    beta: float = None,
    max_iterations: int = 5,
    accepted_ids: List[str] = None,
) -> dict:
    """
    Execute the LangGraph-based inventory rebalancing pipeline.

    Args:
        user_query: Planner's text input
        data_dir: Path to data directory
        mode: "auto" | "selective" | "reject_all"
        alpha: Cost weight (0-1), default 0.6
        beta: Service level weight (0-1), default 0.4
        max_iterations: Max re-optimization loops
        accepted_ids: Recommendation IDs to accept (selective mode)

    Returns:
        Pipeline result dict with status, recommendations, trace.
    """
    # Initialize agent state
    agent_state = AgentState()
    agent_state.max_iterations = max_iterations
    agent_state.iteration = 1
    agent_state.raw_input = {"query": user_query, "data_dir": data_dir, "mode": mode}

    logger.info("=" * 70)
    logger.info("AGENTIC INVENTORY REBALANCING PIPELINE — START (LangGraph)")
    logger.info(f"  Query: {user_query}")
    logger.info(f"  Mode: {mode} | Max Iterations: {max_iterations}")
    logger.info("=" * 70)

    agent_state.add_trace("Orchestrator", "pipeline_start", {
        "query": user_query, "mode": mode, "max_iterations": max_iterations,
        "framework": "LangGraph",
    })

    # Build initial state
    initial_state: PipelineState = {
        "agent_state": agent_state,
        "user_query": user_query,
        "data_dir": data_dir,
        "mode": mode,
        "alpha": alpha,
        "beta": beta,
        "max_iterations": max_iterations,
        "accepted_ids": accepted_ids,
        "guardrail_status": "",
        "loop_status": "",
        "all_recommendations": [],
    }

    # Execute the graph
    final_state = _compiled_graph.invoke(initial_state)

    # Extract results
    agent_state = final_state["agent_state"]
    all_recs = final_state.get("all_recommendations", [])

    result = {
        "status": agent_state.status,
        "timestamp": datetime.now().isoformat(),
        "iterations": agent_state.iteration,
        "total_accepted_transfers": len(agent_state.accepted_transfers),
        "recommendations": agent_state.recommendations or all_recs,
        "errors": agent_state.errors,
        "trace": agent_state.trace,
        "trace_summary": agent_state.get_trace_summary(),
        "state_summary": agent_state.to_dict(),
    }

    logger.info("\n" + "=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Status: {result['status']}")
    logger.info(f"  Iterations: {agent_state.iteration}")
    logger.info(f"  Total Recommendations: {len(result['recommendations'])}")
    logger.info(f"  Trace Entries: {len(agent_state.trace)}")
    logger.info("=" * 70)

    return result
