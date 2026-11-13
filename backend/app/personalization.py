"""Ranks the "For You" feed for one person.

Inputs are the scores, segments and preferences from the nightly export,
plus live state the export can't know about: what the person has done since
(a return started in chat, a ticket opened, a consultation booked), unsold
stock and open consultation slots. The result is written to
`feed::<user_id>`, which Sync Gateway replicates to the person's phone - so
the feed renders from Couchbase Lite, even offline, and re-ranks itself on
the next sync after every action.

A card carries everything its screen needs (return options, consultation
slots), so the Return and Consultation screens work offline too.
"""
from __future__ import annotations

from . import catalog as C
from .docs import days_until, feed_id, money, nice_date, now_iso, profile_id, user_channel
from .store import store

PALETTES = {  # gradient keys the app maps to brand gradients
    "order": "ink", "return": "ember", "cart": "red", "product": "sand", "consult": "red", "lead": "ink",
    "onboarding": "red", "benefits": "ember", "ticket": "ink", "it": "sand", "timeoff": "sand", "reward": "ember",
}


def _card(kind: str, card_id: str, title: str, subtitle: str, reason: str, badge: str, score: float, cta: dict, **extra) -> dict:
    return {"card_id": card_id, "kind": kind, "palette": PALETTES.get(kind, "ink"), "area": AREA_OF[kind], "title": title,
            "subtitle": subtitle, "reason": reason, "badge": badge, "score": score, "cta": cta, **extra}


AREA_OF = {"order": "commerce", "return": "commerce", "cart": "commerce", "reward": "support", "product": "sales",
           "consult": "sales", "lead": "sales", "onboarding": "workplace", "benefits": "workplace", "ticket": "workplace",
           "it": "workplace", "timeoff": "workplace"}


async def _customer(p: dict) -> list[dict]:
    from .actions import get_inventory, return_status  # avoid import cycle

    s, cards = p["ml_scores"], []
    inv, _ = await get_inventory()
    for o in p["orders"]:
        if o["status"] in ("processing", "shipped", "out_for_delivery"):
            d = days_until(o["eta"]) or 0
            when = "today" if d <= 0 else "tomorrow" if d == 1 else f"in {d} days"
            cards.append(_card(
                "order", f"order-{o['order_id']}", f"Your {o['items'][0]['name']} arrives {when}",
                f"Order {o['order_id']} · {o['status'].replace('_', ' ')} · {o['carrier']}"
                + (f" · {o['delivery_window']}" if o.get("delivery_window") else ""),
                "Out for delivery now" if o["status"] == "out_for_delivery" else "You can move the delivery day" if o["carrier"] == "Larkfield Delivery" and o["status"] != "out_for_delivery" else "Tracking is live",
                nice_date(o["eta"]), 0.95 if d <= 2 else 0.7, {"label": "Track order", "screen": "order", "args": {"order_id": o["order_id"]}}))
    cart = p.get("cart")
    if cart and cart.get("items"):
        offer = cart.get("offer")
        left = days_until(offer["expires"]) if offer else None
        valid = offer and left is not None and left >= 0
        low = [i["name"] for i in cart["items"] if inv["stock"].get(i["sku"], 0) <= 3]
        total = cart["subtotal_usd"] * (1 - offer["pct_off"] / 100) if valid else cart["subtotal_usd"]
        cards.append(_card(
            "cart", "cart", "Still thinking it over?" if not valid else f"{offer['pct_off']}% off what's in your cart",
            " + ".join(i["name"] for i in cart["items"][:2]) + (f" +{len(cart['items']) - 2} more" if len(cart["items"]) > 2 else ""),
            " · ".join(x for x in [f"Code {offer['code']} ends in {left} day{'s' if left != 1 else ''}" if valid else None,
                                    f"Only a few {low[0]} left" if low else None] if x) or "Saved for you",
            money(round(total, 2)), s.get("cart_recovery_propensity", 0.5) * (1.15 if valid else 0.9),
            {"label": "Check out", "tool": "checkout_cart", "args": {"apply_offer": True}}))
    ret_items = []
    for o in p["orders"]:
        if o["status"] != "delivered":
            continue
        for i in o["items"]:
            st = return_status(p, o, i)
            if st["eligible"]:
                ret_items.append({"order_id": o["order_id"], "sku": i["sku"], "name": i["name"], "price": i["price"],
                                  "delivered_at": o["delivered_at"], "days_left": st["days_left"], "window_days": st["window_days"],
                                  "exchange_options": [{"sku": x["sku"], "name": x["name"], "price": x["price"],
                                                        "in_stock": inv["stock"].get(x["sku"], 0)} for x in C.exchange_options(i["sku"])]})
    if ret_items:
        ret_items.sort(key=lambda r: r["days_left"])
        soon = ret_items[0]
        cards.append(_card(
            "return", "returns", "Not quite right? Returns are free",
            f"{len(ret_items)} item{'s' if len(ret_items) > 1 else ''} you can still return or exchange",
            f"{soon['name']}: {soon['days_left']} days left" + (f" · {p['loyalty']['tier']} members get {soon['window_days']} days" if soon["window_days"] > 30 else ""),
            "Free", 0.32 + (0.2 if soon["days_left"] <= 7 else 0), {"label": "Start a return", "screen": "return"},
            options=ret_items, reasons=C.RETURN_REASONS))
    owned = {i["sku"] for o in p["orders"] for i in o["items"]} | {i["sku"] for i in (cart or {}).get("items", [])}
    likes = set(p["preferences"]["interests"])
    for sku in [x for x in s.get("recommended_skus", []) if x not in owned][:2]:
        prod = C.PRODUCT_BY_SKU.get(sku)
        if not prod:
            continue
        match = sorted(likes & set(prod["tags"]))
        cards.append(_card(
            "product", f"product-{sku}", prod["name"], prod["blurb"],
            f"Because you like {' & '.join(match[:2])}" if match else "Goes with what you own", f"${prod['price']}",
            s.get("upsell_propensity", 0.4) * 0.7, {"label": "Ask about it", "ask": f"Tell me about the {prod['name']}"}))
    if p["loyalty"]["points"] >= 500:
        cards.append(_card("reward", "reward", f"You have {p['loyalty']['points']:,} points", f"{p['loyalty']['tier']} · {p['loyalty']['program']}",
                           f"That's {money(p['loyalty']['points'] // 500 * 5)} in rewards at checkout", p["loyalty"]["tier"], 0.25,
                           {"label": "How rewards work", "ask": "How does Larkfield Rewards work?"}))
    return cards


