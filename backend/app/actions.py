"""OneChat actions - the business logic behind every MCP tool.

These functions are what actually changes state (orders, returns, carts,
leads, consultations, tickets, access, time off, benefits, onboarding). They
are only ever reached through `tool_gateway`, which routes them through the
Couchbase Agent Operations Manager when it is configured (RBAC, approvals,
tracing, audit) and calls them in-process otherwise. Every mutation bumps
the person's profile `rev`, which is what invalidates their context cache
and re-ranks their For You feed.

Each tool checks the caller's audience itself: a customer can't open an IT
ticket and a team member's HR tools never run for a prospect, whatever the
agent was asked to do.
"""
from __future__ import annotations

import datetime as dt
import uuid

from . import catalog as C
from .docs import INVENTORY_ID, activity_id, days_since, days_until, money, nice_date, now_iso, profile_id, today, user_channel
from .store import store


class ToolError(Exception):
    pass


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
async def load_profile(user_id: str) -> dict:
    p = await store.get("profiles", profile_id(user_id))
    if not p:
        raise ToolError(f"No profile for '{user_id}'")
    return p


def require(profile: dict, *audiences: str):
    if profile.get("audience") not in audiences:
        who = {"customer": "customers", "lead": "business prospects", "employee": "Larkfield team members"}
        raise ToolError("This is only available to " + " and ".join(who[a] for a in audiences))


async def save_profile(p: dict):
    p["rev"] = int(p.get("rev", 0)) + 1
    p["updated_at"] = now_iso()
    await store.upsert("profiles", profile_id(p["user_id"]), p)
    from .loader import mark_live  # late import: loader -> personalization -> actions
    await mark_live(p["user_id"])


async def record_activity(user_id: str, item: dict):
    doc = await store.get("activity", activity_id(user_id)) or {
        "type": "activity", "user_id": user_id, "items": [], "channels": [user_channel(user_id)]}
    doc["items"] = [i for i in doc["items"] if i.get("item_id") != item["item_id"]] + [item]
    doc["updated_at"] = now_iso()
    await store.upsert("activity", activity_id(user_id), doc)


async def after_change(user_id: str):
    # late imports: personalization/assistant import this module
    from . import assistant, personalization
    await personalization.refresh_feed(user_id)
    await assistant.invalidate_context(user_id)


async def get_inventory() -> tuple[dict, int]:
    doc, cas = await store.get_with_cas("inventory", INVENTORY_ID)
    if doc is None:
        await store.insert("inventory", INVENTORY_ID, {"type": "inventory", **C.initial_inventory(today()), "created_at": now_iso()})
        doc, cas = await store.get_with_cas("inventory", INVENTORY_ID)
    return doc, cas


async def take(kind: str, key: str, what: str):
    """Take one unit of stock or one consultation seat (CAS: two phones can't
    both get the last one)."""
    for _ in range(10):
        doc, cas = await get_inventory()
        if doc[kind].get(key, 0) <= 0:
            raise ToolError(what)
        doc[kind][key] -= 1
        if await store.replace_cas("inventory", INVENTORY_ID, doc, cas):
            return doc[kind][key]
    raise ToolError("That's busy right now - please try again")


def _item(kind: str, title: str, **kw) -> dict:
    return {"item_id": f"{kind}-{uuid.uuid4().hex[:10]}", "kind": kind, "title": title, "status": "confirmed",
            "date": today().isoformat(), "created_at": now_iso(), **kw}


def _order(p: dict, order_id: str) -> dict:
    o = next((o for o in p.get("orders", []) if o["order_id"] == order_id), None)
    if not o:
        raise ToolError(f"I can't find order {order_id} on this account")
    return o


def _first(p: dict) -> str:
    return p["first_name"]


def return_status(p: dict, order: dict, item: dict) -> dict:
    """Is this delivered item still returnable, and for how much longer?"""
    window = C.return_window_days(p.get("loyalty", {}).get("tier"))
    since = days_since(order.get("delivered_at"))
    returned = any(r["order_id"] == order["order_id"] and r["sku"] == item["sku"] for r in p.get("returns", []))
    eligible = order["status"] == "delivered" and since is not None and since <= window and not returned
    return {"window_days": window, "days_since_delivery": since, "days_left": (window - since) if since is not None else None,
            "eligible": eligible, "already_returned": returned}


