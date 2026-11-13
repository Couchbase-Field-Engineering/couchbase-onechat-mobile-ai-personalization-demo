"""`onechat-services` - the MCP server registered with AOM.

Streamable HTTP at /oc/mcp/. AOM ingests these tool definitions into its
vetted catalog (embeddings for discovery, RBAC per role, drift detection)
and is the only caller the demo expects: the app and the assistant reach
these tools through `POST /v1/tools/invoke`, never directly.

Business errors (out of stock, outside the return window, wrong audience)
come back as `{"ok": false, ...}` results rather than MCP errors, so AOM
records a completed call and the person gets a useful message instead of a
gateway failure.
"""
from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import actions

log = logging.getLogger("onechat.mcp")

mcp = FastMCP(
    "onechat-services",
    instructions=("Larkfield OneChat services, one tool set for the company-wide chatbot: customer orders, deliveries, "
                  "returns, exchanges, carts and goodwill credits; business lead capture and consultation booking; and the "
                  "internal IT help desk (tickets, password resets, system access) and HR (benefits, time off, onboarding)."),
    stateless_http=True,
    # Called by AOM over the Docker host gateway, so the Host header is not
    # localhost; same reasoning as AOM's own bundled sample servers.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _run(fn, **kw) -> dict:
    try:
        res = await fn(**kw)
    except actions.ToolError as exc:
        return {"ok": False, "status": "failed", "summary": str(exc)}
    return res if isinstance(res, dict) and "ok" in res else {"ok": True, "status": "ok", "data": res}


# ---- read ---------------------------------------------------------------------
@mcp.tool()
async def get_user_context(user_id: str) -> dict:
    """Read who a OneChat user is: audience (customer, business prospect or team member), loyalty or lead or employment summary, segment and next best action."""
    return await _run(actions.get_user_context, user_id=user_id)


@mcp.tool()
async def get_orders(user_id: str, order_id: str = "") -> dict:
    """List a customer's orders with status, carrier, tracking number, delivery date and window, and which items are still returnable."""
    return await _run(actions.get_orders, user_id=user_id, order_id=order_id)


@mcp.tool()
async def get_return_options(user_id: str, order_id: str = "") -> dict:
    """List a customer's delivered items with return-window eligibility, refund amount and in-stock exchange options."""
    return await _run(actions.get_return_options, user_id=user_id, order_id=order_id)


@mcp.tool()
async def get_cart(user_id: str) -> dict:
    """Read a customer's saved cart: items, stock, any recovery offer code, and the total with shipping."""
    return await _run(actions.get_cart, user_id=user_id)


@mcp.tool()
async def recommend_products(user_id: str, need: str = "") -> dict:
    """Recommend products for a user from their interests, browsing and an optional stated need; for business prospects also the workspace package sized to their team."""
    return await _run(actions.recommend_products, user_id=user_id, need=need)


@mcp.tool()
async def get_consultation_slots(user_id: str) -> dict:
    """List open workspace-consultation slots for the next business days, and any consultation already booked."""
    return await _run(actions.get_consultation_slots, user_id=user_id)


@mcp.tool()
async def get_it_context(user_id: str) -> dict:
    """Read a team member's IT picture: devices, open help-desk tickets, password expiry, system access and what they can request."""
    return await _run(actions.get_it_context, user_id=user_id)


@mcp.tool()
async def get_benefits_summary(user_id: str) -> dict:
    """Read a team member's benefits enrollment and deadline, plan options, 401(k), paid-time-off balance and next pay date."""
    return await _run(actions.get_benefits_summary, user_id=user_id)


@mcp.tool()
async def get_onboarding_tasks(user_id: str) -> dict:
    """List a new hire's onboarding paperwork: pending and completed tasks with due dates."""
    return await _run(actions.get_onboarding_tasks, user_id=user_id)


# ---- customers ------------------------------------------------------------------
@mcp.tool()
async def reschedule_delivery(user_id: str, order_id: str, date: str, window: str = "") -> dict:
    """Move a Larkfield Delivery order to another day (YYYY-MM-DD) and four-hour window (8am-12pm, 12pm-4pm, 4pm-8pm) before it is out for delivery."""
    return await _run(actions.reschedule_delivery, user_id=user_id, order_id=order_id, date=date, window=window)


@mcp.tool()
async def start_return(user_id: str, order_id: str, sku: str, reason: str, resolution: str = "refund", exchange_sku: str = "") -> dict:
    """Start a return for a delivered item inside the return window. resolution is 'refund' or 'exchange' (with exchange_sku); issues a drop-off code."""
    return await _run(actions.start_return, user_id=user_id, order_id=order_id, sku=sku, reason=reason,
                      resolution=resolution, exchange_sku=exchange_sku)


@mcp.tool()
async def issue_goodwill_credit(user_id: str, amount_usd: float, reason: str, order_id: str = "") -> dict:
    """Issue store credit (up to $150) as a service-recovery gesture for a damaged, late or out-of-window order. Requires a reason; held for supervisor approval."""
    return await _run(actions.issue_goodwill_credit, user_id=user_id, amount_usd=amount_usd, reason=reason, order_id=order_id)


@mcp.tool()
async def checkout_cart(user_id: str, apply_offer: bool = True) -> dict:
    """Place an order for everything in a customer's saved cart using the card on file, applying the cart recovery offer if it is still valid."""
    return await _run(actions.checkout_cart, user_id=user_id, apply_offer=apply_offer)


# ---- prospects ----------------------------------------------------------------------
@mcp.tool()
async def submit_lead_details(user_id: str, seats: int, budget_band: str, timeline: str, phone: str = "", interest: str = "") -> dict:
    """Capture and qualify a business lead: seats needed, budget band (under $10k, $10k-$50k, $50k-$150k, $150k+), timeline, optional phone. Scores the lead and assigns a specialist."""
    return await _run(actions.submit_lead_details, user_id=user_id, seats=seats, budget_band=budget_band, timeline=timeline,
                      phone=phone, interest=interest)


@mcp.tool()
async def book_consultation(user_id: str, date: str, time: str, topic: str = "", channel: str = "video") -> dict:
    """Book a free workspace consultation with a Larkfield for Business specialist. date YYYY-MM-DD, time HH:MM, channel video, phone or in-store."""
    return await _run(actions.book_consultation, user_id=user_id, date=date, time=time, topic=topic, channel=channel)


# ---- team members -----------------------------------------------------------------------
@mcp.tool()
async def create_it_ticket(user_id: str, category: str, summary: str, priority: str = "normal") -> dict:
    """Open an IT help desk ticket for a team member. category: access, hardware, vpn, software, email or pos; priority low, normal or high."""
    return await _run(actions.create_it_ticket, user_id=user_id, category=category, summary=summary, priority=priority)


@mcp.tool()
async def reset_password(user_id: str, system: str = "sso") -> dict:
    """Send a team member a self-service password reset to their authenticator app (requires multi-factor sign-in to be set up)."""
    return await _run(actions.reset_password, user_id=user_id, system=system)


@mcp.tool()
async def request_system_access(user_id: str, system: str, justification: str) -> dict:
    """Grant a team member access to a standard system (vpn, pos) with a business justification."""
    return await _run(actions.request_system_access, user_id=user_id, system=system, justification=justification)


@mcp.tool()
async def request_privileged_access(user_id: str, system: str, justification: str) -> dict:
    """Grant a team member access to a privileged system holding customer, financial or production data (analytics, erp-finance, crm-admin, prod-db). Requires a justification; held for approval."""
    return await _run(actions.request_privileged_access, user_id=user_id, system=system, justification=justification)


@mcp.tool()
async def request_time_off(user_id: str, start_date: str, end_date: str, note: str = "") -> dict:
    """Request paid time off for a team member (dates YYYY-MM-DD); checks the balance and sends it to their manager."""
    return await _run(actions.request_time_off, user_id=user_id, start_date=start_date, end_date=end_date, note=note)


@mcp.tool()
async def enroll_benefits(user_id: str, medical: str, dental: str = "", vision: str = "", k401_pct: int = -1) -> dict:
    """Enroll a new hire in benefits within their 30-day window: medical (MED-CORE, MED-HSA, MED-PLUS), optional dental (DEN-BASE, DEN-PLUS), vision (VIS-STD) and 401(k) percent."""
    return await _run(actions.enroll_benefits, user_id=user_id, medical=medical, dental=dental, vision=vision, k401_pct=k401_pct)


@mcp.tool()
async def complete_onboarding_task(user_id: str, task_id: str, acknowledgment: str = "") -> dict:
    """Complete a new-hire onboarding task (i9, w4, direct-deposit, handbook, code-of-conduct, security-training, emergency-contact). Sign tasks need the person's typed name."""
    return await _run(actions.complete_onboarding_task, user_id=user_id, task_id=task_id, acknowledgment=acknowledgment)