async def _lead(p: dict) -> list[dict]:
    from .actions import get_inventory

    s, lead, cards = p["ml_scores"], p["lead"], []
    inv, _ = await get_inventory()
    seats = lead.get("seats") or p["company"]["employees"]
    b = C.bundle_for_seats(seats)
    consult = p.get("consultation")
    if consult:
        cards.append(_card("consult", "consult-booked", f"Consultation with {consult['rep']}", f"{nice_date(consult['date'])} at {consult['time']} · {consult['channel']}",
                           consult["topic"], "Booked", 1.0, {"label": "What to bring", "ask": "How does a workspace consultation work?"}))
    else:
        days: dict[str, list] = {}
        for sid, left in sorted(inv["slots"].items()):
            date, time = sid.split("T")
            if (days_until(date) or 0) >= 1:
                days.setdefault(date, []).append({"time": time, "open": left})
        cards.append(_card(
            "consult", "consult", "Book a free workspace consultation",
            f"45 minutes with a {C.COMPANY['business_brand']} specialist - video, phone or in store",
            f"For {p['company']['name']}: {', '.join(lead.get('interest', [])[:2])}", "Free",
            s.get("lead_score", 0.5) * 1.2, {"label": "Pick a time", "screen": "consult"},
            slots=[{"date": d, "slots": sl} for d, sl in list(days.items())[:6]], topics=C.CONSULT_TOPICS, channels=C.CONSULT_CHANNELS))
    if not lead.get("seats") or not lead.get("budget_band"):
        cards.append(_card("lead", "lead-details", "Get a tailored quote", "Tell us your headcount, budget and timeline",
                           "Takes a minute - we'll size the right package", "2 questions", s.get("lead_score", 0.5) * 1.05,
                           {"label": "Share details", "screen": "consult", "args": {"step": "details"}}))
    cards.append(_card(
        "product", f"bundle-{b['code']}", b["name"], b["blurb"],
        f"Sized for about {seats} seats at {p['company']['name']}", f"${b['price_per_seat']:,}/seat · ~{money(b['price_per_seat'] * seats)}",
        s.get("fit", 0.5) * 0.9, {"label": "Ask about it", "ask": f"What's included in {b['name']}?"}))
    for sku in p["browsing"]["viewed_skus"][:2]:
        prod = C.PRODUCT_BY_SKU.get(sku)
        if prod:
            cards.append(_card("product", f"product-{sku}", prod["name"], prod["blurb"], "You looked at this recently", f"${prod['price']}",
                               0.3, {"label": "Ask about it", "ask": f"Tell me about the {prod['name']}"}))
    return cards


