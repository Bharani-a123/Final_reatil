# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Extended LangGraph compilation using ExtendedState.
Maintains core nodes and edges, preparing for Phase 1 worker additions.
"""
from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnablePassthrough
from chain_server.src.graph import GraphNodes, GraphRouting
from .state import ExtendedState

def create_extended_graph(
    cart_agent,
    retriever_agent,
    planner_agent,
    chatter_agent,
    summary_agent,
    inventory_agent,
    payment_agent,
    fulfillment_agent,
    loyalty_agent,
    support_agent,
    config
) -> StateGraph:
    """
    Creates and compiles the extended LangGraph.
    """
    # Force the core graph global config pointer to be set
    import chain_server.src.graph as core_graph
    core_graph._config = config
    
    # StateGraph using our ExtendedState
    graph = StateGraph(ExtendedState)
    
    # Register core nodes
    graph.add_node("memory_node", GraphNodes.get_memory)
    graph.add_node("rails_input_node", GraphNodes.check_input_safety)
    graph.add_node("planner_node", planner_agent.invoke)
    graph.add_node("cart_node", cart_agent.invoke)
    graph.add_node("retriever_node", retriever_agent.invoke)
    graph.add_node("check_rail_node", GraphNodes.check_rail_node)
    graph.add_node("check_out_node", GraphNodes.check_rail_node)
    graph.add_node("passthrough_node", RunnablePassthrough())
    graph.add_node("chatter_node", chatter_agent.invoke)
    graph.add_node("rails_output_node", GraphNodes.check_output_safety)
    graph.add_node("summarize_node", summary_agent.invoke)
    graph.add_node("unsafe_output", GraphNodes.unsafe_output)

    # Register Phase 1 worker nodes
    graph.add_node("inventory_node", inventory_agent.invoke)
    graph.add_node("payment_node", payment_agent.invoke)
    graph.add_node("fulfillment_node", fulfillment_agent.invoke)

    # Register Phase 2 worker nodes
    graph.add_node("loyalty_node", loyalty_agent.invoke)
    graph.add_node("support_node", support_agent.invoke)

    # Core edges
    graph.add_edge(START, "memory_node")
    graph.add_edge("memory_node", "planner_node")
    graph.add_edge("memory_node", "rails_input_node")
    
    # Router mapping (Phase 2 supports all workers)
    graph.add_conditional_edges(
        "planner_node",
        planner_agent.decide_function,
        {
            "cart": "cart_node",
            "retriever": "retriever_node",
            "chatter": "passthrough_node",
            "inventory": "inventory_node",
            "payment": "payment_node",
            "fulfillment": "fulfillment_node",
            "loyalty": "loyalty_node",
            "support": "support_node",
        }
    )
    
    # specialist joins with input safety check
    graph.add_edge(["cart_node", "rails_input_node"], "check_rail_node")
    graph.add_edge(["retriever_node", "rails_input_node"], "check_rail_node")
    graph.add_edge(["passthrough_node", "rails_input_node"], "check_rail_node")
    graph.add_edge(["inventory_node", "rails_input_node"], "check_rail_node")
    graph.add_edge(["payment_node", "rails_input_node"], "check_rail_node")
    graph.add_edge(["fulfillment_node", "rails_input_node"], "check_rail_node")
    graph.add_edge(["loyalty_node", "rails_input_node"], "check_rail_node")
    graph.add_edge(["support_node", "rails_input_node"], "check_rail_node")
    
    # evaluate safety of inputs
    graph.add_conditional_edges("check_rail_node", GraphRouting.decide_if_input_safe)
    
    # chatter generation and output safety
    graph.add_edge("chatter_node", "rails_output_node")
    graph.add_edge("rails_output_node", "check_out_node")
    graph.add_conditional_edges("check_out_node", GraphRouting.decide_if_output_safe)
    
    # Terminations
    graph.add_edge("summarize_node", END)
    graph.add_edge("unsafe_output", END)
    
    return graph.compile()