# --------------------------------------------------------------------------
# read tools
# --------------------------------------------------------------------------
async def get_user_context(user_id: str) -> dict:
    p = await load_profile(user_id)
    out = {"user_id": user_id, "audience": p["audience"], "name": f"{p['first_name']} {p['last_name']}",
           "home_city": p.get("home_city"), "segment": p["ml_scores"].get("segment"),
           "next_best_action": p["ml_scores"].get("next_best_action"), "preferences": p.get("preferences")}
    if p["audience"] == "customer":
        open_orders = [o for o in p["orders"] if o["status"] in ("processing", "shipped", "out_for_delivery")]
        out.update({"loyalty": p["loyalty"], "open_orders": len(open_orders), "orders_total": p["history"]["orders_count"],
                    "cart_items": len((p.get("cart") or {}).get("items", [])),
                    "store_credit_usd": sum(c["amount_usd"] for c in p.get("credits", []))})
    elif p["audience"] == "lead":
        out.update({"company": p["company"], "lead": p["lead"], "consultation": p.get("consultation"),
                    "recommended_bundle": p["ml_scores"].get("recommended_bundle")})
    else:
        e = p["employment"]
        out.update({"employment": {k: e[k] for k in ("title", "department", "manager", "location", "start_date")},
                    "onboarding_pending": sum(1 for t in p["onboarding"]["tasks"] if t["status"] != "complete"),
                    "open_tickets": len(p["it"]["open_tickets"]), "benefits_enrolled": p["hr"]["benefits"]["enrolled"]})
    return out


async def get_orders(user_id: str, order_id: str = "") -> dict:
    p = await load_profile(user_id)
    require(p, "customer")
    orders = []
    for o in p["orders"]:
        if order_id and o["order_id"] != order_id:
            continue
        eta_days = days_until(o.get("eta"))
        orders.append({**o, "eta_in_days": eta_days,
                       "can_reschedule": o["status"] in ("processing", "shipped") and o["carrier"] == "Larkfield Delivery",
                       "returnable_items": [i["sku"] for i in o["items"] if return_status(p, o, i)["eligible"]]})
    if order_id and not orders:
        raise ToolError(f"I can't find order {order_id} on this account")
    orders.sort(key=lambda o: o["placed_at"], reverse=True)
    return {"user_id": user_id, "orders": orders, "open": [o["order_id"] for o in orders if o["status"] in ("processing", "shipped", "out_for_delivery")]}


async def get_return_options(user_id: str, order_id: str = "") -> dict:
    p = await load_profile(user_id)
    require(p, "customer")
    inv, _ = await get_inventory()
    items = []
    for o in p["orders"]:
        if o["status"] != "delivered" or (order_id and o["order_id"] != order_id):
            continue
        for i in o["items"]:
            st = return_status(p, o, i)
            if st["already_returned"]:
                continue
            items.append({"order_id": o["order_id"], "sku": i["sku"], "name": i["name"], "price": i["price"],
                          "delivered_at": o["delivered_at"], **st, "refund_usd": i["price"],
                          "exchange_options": [{"sku": x["sku"], "name": x["name"], "price": x["price"],
                                                "in_stock": inv["stock"].get(x["sku"], 0),
                                                "price_difference_usd": x["price"] - i["price"]}
                                               for x in C.exchange_options(i["sku"])]})
    items.sort(key=lambda i: (not i["eligible"], i["days_since_delivery"] or 0))
    return {"user_id": user_id, "tier": p["loyalty"]["tier"], "window_days": C.return_window_days(p["loyalty"]["tier"]),
            "items": items, "reasons": C.RETURN_REASONS, "past_returns": p.get("returns", [])[-5:],
            "store_credit_usd": sum(c["amount_usd"] for c in p.get("credits", []))}


async def get_cart(user_id: str) -> dict:
    p = await load_profile(user_id)
    require(p, "customer")
    cart = p.get("cart")
    if not cart or not cart.get("items"):
        return {"user_id": user_id, "cart": None, "summary": "The cart is empty."}
    inv, _ = await get_inventory()
    offer = cart.get("offer")
    valid = bool(offer and (days_until(offer["expires"]) or 0) >= 0)
    sub = cart["subtotal_usd"]
    discount = round(sub * offer["pct_off"] / 100, 2) if valid else 0
    shipping = 0 if sub - discount >= C.FREE_SHIPPING_MIN else C.STANDARD_SHIPPING
    return {"user_id": user_id, "cart": {**cart, "items": [{**i, "in_stock": inv["stock"].get(i["sku"], 0)} for i in cart["items"]]},
            "offer_valid": valid, "offer_days_left": days_until(offer["expires"]) if valid else None,
            "discount_usd": discount, "shipping_usd": shipping, "total_usd": round(sub - discount + shipping, 2),
            "low_stock": [i["name"] for i in cart["items"] if inv["stock"].get(i["sku"], 0) <= 3]}


