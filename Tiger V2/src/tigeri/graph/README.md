# LangGraph + session memory pattern

Every Tigeri agent (going forward) is a LangGraph workflow. This directory is the shared scaffolding.

## Layout

- `state.py` — `BaseAgentState` and `SessionContext` TypedDicts. Every agent extends `BaseAgentState`.
- `base.py` — `BaseGraphAgent`. Subclasses implement `build_graph()` and call `run_graph()`.
- `checkpointer.py` — picks `MemorySaver` (in-process) or `PostgresSaver` based on `TIGERI_SESSION_CHECKPOINTER`.
- `llm.py` — `agent_llm()` and `reasoning_llm()` factories built on `langchain_anthropic.ChatAnthropic`.
- `tracing.py` — wires LangSmith from `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` / `LANGSMITH_TRACING`.

## Author a new agent in five steps

1. Define a state TypedDict that extends `BaseAgentState` with your per-agent fields.
2. Subclass `BaseGraphAgent`. Set `agent_id` and `state_schema`.
3. Implement `build_graph()` returning a `StateGraph`. Each catalog capability is a node; conditional edges branch on outcomes (validation failure, policy denial).
4. Inside each node, write back to `state["session"]["behaviour"]` to record per-user signals you want remembered (e.g. rejection streak, last fee tier hit). The checkpointer persists this between calls keyed by `tenant_id:user_id:session_id`.
5. Mirror existing audit calls — call `self.audit(...)` at the end of every node.

## Reference implementation

[`tigeri/agents/invoice/graph_agent.py`](../agents/invoice/graph_agent.py) — Invoice Agent rebuilt as a LangGraph workflow:

- 6 catalog capabilities → 6 graph nodes
- conditional edge after `validate` skips routing/posting on `REJECTED`
- writes `behaviour.rejection_streak` and `behaviour.last_validation` to session memory on every run
- exposed via the same `POST /agents/invoice_agent/invoke` endpoint, with `X-Tigeri-User-Id` and `X-Tigeri-Session-Id` headers driving the checkpoint thread
- `X-Tigeri-Engine: legacy` falls back to the original imperative implementation, useful while migrating

## Session memory model

```
thread_id = f"{tenant_id}:{user_id}:{session_id}"
state["session"] = {
    "tenant_id": "...",
    "user_id": "...",
    "session_id": "...",
    "invocations": <int — incremented every call>,
    "behaviour": { ...arbitrary signals you record... },
}
```

`MemorySaver` (default) keeps this in process RAM — perfect for slice 1 / dev. Set `TIGERI_SESSION_CHECKPOINTER=postgres` to swap in `PostgresSaver` (table created automatically by `setup()` at first use). Same DSN as the rest of the app.

## LangSmith tracing

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY=...` in `.env`. The runtime calls `configure_langsmith()` at FastAPI startup and `BaseGraphAgent.__init__`. Every graph invocation appears in the LangSmith project named by `LANGSMITH_PROJECT` (default `tigeri`). Disable by leaving `LANGSMITH_TRACING=false`.

## Migration plan for the other agents

| Priority | Agent | Plan |
|----------|-------|------|
| 2 | Expense | One graph node per source-catalog capability (scan → extract → categorise → policy_check → reconcile → submit). Behaviour signal: `policy_violation_streak`. |
| 3 | Admin | Nodes follow template steps; conditional branch on subject type (employee vs contractor). Behaviour signal: `pending_workflows`. |
| 4 | Staffing | Nodes: generate_roster → publish_roster → detect_gap → source_cover → confirm_cover → notify. Behaviour signal: `recurring_gap_venues`. |
| 5 | Booking | Nodes: accept → resolve_availability → confirm → notify → reschedule_or_cancel → surface_utilisation. Behaviour signal: `decline_streak_per_venue`. |
| 6+ | All | Same pattern — schema + graph + behaviour signals. |

Until each agent is migrated, the imperative class in `agents/<name>/agent.py` stays as the live implementation. The graph variants land alongside (`graph_agent.py`) and are flag-flipped per route.
