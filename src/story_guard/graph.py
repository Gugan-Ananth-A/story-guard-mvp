"""Code-node graph. Later slices add the rest of the node list in this module."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class GraphState(TypedDict, total=False):
    graph: str


def ping(state: GraphState) -> dict[str, str]:
    return {"graph": "ok"}


def build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("ping", ping)
    builder.add_edge(START, "ping")
    builder.add_edge("ping", END)
    return builder.compile()


def run(state: GraphState | None = None) -> GraphState:
    return build_graph().invoke(state or {})