async def recommend_products(user_id: str, need: str = "") -> dict:
    p = await load_profile(user_id)
    likes = set(p.get("preferences", {}).get("interests", []))
    words = set(need.lower().replace(",", " ").split())
    owned = {i["sku"] for o in p.get("orders", []) for i in o["items"]} | {i["sku"] for i in (p.get("cart") or {}).get("items", [])}
    viewed = set((p.get("browsing") or {}).get("viewed_skus", []))
    picks = set(p["ml_scores"].get("recommended_skus", []))
    out = []
    for prod in C.PRODUCTS:
        if prod["sku"] in owned:
            continue
        match = sorted(likes & set(prod["tags"]))
        asked = sorted(w for w in words if w in prod["tags"] or w in prod["name"].lower() or w in prod["category"].lower())
        score = 0.3 * len(match) + 0.6 * len(asked) + (0.35 if prod["sku"] in picks else 0) + (0.2 if prod["sku"] in viewed else 0)
        if score > 0:
            out.append({**prod, "matched_interests": match, "matched_need": asked, "recently_viewed": prod["sku"] in viewed,
                        "score": round(score, 2)})
    out.sort(key=lambda x: (-x["score"], x["price"]))
    res = {"user_id": user_id, "products": out[:6]}
    if p["audience"] == "lead":
        seats = p["lead"].get("seats") or p["company"]["employees"]
        b = C.bundle_for_seats(seats)
        res["bundle"] = {**b, "seats": list(b["seats"]), "estimated_seats": seats, "estimate_usd": b["price_per_seat"] * seats}
    return res


async def get_consultation_slots(user_id: str) -> dict:
    p = await load_profile(user_id)
    require(p, "customer", "lead")
    inv, _ = await get_inventory()
    days: dict[str, list] = {}
    for sid, left in sorted(inv["slots"].items()):
        date, time = sid.split("T")
        if (days_until(date) or 0) < 1:
            continue
        days.setdefault(date, []).append({"time": time, "open": left})
    return {"user_id": user_id, "booked": p.get("consultation"), "topics": C.CONSULT_TOPICS, "channels": C.CONSULT_CHANNELS,
            "days": [{"date": d, "slots": s} for d, s in list(days.items())[:6]],
            "qualified": (p.get("lead") or {}).get("status") in ("qualified", "consult_booked")}


async def get_it_context(user_id: str) -> dict:
    p = await load_profile(user_id)
    require(p, "employee")
    it = p["it"]
    have = set(it["systems_access"])
    return {"user_id": user_id, "devices": it["devices"], "open_tickets": it["open_tickets"],
            "password_expires_in_days": it["password_expires_in_days"], "mfa_enrolled": it["mfa_enrolled"],
            "systems_access": [C.SYSTEM_BY_ID[s]["name"] for s in it["systems_access"] if s in C.SYSTEM_BY_ID],
            "requestable": [{"id": s["id"], "name": s["name"], "needs_approval": s["approval"]} for s in C.SYSTEMS if s["id"] not in have],
            "pending_access": [r for r in it.get("access_requests", []) if r.get("status") == "pending"],
            "categories": C.IT_CATEGORIES}


async def get_benefits_summary(user_id: str) -> dict:
    p = await load_profile(user_id)
    require(p, "employee")
    b = p["hr"]["benefits"]
    plan = lambda pid: ({"id": pid, "name": C.PLAN_BY_ID[pid]["name"], "cost_per_paycheck": C.PLAN_BY_ID[pid]["employee_cost_per_paycheck"]} if pid else None)  # noqa: E731
    return {"user_id": user_id, "enrolled": b["enrolled"], "enrollment_deadline": b.get("enrollment_deadline"),
            "days_to_enroll": days_until(b.get("enrollment_deadline")),
            "medical": plan(b.get("medical")), "dental": plan(b.get("dental")), "vision": plan(b.get("vision")),
            "k401_pct": b.get("k401_pct", 0), "k401_match_pct": C.K401_MATCH_PCT, "plans": C.BENEFIT_PLANS,
            "pto": p["hr"]["pto"], "pay": p["hr"]["pay"], "start_date": p["employment"]["start_date"]}


async def get_onboarding_tasks(user_id: str) -> dict:
    p = await load_profile(user_id)
    require(p, "employee")
    tasks = [{**t, "detail": C.ONBOARDING_BY_ID[t["task_id"]]["detail"], "due_in_days": days_until(t["due_date"])}
             for t in p["onboarding"]["tasks"]]
    pending = [t for t in tasks if t["status"] != "complete"]
    pending.sort(key=lambda t: t["due_date"])
    return {"user_id": user_id, "status": p["onboarding"]["status"], "start_date": p["employment"]["start_date"],
            "manager": p["employment"]["manager"], "pending": pending, "completed": [t for t in tasks if t["status"] == "complete"],
            "next_due": pending[0] if pending else None}


