"""The real LangGraph runtime, with durable interrupts keyed by run ID."""
from contextlib import contextmanager

from .types import EditorialState


@contextmanager
def open_graph(workflow, home):
    # Lazy imports keep adapters and editorial rules independently testable.
    from .checkpoints import SQLiteSaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    def editor(state):
        decision = interrupt({"run_id": state["run_id"], "pitches": state["pitches"],
                              "message": "Select a pitch, revise its question, or dismiss this run."})
        return workflow.select(state, decision)

    builder = StateGraph(EditorialState)
    for name in ("discover", "pitch", "research_start", "research_search", "extract", "draft", "verify", "export"):
        builder.add_node(name, getattr(workflow, name))
    builder.add_node("editor", editor)
    builder.add_edge(START, "discover")
    builder.add_edge("discover", "pitch")
    builder.add_conditional_edges("pitch", lambda s: "editor" if s["pitches"] else END)
    builder.add_conditional_edges("editor", lambda s: END if s["status"] == "dismissed" else "research_start")
    builder.add_conditional_edges("research_start", lambda s: "research_search" if s["research_budget"] else "extract")
    builder.add_conditional_edges("research_search", lambda s: "research_search"
                                  if not s.get("research_done") and s["searches_used"] < s["research_budget"] else "extract")
    builder.add_edge("extract", "draft")
    builder.add_edge("draft", "verify")
    builder.add_edge("verify", "export")
    builder.add_edge("export", END)
    saver = SQLiteSaver(str(home / "checkpoints.sqlite"))
    try:
        yield builder.compile(checkpointer=saver)
    finally:
        saver.close()


def graph_config(run_id):
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 100}


def is_interrupted(snapshot):
    return any(task.interrupts for task in snapshot.tasks)