async def _employee(p: dict) -> list[dict]:
    it, hr, cards = p["it"], p["hr"], []
    pend = sorted([t for t in p["onboarding"]["tasks"] if t["status"] != "complete"], key=lambda t: t["due_date"])
    if pend:
        nxt = pend[0]
        d = days_until(nxt["due_date"]) or 0
        due = "overdue" if d < 0 else "due today" if d == 0 else "due tomorrow" if d == 1 else f"due in {d} days"
        cards.append(_card("onboarding", "onboarding", f"{len(pend)} onboarding task{'s' if len(pend) > 1 else ''} left",
                           f"Next: {nxt['title']} · {due}", "Sign and submit right here, even offline", f"{len(p['onboarding']['tasks']) - len(pend)}/{len(p['onboarding']['tasks'])} done",
                           1.0 + (0.3 if d <= 2 else 0), {"label": "Open my checklist", "screen": "onboarding"}))
    b = hr["benefits"]
    if not b["enrolled"]:
        d = days_until(b.get("enrollment_deadline"))
        if d is not None and d >= 0:
            cards.append(_card("benefits", "benefits", "Choose your benefits", f"Enrollment closes in {d} day{'s' if d != 1 else ''} ({nice_date(b['enrollment_deadline'])})",
                               "Medical, dental, vision and 401(k) - coverage starts the 1st of next month", "Required",
                               0.9 + (0.3 if d <= 7 else 0), {"label": "Compare plans", "screen": "benefits"}))
    for t in it["open_tickets"][:2]:
        cards.append(_card("ticket", f"ticket-{t['ticket_id']}", f"{t['ticket_id']} · {t['status'].replace('_', ' ')}", t["summary"],
                           f"With the {t.get('queue') or C.IT_CATEGORY_BY_ID.get(t['category'], {}).get('queue', 'IT')} team since {nice_date(t['opened_at'])}",
                           t["priority"], 0.75, {"label": "Ask for an update", "ask": f"Any update on ticket {t['ticket_id']}?"}))
    if it["password_expires_in_days"] <= 10:
        d = it["password_expires_in_days"]
        cards.append(_card("it", "password", f"Your password expires in {d} day{'s' if d != 1 else ''}", "Reset it now in one tap",
                           "Avoid getting locked out", "SSO", 0.8 if d <= 5 else 0.6,
                           {"label": "Reset password", "tool": "reset_password", "args": {"system": "sso"}}))
    if "vpn" not in it["systems_access"]:
        cards.append(_card("it", "vpn", "Working from home?", "Remote VPN is a standard request, granted straight away",
                           "You don't have VPN access yet", "IT", 0.45,
                           {"label": "Request VPN access", "tool": "request_system_access",
                            "args": {"system": "vpn", "justification": "Remote work from home"}}))
    cards.append(_card("timeoff", "pto", f"{hr['pto']['balance_days']:g} days of paid time off", f"Accruing {hr['pto'].get('accrual_per_month', C.PTO_ACCRUAL_PER_MONTH):g} days a month",
                       f"Requests go to {p['employment']['manager']}", "PTO", 0.3, {"label": "Request time off", "screen": "timeoff"}))
    return cards


async def compute_feed(profile: dict) -> list[dict]:
    if not profile.get("consent", {}).get("personalization_opt_in", True):
        return []
    cards = await {"customer": _customer, "lead": _lead, "employee": _employee}[profile["audience"]](profile)
    cards.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(cards):
        c["rank"] = i + 1
        c["score"] = round(c["score"], 3)
    return cards


async def refresh_feed(user_id: str) -> dict | None:
    profile = await store.get("profiles", profile_id(user_id))
    if not profile:
        return None
    doc = {
        "type": "feed", "user_id": user_id, "audience": profile["audience"], "cards": await compute_feed(profile),
        "model_version": profile["ml_scores"].get("model_version"), "segment": profile["ml_scores"].get("segment"),
        "export_date": profile.get("export_date"), "profile_rev": profile.get("rev", 0),
        "generated_at": now_iso(), "channels": [user_channel(user_id)],
    }
    await store.upsert("feed", feed_id(user_id), doc)
    return doc