# --------------------------------------------------------------------------
# customers: orders, returns, cart
# --------------------------------------------------------------------------
async def reschedule_delivery(user_id: str, order_id: str, date: str, window: str = "") -> dict:
    p = await load_profile(user_id)
    require(p, "customer")
    o = _order(p, order_id)
    if o["status"] not in ("processing", "shipped"):
        raise ToolError(f"Order {order_id} is {o['status'].replace('_', ' ')}, so its delivery can't be moved")
    if o["carrier"] != "Larkfield Delivery":
        raise ToolError(f"Order {order_id} ships with {o['carrier']}; use their tracking page to redirect it")
    window = window or o.get("delivery_window") or C.DELIVERY_WINDOWS[0]
    if window not in C.DELIVERY_WINDOWS:
        raise ToolError(f"Delivery windows: {', '.join(C.DELIVERY_WINDOWS)}")
    try:
        new = dt.date.fromisoformat(date)
    except ValueError:
        raise ToolError("Date must be YYYY-MM-DD") from None
    eta = dt.date.fromisoformat(o["eta"])
    if not (eta <= new <= eta + dt.timedelta(days=10)) or new <= today():
        raise ToolError(f"Pick a day from {max(eta, today() + dt.timedelta(days=1)).isoformat()} to {(eta + dt.timedelta(days=10)).isoformat()}")
    o.update(eta=new.isoformat(), delivery_window=window)
    o["events"].append({"at": today().isoformat(), "text": f"Delivery rescheduled to {new.isoformat()}, {window}"})
    await save_profile(p)
    item = _item("delivery", f"Delivery moved · {order_id}", order_id=order_id, date=new.isoformat(), time=window)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"Done - order {order_id} now arrives {nice_date(new.isoformat())} between {window}. We'll text you when the driver is 30 minutes away."}


async def start_return(user_id: str, order_id: str, sku: str, reason: str, resolution: str = "refund", exchange_sku: str = "") -> dict:
    p = await load_profile(user_id)
    require(p, "customer")
    o = _order(p, order_id)
    i = next((i for i in o["items"] if i["sku"] == sku), None)
    if not i:
        raise ToolError(f"{sku} isn't on order {order_id}")
    st = return_status(p, o, i)
    if st["already_returned"]:
        raise ToolError(f"A return for {i['name']} is already in progress")
    if o["status"] != "delivered":
        raise ToolError(f"{i['name']} hasn't been delivered yet - you can start a return once it arrives")
    if not st["eligible"]:
        raise ToolError(f"{i['name']} was delivered {st['days_since_delivery']} days ago, outside your {st['window_days']}-day return window")
    if not reason or len(reason.strip()) < 3:
        raise ToolError("A return needs a reason")
    if resolution not in ("refund", "exchange"):
        raise ToolError("Resolution must be 'refund' or 'exchange'")
    rid = f"RMA-{uuid.uuid4().hex[:8].upper()}"
    rec = {"return_id": rid, "order_id": order_id, "sku": sku, "name": i["name"], "reason": reason.strip()[:200],
           "resolution": resolution, "status": "label_issued", "created_at": today().isoformat(),
           "drop_off": "Any Larkfield store or UPS location", "label_code": f"LF{uuid.uuid4().hex[:6].upper()}"}
    if resolution == "exchange":
        x = C.PRODUCT_BY_SKU.get(exchange_sku)
        if not x or exchange_sku not in [e["sku"] for e in C.exchange_options(sku)]:
            raise ToolError(f"{i['name']} can't be exchanged for '{exchange_sku}'")
        await take("stock", exchange_sku, f"{x['name']} is out of stock - choose another option or a refund")
        diff = x["price"] - i["price"]
        rec.update(exchange_sku=exchange_sku, exchange_name=x["name"], price_difference_usd=diff, ships_by=(today() + dt.timedelta(days=2)).isoformat())
        summary = (f"Exchange started: {i['name']} for {x['name']}. Your replacement ships by {nice_date(rec['ships_by'])}"
                   + (f"; {money(diff)} will be charged to your card on file." if diff > 0 else f"; {money(-diff)} goes back to your card." if diff < 0 else ".")
                   + f" Drop the original at any Larkfield store or UPS with code {rec['label_code']}.")
        charge = max(diff, 0)
    else:
        rec.update(refund_usd=i["price"])
        summary = (f"Return started for {i['name']}. Drop it at any Larkfield store or UPS with code {rec['label_code']} - "
                   f"{money(i['price'])} goes back to your card within 3 business days of the scan.")
        charge = 0
    p.setdefault("returns", []).append(rec)
    p["history"]["returns_count"] = int(p["history"].get("returns_count", 0)) + 1
    await save_profile(p)
    item = _item("exchange" if resolution == "exchange" else "return", f"{'Exchange' if resolution == 'exchange' else 'Return'} · {i['name']}",
                 order_id=order_id, sku=sku, return_id=rid, resolution=resolution, reason=rec["reason"], label_code=rec["label_code"],
                 refund_usd=rec.get("refund_usd"), exchange_name=rec.get("exchange_name"), charge_usd=charge)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "charge_usd": charge, "item": item, "summary": summary}


