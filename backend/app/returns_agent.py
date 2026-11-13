"""OneChat Returns Agent - the second AOM agent identity in the demo.

It is triggered by **Confirm** on the Return screen (or a goodwill-credit
button in chat): the phone writes a `requests` document (`start_return` or
`issue_goodwill_credit`), and the worker hands either tool to this agent
instead of the assistant. One return = one AOM run, attributed to the
*OneChat Returns Agent* on AOM's Agents, Traces and Audit pages, scoped to
the five order-and-return tools only - it cannot touch a lead, a ticket or
anything in HR.

What makes it an agent rather than a tool call is **AOM Agent Memory**:

1. Before processing it recalls what AOM already remembers about this
   customer's returns (`POST /v1/memory/search`): earlier returns and
   exchanges, credits, and anything they told OneChat about fit or sizing.
2. After the return is processed it writes an episodic memory
   (`POST /v1/memory`) - what went back, from which order, why, and whether
   it was refunded, exchanged (for what) or credited - plus a semantic
   preference memory when the reason shows one ("found the 60-inch desk too
   large for the room").

The assistant recalls the same memories on its next turn, so "recommend me
a desk" is answered knowing the last one was too big.
"""
from __future__ import annotations

import logging

from . import tool_gateway
from .aom_client import AOMError, returns_aom
from .docs import profile_id
from .store import store

log = logging.getLogger("onechat.returns_agent")

AGENT_ID = "onechat-returns-agent"
AGENT_NAME = "OneChat Returns Agent"
TOOLS = ["get_user_context", "get_orders", "get_return_options", "start_return", "issue_goodwill_credit"]
# Tools the worker routes to this agent (the request documents a Confirm creates).
TRIGGER_TOOLS = {"start_return", "issue_goodwill_credit"}
DESCRIPTION = ("Larkfield returns and exchanges agent. Triggered when a customer confirms a return, an exchange or a "
               "goodwill credit in the OneChat mobile app: recalls the customer's return history and stated preferences "
               "from Agent Memory, processes the return as a governed tool call, and remembers the outcome for the assistant.")


def enabled() -> bool:
    return returns_aom.enabled


async def recall(user_id: str) -> list[str]:
    if not enabled():
        return []
    try:
        res = await returns_aom.memory_search(user_id, "return exchange refund credit size fit preference", top_k=4)
        return [e.get("content", "") for e in res.get("entries", []) if e.get("content")]
    except AOMError as exc:
        log.info("memory search skipped: %s", exc)
        return []


def _episode(tool: str, profile: dict, args: dict, result: dict) -> str:
    item = result.get("item") or {}
    tier = (profile.get("loyalty") or {}).get("tier")
    if tool == "issue_goodwill_credit":
        what = (f"received a ${item.get('amount_usd', args.get('amount_usd')):,.0f} goodwill store credit approved by customer care"
                + (f" on order {item['order_id']}" if item.get("order_id") else "") + f" - reason: {item.get('reason') or args.get('reason')}")
    else:
        rec = next((r for r in profile.get("returns", []) if r.get("return_id") == item.get("return_id")), {})
        name = rec.get("name") or args.get("sku")
        if item.get("resolution") == "exchange":
            what = f"exchanged {name} (order {item.get('order_id')}) for {item.get('exchange_name')} - reason: {item.get('reason')}"
        else:
            what = (f"returned {name} (order {item.get('order_id')}) for a ${item.get('refund_usd') or 0:,.0f} refund - reason: "
                    f"{item.get('reason')}")
    return f"Return history: {what}." + (f" Customer is a {tier} member." if tier else "")


def _preference(args: dict, result: dict) -> str | None:
    reason = ((result.get("item") or {}).get("reason") or args.get("reason") or "").strip()
    name = (result.get("item") or {}).get("title", "").split("·")[-1].strip()
    low = reason.lower()
    if any(k in low for k in ("size", "fit", "large", "small", "big", "tall", "narrow", "wide", "colour", "color")) and name:
        return f"Product preferences: found {name} wasn't right - {reason}."
    return None


async def run(doc: dict, args: dict, approval_id: str | None = None) -> dict:
    """Process a return request as the Returns Agent. Returns the tool result
    plus `agent`, `memories_recalled` and `remembered`."""
    user_id = doc.get("user_id")
    tool = doc.get("tool")
    memories = await recall(user_id)
    result = await tool_gateway.invoke(tool, args, approval_id=approval_id, client=returns_aom if enabled() else None)
    result.update({"agent": AGENT_ID, "memories_recalled": len(memories), "remembered": False})

    if result.get("ok") and result.get("status") in ("ok", "confirmed", "accepted", "submitted") and enabled():
        try:
            after = await store.get("profiles", profile_id(user_id)) or {}
            await returns_aom.memory_add(
                user_id, _episode(tool, after, args, result), session_id=doc.get("session_id"), memory_type="episodic",
                metadata={"agent": AGENT_ID, "tool": tool, "order_id": args.get("order_id"),
                          "trace_id": result.get("trace_id"), "app": "onechat-mobile"})
            pref = _preference(args, result)
            if pref:
                await returns_aom.memory_add(user_id, pref, memory_type="semantic", metadata={"agent": AGENT_ID, "app": "onechat-mobile"})
            result["remembered"] = True
        except AOMError as exc:
            log.info("memory add skipped: %s", exc)
    if memories and result.get("summary"):
        last = next((m for m in memories if m.startswith("Return history:")), None)
        if last:
            result["summary"] += f" (The returns agent remembered: {last[len('Return history: '):].rstrip('.')}.)"
    return result
