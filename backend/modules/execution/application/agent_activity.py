"""User-visible agent activity, shared by history and event snapshots."""
from copy import deepcopy

TEXT_LIMIT = 100000


def reduce_activity(state, kind, payload):
    state = deepcopy(state or {})
    if kind == "agent.item":
        items = state.setdefault("items", {})
        key = str(payload.get("id") or "unknown")
        item = {**items.get(key, {}), **payload}
        if "delta" in payload:
            item["text"] = str(items.get(key, {}).get("text", "")) + str(payload["delta"])
        if "summary_delta" in payload:
            summary = list(items.get(key, {}).get("summary") or [])
            index = min(max(int(payload.get("summary_index") or 0), 0), 100)
            summary.extend([""] * (index + 1 - len(summary)))
            summary[index] = (summary[index] + str(payload["summary_delta"]))[-TEXT_LIMIT:]
            item["summary"] = summary
        for field in ("delta", "summary_delta", "summary_index"):
            item.pop(field, None)
        items[key] = item
    elif kind == "agent.tool":
        tools = state.setdefault("tools", {})
        key = str(payload.get("id") or "unknown")
        tool = {**tools.get(key, {}), **payload}
        if "delta" in payload:
            tool["output"] = (tools.get(key, {}).get("output", "") + str(payload["delta"]))[-TEXT_LIMIT:]
        tools[key] = tool
    elif kind == "agent.warning":
        state["warnings"] = [*state.get("warnings", []), payload][-30:]
    elif kind in {"agent.plan", "agent.diff", "agent.usage", "agent.session"}:
        state[kind.split(".")[1]] = payload
    return state


def project_activity(run, *, after_sequence=0, through_sequence=None):
    state = {}
    events = run.events.filter(type__startswith="agent.", sequence__gt=after_sequence)
    if through_sequence is not None:
        events = events.filter(sequence__lte=through_sequence)
    for event in events.order_by("sequence"):
        state = reduce_activity(state, event.type, event.payload)
    return state