async def issue_goodwill_credit(user_id: str, amount_usd: float, reason: str, order_id: str = "") -> dict:
    """Store credit as a service-recovery gesture (late or damaged order, an
    item just outside the return window). Held for a human decision in AOM's
    approval tier before it can run."""
    if not reason or len(reason.strip()) < 5:
        raise ToolError("A goodwill credit needs a reason for the audit trail")
    amount = round(float(amount_usd), 2)
    if amount <= 0 or amount > C.GOODWILL_CREDIT_MAX:
        raise ToolError(f"Goodwill credits are between $1 and {money(C.GOODWILL_CREDIT_MAX)}")
    p = await load_profile(user_id)
    require(p, "customer")
    if order_id:
        _order(p, order_id)
    credit = {"credit_id": f"CR-{uuid.uuid4().hex[:8].upper()}", "amount_usd": amount, "reason": reason.strip()[:300],
              "order_id": order_id or None, "issued_at": today().isoformat(), "expires": (today() + dt.timedelta(days=365)).isoformat()}
    p.setdefault("credits", []).append(credit)
    await save_profile(p)
    item = _item("credit", f"Store credit · {money(amount)}", amount_usd=amount, order_id=order_id or None, reason=credit["reason"])
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "charge_usd": 0, "item": item,
            "summary": f"A {money(amount)} store credit is on your account, good for a year. Reason recorded: {reason.strip()[:120]}"}


async def checkout_cart(user_id: str, apply_offer: bool = True) -> dict:
    p = await load_profile(user_id)
    require(p, "customer")
    cart = p.get("cart")
    if not cart or not cart.get("items"):
        raise ToolError("Your cart is empty")
    offer = cart.get("offer")
    valid = bool(apply_offer and offer and (days_until(offer["expires"]) or 0) >= 0)
    for i in cart["items"]:
        await take("stock", i["sku"], f"{i['name']} just sold out - remove it from your cart to check out")
    sub = cart["subtotal_usd"]
    discount = round(sub * offer["pct_off"] / 100, 2) if valid else 0
    shipping = 0 if sub - discount >= C.FREE_SHIPPING_MIN else C.STANDARD_SHIPPING
    total = round(sub - discount + shipping, 2)
    eta = C.business_days(today(), 3)[-1].isoformat()
    big = any(C.PRODUCT_BY_SKU[i["sku"]]["category"] in ("Desks", "Chairs", "Storage") for i in cart["items"])
    order = {"order_id": f"LF-{900000 + C._h(user_id, p.get('rev', 0)) % 90000}", "placed_at": today().isoformat(), "status": "processing",
             "items": cart["items"], "subtotal_usd": sub, "discount_usd": discount, "offer_code": offer["code"] if valid else None,
             "shipping_usd": shipping, "total_usd": total, "carrier": "Larkfield Delivery" if big else "UPS",
             "tracking_number": None, "eta": eta, "delivery_window": C.DELIVERY_WINDOWS[1] if big else None, "delivered_at": None,
             "ship_to_city": p.get("home_city"), "events": [{"at": today().isoformat(), "text": "Order placed in OneChat"}]}
    p["orders"].insert(0, order)
    p["cart"] = None
    p["history"]["orders_count"] = int(p["history"].get("orders_count", 0)) + 1
    p["loyalty"]["points"] = int(p["loyalty"].get("points", 0)) + int(total)
    await save_profile(p)
    item = _item("order", f"Order {order['order_id']} · {len(order['items'])} item{'s' if len(order['items']) > 1 else ''}",
                 order_id=order["order_id"], charge_usd=total, date=eta)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "charge_usd": total, "item": item,
            "summary": f"Order {order['order_id']} is placed: {', '.join(i['name'] for i in order['items'])}. "
                       + (f"{offer['code']} saved you {money(discount)}. " if valid else "")
                       + f"{money(total)} charged to your card on file; arriving {nice_date(eta)}."}


# --------------------------------------------------------------------------
# prospects: lead capture, qualification, consultations
# --------------------------------------------------------------------------
async def submit_lead_details(user_id: str, seats: int, budget_band: str, timeline: str, phone: str = "", interest: str = "") -> dict:
    p = await load_profile(user_id)
    require(p, "lead")
    seats = int(seats)
    if seats < 1 or seats > 5000:
        raise ToolError("Seats must be between 1 and 5,000")
    if budget_band not in C.BUDGET_BANDS:
        raise ToolError(f"Budget: {', '.join(C.BUDGET_BANDS)}")
    if timeline not in C.TIMELINES:
        raise ToolError(f"Timeline: {', '.join(C.TIMELINES)}")
    lead = p["lead"]
    # Qualification the way a sales-development rep would score it.
    score = 0.35 + (0.2 if seats >= 16 else 0.05) + {"under $10k": 0.0, "$10k-$50k": 0.1, "$50k-$150k": 0.2, "$150k+": 0.25}[budget_band] \
        + {"this month": 0.2, "1-3 months": 0.15, "3-6 months": 0.05, "just researching": -0.1}[timeline]
    score = round(max(0.05, min(0.99, score)), 2)
    qualified = score >= 0.5
    rep = lead.get("owner") or C.SALES_REPS[C._h(user_id) % len(C.SALES_REPS)]
    lead.update(seats=seats, budget_band=budget_band, timeline=timeline, score=score, owner=rep,
                status=("consult_booked" if p.get("consultation") else "qualified" if qualified else "nurture"))
    if interest:
        lead["interest"] = list(dict.fromkeys([interest] + lead.get("interest", [])))[:3]
    if phone.strip():
        p["phone"] = phone.strip()[:30]
    b = C.bundle_for_seats(seats)
    p["ml_scores"].update(lead_score=score, recommended_bundle=b["code"],
                          next_best_action="book_consultation" if qualified and not p.get("consultation") else "nurture")
    await save_profile(p)
    item = _item("lead", f"Details shared · {seats} seats · {budget_band}", seats=seats, budget_band=budget_band, timeline=timeline,
                 score=score, qualified=qualified, owner=rep)
    await record_activity(user_id, item)
    await after_change(user_id)
    est = b["price_per_seat"] * seats
    return {"ok": True, "status": "confirmed", "item": item, "qualified": qualified,
            "summary": f"Thanks, {_first(p)} - for {seats} seats, {b['name']} is the fit: about {money(est)} ({money(b['price_per_seat'])}/seat), "
                       f"delivered and assembled. {rep} from {C.COMPANY['business_brand']} is your contact"
                       + (" - book a consultation and they'll bring a floor plan." if qualified else "; we'll send the workspace guide and check in when you're closer.")}


async def book_consultation(user_id: str, date: str, time: str, topic: str = "", channel: str = "video") -> dict:
    p = await load_profile(user_id)
    require(p, "customer", "lead")
    if time not in C.CONSULT_TIMES:
        raise ToolError(f"Times available: {', '.join(C.CONSULT_TIMES)}")
    if channel not in C.CONSULT_CHANNELS:
        raise ToolError(f"Choose one of: {', '.join(C.CONSULT_CHANNELS)}")
    topic = topic or ((p.get("lead") or {}).get("interest") or C.CONSULT_TOPICS[-1:])[0]
    inv, _ = await get_inventory()
    sid = C.slot_id(date, time)
    if sid not in inv["slots"] or (days_until(date) or 0) < 1:
        raise ToolError("Pick a weekday in the next two weeks")
    if inv["slots"][sid] <= 0:
        alts = [t for t in C.CONSULT_TIMES if inv["slots"].get(C.slot_id(date, t), 0) > 0][:3]
        raise ToolError(f"{time} on {date} is fully booked." + (f" Open that day: {', '.join(alts)}" if alts else " Try another day."))
    await take("slots", sid, f"{time} on {date} was just taken - pick another time")
    rep = (p.get("lead") or {}).get("owner") or C.SALES_REPS[C._h(user_id) % len(C.SALES_REPS)]
    p["consultation"] = {"date": date, "time": time, "topic": topic, "channel": channel, "rep": rep, "booked_at": now_iso()}
    if p["audience"] == "lead":
        p["lead"].update(status="consult_booked", owner=rep)
        p["ml_scores"]["next_best_action"] = "prepare_for_consultation"
    await save_profile(p)
    item = _item("consultation", f"Consultation · {topic}", date=date, time=time, channel=channel, rep=rep, topic=topic)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"Booked: {topic} with {rep} on {nice_date(date)} at {time} ({channel}). A calendar invite is on its way to {p.get('email')}."}


# --------------------------------------------------------------------------
# team members: IT help desk
# --------------------------------------------------------------------------
async def create_it_ticket(user_id: str, category: str, summary: str, priority: str = "normal") -> dict:
    p = await load_profile(user_id)
    require(p, "employee")
    cat = C.IT_CATEGORY_BY_ID.get(category)
    if not cat:
        raise ToolError(f"Categories: {', '.join(c['id'] for c in C.IT_CATEGORIES)}")
    if priority not in C.IT_PRIORITIES:
        raise ToolError(f"Priority: {', '.join(C.IT_PRIORITIES)}")
    if not summary or len(summary.strip()) < 5:
        raise ToolError("Describe the problem in a sentence")
    dup = next((t for t in p["it"]["open_tickets"] if t["category"] == category and t["summary"].lower() == summary.strip().lower()), None)
    if dup:
        raise ToolError(f"{dup['ticket_id']} is already open for this")
    tid = f"INC-{300000 + C._h(user_id, summary, p.get('rev', 0)) % 600000}"
    sla = cat["sla_hours"] // (2 if priority == "high" else 1)
    ticket = {"ticket_id": tid, "category": category, "summary": summary.strip()[:200], "status": "open", "priority": priority,
              "opened_at": today().isoformat(), "queue": cat["queue"], "sla_hours": sla,
              "device": (p["it"]["devices"] or [{}])[0].get("asset_tag")}
    p["it"]["open_tickets"].append(ticket)
    await save_profile(p)
    item = _item("ticket", f"{tid} · {cat['name']}", ticket_id=tid, category=category, priority=priority, queue=cat["queue"], summary=ticket["summary"])
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"{tid} is open with the {cat['queue']} team ({priority} priority). First response within {sla} business hour{'s' if sla != 1 else ''}; "
                       f"they have your {ticket['device'] or 'device'} details already."}


async def reset_password(user_id: str, system: str = "sso") -> dict:
    p = await load_profile(user_id)
    require(p, "employee")
    s = C.SYSTEM_BY_ID.get(system)
    if not s or system not in p["it"]["systems_access"]:
        raise ToolError(f"You don't have an account on '{system}' to reset")
    if not p["it"]["mfa_enrolled"]:
        raise ToolError("You need multi-factor sign-in set up before a self-service reset - open an Account & access ticket and the Identity team will verify you")
    p["it"]["password_expires_in_days"] = 90
    p["it"]["last_password_reset"] = now_iso()
    await save_profile(p)
    item = _item("password", f"Password reset · {s['name']}", system=system)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"A reset link for {s['name']} is in your authenticator app - approve the prompt, then choose a new password within 15 minutes. "
                       "Your other devices will ask you to sign in again."}


async def _grant_access(user_id: str, system: str, justification: str, privileged: bool) -> dict:
    if not justification or len(justification.strip()) < 5:
        raise ToolError("Access requests need a business justification for the audit trail")
    p = await load_profile(user_id)
    require(p, "employee")
    s = C.SYSTEM_BY_ID.get(system)
    if not s:
        raise ToolError(f"Unknown system '{system}'. Requestable: {', '.join(x['id'] for x in C.SYSTEMS if not x['default'])}")
    if system in p["it"]["systems_access"]:
        raise ToolError(f"You already have access to {s['name']}")
    if s["approval"] != privileged:
        raise ToolError(f"{s['name']} " + ("holds customer, financial or production data, so it goes through a privileged access request"
                                           if s["approval"] else "is a standard system - request it with a standard access request"))
    if privileged and not all(t["status"] == "complete" for t in p["onboarding"]["tasks"] if t["task_id"] == "security-training"):
        raise ToolError(f"Finish your security awareness training before requesting {s['name']}")
    p["it"]["systems_access"].append(system)
    p["it"].setdefault("access_requests", []).append({"system": system, "justification": justification.strip()[:300],
                                                       "status": "granted", "privileged": privileged, "at": today().isoformat()})
    await save_profile(p)
    item = _item("access", f"Access granted · {s['name']}", system=system, privileged=privileged, justification=justification.strip()[:300])
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"You now have access to {s['name']}. It appears in your SSO launcher within a few minutes. Justification recorded: {justification.strip()[:120]}"}


async def request_system_access(user_id: str, system: str, justification: str) -> dict:
    """Standard systems (VPN, point of sale): granted straight away."""
    return await _grant_access(user_id, system, justification, privileged=False)


async def request_privileged_access(user_id: str, system: str, justification: str) -> dict:
    """Systems that expose customer, financial or production data. Held for a
    human decision in AOM's approval tier before it can run."""
    return await _grant_access(user_id, system, justification, privileged=True)


# --------------------------------------------------------------------------
# team members: HR
# --------------------------------------------------------------------------
async def request_time_off(user_id: str, start_date: str, end_date: str, note: str = "") -> dict:
    p = await load_profile(user_id)
    require(p, "employee")
    try:
        a, b = dt.date.fromisoformat(start_date), dt.date.fromisoformat(end_date)
    except ValueError:
        raise ToolError("Dates must be YYYY-MM-DD") from None
    if b < a or a <= today():
        raise ToolError("Pick a future start date and an end date on or after it")
    days = sum(1 for n in range((b - a).days + 1) if (a + dt.timedelta(days=n)).weekday() < 5)
    if days == 0:
        raise ToolError("Those dates are a weekend - no time off needed")
    pto = p["hr"]["pto"]
    if days > pto["balance_days"]:
        raise ToolError(f"That's {days} working days and your balance is {pto['balance_days']:g}. You accrue {pto.get('accrual_per_month', C.PTO_ACCRUAL_PER_MONTH):g} days a month.")
    if any(r["start_date"] <= end_date and start_date <= r["end_date"] for r in pto.get("requests", [])):
        raise ToolError("You already have time off requested over those dates")
    pto["balance_days"] = round(pto["balance_days"] - days, 1)
    pto.setdefault("requests", []).append({"start_date": start_date, "end_date": end_date, "days": days, "status": "pending_manager",
                                           "note": note.strip()[:200], "requested_at": today().isoformat()})
    await save_profile(p)
    mgr = p["employment"]["manager"]
    item = _item("timeoff", f"Time off · {days} day{'s' if days != 1 else ''}", status="submitted", date=start_date, end_date=end_date,
                 days=days, manager=mgr)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "submitted", "item": item,
            "summary": f"Requested {days} day{'s' if days != 1 else ''} off, {nice_date(start_date)}" + (f" to {nice_date(end_date)}" if end_date != start_date else "") + f". It's with {mgr} for approval; "
                       f"your balance after this is {pto['balance_days']:g} days."}


async def enroll_benefits(user_id: str, medical: str, dental: str = "", vision: str = "", k401_pct: int = -1) -> dict:
    p = await load_profile(user_id)
    require(p, "employee")
    b = p["hr"]["benefits"]
    left = days_until(b.get("enrollment_deadline"))
    if b["enrolled"]:
        raise ToolError("You're already enrolled - changes open again at annual enrollment in November, or after a qualifying life event")
    if left is not None and left < 0:
        raise ToolError("Your 30-day new-hire enrollment window has closed - talk to a People Partner about a qualifying life event")
    chosen = []
    for kind, pid in (("medical", medical), ("dental", dental), ("vision", vision)):
        if not pid:
            continue
        plan = C.PLAN_BY_ID.get(pid)
        if not plan or plan["kind"] != kind:
            raise ToolError(f"'{pid}' isn't a {kind} plan. Options: {', '.join(x['id'] for x in C.BENEFIT_PLANS[kind])}")
        b[kind] = pid
        chosen.append(plan)
    if not medical:
        raise ToolError("Choose a medical plan (or ask about waiving coverage)")
    if 0 <= int(k401_pct) <= 50:
        b["k401_pct"] = int(k401_pct)
    b.update(enrolled=True, enrolled_at=today().isoformat())
    for t in p["onboarding"]["tasks"]:
        if t["task_id"] == "benefits":
            t.update(status="complete", completed_at=today().isoformat())
    _close_onboarding(p)
    await save_profile(p)
    cost = sum(x["employee_cost_per_paycheck"] for x in chosen)
    item = _item("benefits", "Benefits enrolled · " + ", ".join(x["name"] for x in chosen), plans=[x["id"] for x in chosen],
                 cost_per_paycheck=cost, k401_pct=b.get("k401_pct", 0))
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"You're enrolled: {', '.join(x['name'] for x in chosen)} - {money(cost)} per paycheck, effective the first of next month. "
                       + (f"401(k) set to {b['k401_pct']}% (we match up to {C.K401_MATCH_PCT}%). " if b.get("k401_pct") else "")
                       + "Your ID cards arrive by mail in about 10 days and are in the People Portal now."}


def _close_onboarding(p: dict):
    if all(t["status"] == "complete" for t in p["onboarding"]["tasks"]):
        p["onboarding"]["status"] = "complete"
        p["ml_scores"]["next_best_action"] = "none"


async def complete_onboarding_task(user_id: str, task_id: str, acknowledgment: str = "") -> dict:
    p = await load_profile(user_id)
    require(p, "employee")
    t = next((t for t in p["onboarding"]["tasks"] if t["task_id"] == task_id), None)
    if not t:
        raise ToolError(f"Unknown onboarding task '{task_id}'")
    if t["status"] == "complete":
        raise ToolError(f"{t['title']} is already complete")
    if task_id == "benefits":
        raise ToolError("Benefits enrollment is completed by choosing your plans")
    if t["kind"] == "sign" and len(acknowledgment.strip()) < 2:
        raise ToolError("Type your full name to sign")
    t.update(status="complete", completed_at=today().isoformat())
    if t["kind"] == "sign":
        t["signed_as"] = acknowledgment.strip()[:80]
    _close_onboarding(p)
    await save_profile(p)
    left = [x for x in p["onboarding"]["tasks"] if x["status"] != "complete"]
    item = _item("onboarding", f"{t['title']} · complete", task_id=task_id, task_kind=t["kind"])
    await record_activity(user_id, item)
    await after_change(user_id)
    nxt = sorted(left, key=lambda x: x["due_date"])[0] if left else None
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"{t['title']} is done" + (" and signed" if t["kind"] == "sign" else "") + ". "
                       + (f"{len(left)} to go - next is {nxt['title']}, due {nice_date(nxt['due_date'])}." if nxt else "That's your onboarding complete - welcome to Larkfield!")}


TOOLS = {
    "get_user_context": get_user_context,
    "get_orders": get_orders,
    "get_return_options": get_return_options,
    "get_cart": get_cart,
    "recommend_products": recommend_products,
    "get_consultation_slots": get_consultation_slots,
    "get_it_context": get_it_context,
    "get_benefits_summary": get_benefits_summary,
    "get_onboarding_tasks": get_onboarding_tasks,
    "reschedule_delivery": reschedule_delivery,
    "start_return": start_return,
    "issue_goodwill_credit": issue_goodwill_credit,
    "checkout_cart": checkout_cart,
    "submit_lead_details": submit_lead_details,
    "book_consultation": book_consultation,
    "create_it_ticket": create_it_ticket,
    "reset_password": reset_password,
    "request_system_access": request_system_access,
    "request_privileged_access": request_privileged_access,
    "request_time_off": request_time_off,
    "enroll_benefits": enroll_benefits,
    "complete_onboarding_task": complete_onboarding_task,
}
READ_ONLY_TOOLS = {"get_user_context", "get_orders", "get_return_options", "get_cart", "recommend_products",
                   "get_consultation_slots", "get_it_context", "get_benefits_summary", "get_onboarding_tasks"}
# Held for a person in AOM's approval tier before they run.
APPROVAL_TOOLS = ["issue_goodwill_credit", "request_privileged_access"]
