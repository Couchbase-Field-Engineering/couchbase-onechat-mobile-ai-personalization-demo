"""End-to-end checks of the demo backend in memory mode (no Couchbase, no AOM):
the four use cases a company-wide chatbot covers, one persona each.

    cd backend && pytest -q
"""
import time
import uuid

# The `client` fixture (memory store, generated mock export, no AOM) lives in conftest.py.
MAYA, DANIEL, SOFIA = ("5510101", "Chen"), ("5520202", "Okafor"), ("5530303", "Alvarez")


def login(client, account, last):
    r = client.post("/api/auth/login", json={"account_id": account, "last_name": last})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user_id"]


def pull(client, h):
    docs = client.get("/api/sync/pull", headers=h).json()["docs"]
    return {(d["collection"], d["id"]): d["doc"] for d in docs}


def ask(client, h, message):
    r = client.post("/api/chat", headers=h, json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


def push(client, h, uid, tool, args):
    rid = f"req::{uid}::{uuid.uuid4().hex[:12]}"
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "requests", "id": rid, "doc": {
        "type": "request", "user_id": uid, "tool": tool, "args": args, "created_at": "2026-11-13T15:00:00Z"}}]})
    assert r.status_code == 200, r.text
    for _ in range(40):
        d = pull(client, h).get(("requests", rid))
        if d and d["status"] not in ("pending", "processing"):
            return d
        time.sleep(0.1)
    raise AssertionError("request never processed")


def test_personas_and_login(client):
    ps = client.get("/api/demo/personas").json()["personas"]
    assert [p["user_id"] for p in ps] == ["C00000101", "L00000201", "E00000301"]
    assert [p["audience"] for p in ps] == ["customer", "lead", "employee"]
    assert client.post("/api/auth/login", json={"account_id": "5510101", "last_name": "Nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"account_id": "5530303", "last_name": "alvarez"}).json()
    assert r["channels"] == ["user:E00000301", "catalog", "employees"]


def test_feed_is_personalized_per_audience(client):
    h, uid = login(client, *MAYA)
    docs = pull(client, h)
    kinds = [c["kind"] for c in docs[("feed", f"feed::{uid}")]["cards"]]
    assert {"order", "cart", "return"} <= set(kinds)
    assert ("catalog", "catalog::v1") in docs
    h, uid = login(client, *DANIEL)
    kinds = [c["kind"] for c in pull(client, h)[("feed", f"feed::{uid}")]["cards"]]
    assert kinds[0] == "consult" and "lead" in kinds
    h, uid = login(client, *SOFIA)
    cards = pull(client, h)[("feed", f"feed::{uid}")]["cards"]
    assert cards[0]["kind"] == "onboarding" and {"benefits", "ticket"} <= {c["kind"] for c in cards}


def test_handbook_only_reaches_team_members(client):
    """Sync Gateway's `employees` channel, mirrored by the preview sync."""
    h, _ = login(client, *MAYA)
    assert ("catalog", "handbook::v1") not in pull(client, h)
    h, _ = login(client, *DANIEL)
    assert ("catalog", "handbook::v1") not in pull(client, h)
    h, _ = login(client, *SOFIA)
    hb = pull(client, h)[("catalog", "handbook::v1")]
    assert hb["channels"] == ["employees"] and any("password" in f["q"].lower() for f in hb["faq"])


# ---- Customer Support & FAQs ---------------------------------------------------
def test_support_faqs_are_shared_answers(client):
    h, _ = login(client, *MAYA)
    for q, expect in (("What are your store hours?", "9am-9pm"), ("How long does delivery take?", "3-5 business days"),
                      ("What is your return policy?", "30 days"), ("Do you price match?", "14 days"),
                      ("How do I update my account details?", "Profile")):
        a = ask(client, h, q)
        assert a["personal"] is False and expect in a["reply"], (q, a["reply"])
        assert a["area"] in ("support", "commerce")
    a = ask(client, h, "How many rewards points do I have?")
    assert a["intent"] == "account" and a["personal"] and "4,180" in a["reply"]


# ---- E-Commerce & Order Tracking -------------------------------------------------
def test_order_tracking_uses_the_context_cache(client):
    h, uid = login(client, *MAYA)
    a = ask(client, h, "Where is my order?")
    assert a["intent"] == "order" and a["area"] == "commerce" and a["personal"] and a["context"]["status"] == "miss"
    assert "LF-881042" in a["reply"] and "12pm-4pm" in a["reply"]
    # the context was built with the person's current CDP record
    assert a["context"]["sor"]["system"] == "cdp" and "Cart abandoners" in a["context"]["sor"]["segments"]
    assert any(x.get("screen") == "order" for x in a["actions"])
    b = ask(client, h, "When will my package arrive?")
    assert b["context"]["status"] == "hit"
    assert ("context_cache", f"ctx::{uid}::order") in pull(client, h)


def test_reschedule_return_and_invalidation(client):
    h, uid = login(client, *MAYA)
    ask(client, h, "Can I return something from my last order?")
    assert ("context_cache", f"ctx::{uid}::return") in pull(client, h)
    r = push(client, h, uid, "reschedule_delivery", {"order_id": "LF-881042", "date": "2026-11-17", "window": "4pm-8pm"})
    assert r["status"] == "confirmed", r
    r = push(client, h, uid, "start_return", {"order_id": "LF-880517", "sku": "LGT-HLO-BAR", "reason": "Changed my mind"})
    assert r["status"] == "confirmed" and "$89" in r["summary"], r
    docs = pull(client, h)
    p = docs[("profiles", f"profile::{uid}")]
    assert next(o for o in p["orders"] if o["order_id"] == "LF-881042")["eta"] == "2026-11-17"
    assert p["returns"][0]["sku"] == "LGT-HLO-BAR" and p["rev"] >= 2
    assert ("context_cache", f"ctx::{uid}::return") not in docs       # invalidated by the return
    assert {i["kind"] for i in docs[("activity", f"activity::{uid}")]["items"]} >= {"delivery", "return"}
    # the same item can't be returned twice, and the keyboard is outside Gold's 45 days
    assert push(client, h, uid, "start_return", {"order_id": "LF-880517", "sku": "LGT-HLO-BAR", "reason": "again"})["status"] == "failed"
    late = push(client, h, uid, "start_return", {"order_id": "LF-874233", "sku": "KBD-TYP-MX", "reason": "Broken key"})
    assert late["status"] == "failed" and "45-day" in late["summary"]


def test_exchange_and_cart_recovery(client):
    h, uid = login(client, *MAYA)
    a = ask(client, h, "Is the offer on my cart still valid?")
    assert a["intent"] == "cart" and "COMEBACK10" in a["reply"] and a["actions"][0]["tool"] == "checkout_cart"
    r = push(client, h, uid, "start_return", {"order_id": "LF-880517", "sku": "CHR-LUM-BLK", "reason": "Wrong colour for the room",
                                             "resolution": "exchange", "exchange_sku": "CHR-LUM-SND"})
    assert r["status"] == "confirmed" and "Lumen Ergonomic Chair · Sand" in r["summary"], r
    r = push(client, h, uid, "checkout_cart", {"apply_offer": True})
    assert r["status"] == "confirmed" and r["charge_usd"] == 457.2, r
    p = pull(client, h)[("profiles", f"profile::{uid}")]
    assert p["cart"] is None and p["orders"][0]["status"] == "processing" and p["orders"][0]["offer_code"] == "COMEBACK10"
    assert push(client, h, uid, "checkout_cart", {})["status"] == "failed"


# ---- Lead Generation & Sales -----------------------------------------------------
def test_lead_capture_qualification_and_consultation(client):
    h, uid = login(client, *DANIEL)
    a = ask(client, h, "We need to furnish our office - where do I start?")
    assert a["intent"] == "sales" and a["area"] == "sales" and a["personal"]
    assert "Brightwater Studio" in a["reply"] and a["context"]["sor"]["system"] == "crm"
    labels = [x["label"] for x in a["actions"]]
    assert any("quote" in x.lower() for x in labels) and any(x.get("tool") == "book_consultation" for x in a["actions"])
    r = push(client, h, uid, "submit_lead_details", {"seats": 24, "budget_band": "$10k-$50k", "timeline": "1-3 months"})
    assert r["status"] == "confirmed" and "Workspace Team" in r["summary"], r
    p = pull(client, h)[("profiles", f"profile::{uid}")]
    assert p["lead"]["status"] == "qualified" and p["lead"]["owner"] and p["lead"]["score"] >= 0.5
    book = next(x for x in ask(client, h, "Can I book a consultation this week?")["actions"] if x.get("tool") == "book_consultation")
    r = push(client, h, uid, "book_consultation", book["args"])
    assert r["status"] == "confirmed", r
    docs = pull(client, h)
    assert docs[("profiles", f"profile::{uid}")]["lead"]["status"] == "consult_booked"
    assert docs[("feed", f"feed::{uid}")]["cards"][0]["card_id"] == "consult-booked"
    # product discovery is personal too
    d = ask(client, h, "Can you recommend a desk for me?")
    assert d["intent"] == "product" and "Workspace Team" in d["reply"]


# ---- Internal Operations & HR ------------------------------------------------------
def test_it_help_desk(client):
    h, uid = login(client, *SOFIA)
    g = ask(client, h, "How do I reset my password?")
    assert g["intent"] == "it" and g["area"] == "workplace" and g["personal"] is False and "authenticator" in g["reply"]
    a = ask(client, h, "I forgot my password and I'm locked out")
    assert a["personal"] and a["context"]["sor"]["system"] == "hris" and a["actions"][0]["tool"] == "reset_password"
    assert push(client, h, uid, "reset_password", {"system": "sso"})["status"] == "confirmed"
    v = ask(client, h, "My laptop won't connect to the VPN")
    assert "INC-204871" in v["reply"] and v["actions"][0]["tool"] == "request_system_access"
    assert push(client, h, uid, "request_system_access", {"system": "vpn", "justification": "Hybrid schedule"})["status"] == "confirmed"
    t = push(client, h, uid, "create_it_ticket", {"category": "hardware", "summary": "Laptop battery drains in an hour", "priority": "high"})
    assert t["status"] == "confirmed" and "Deskside" in t["summary"]
    p = pull(client, h)[("profiles", f"profile::{uid}")]
    assert "vpn" in p["it"]["systems_access"] and len(p["it"]["open_tickets"]) == 2 and p["it"]["password_expires_in_days"] == 90
    # privileged systems go through the approval-tier tool, and need security training first
    assert "privileged" in push(client, h, uid, "request_system_access", {"system": "analytics", "justification": "Weekly reports"})["summary"]
    assert "security awareness training" in push(client, h, uid, "request_privileged_access",
                                                 {"system": "analytics", "justification": "Weekly reports"})["summary"]


def test_hr_benefits_time_off_and_onboarding(client):
    h, uid = login(client, *SOFIA)
    b = ask(client, h, "Am I enrolled in benefits?")
    assert b["intent"] == "hr" and "Dec 7" in b["reply"] and b["actions"][0]["screen"] == "benefits"
    assert "Core PPO" in ask(client, h, "What medical plans are there?")["reply"]
    o = ask(client, h, "What's left on my onboarding checklist?")
    assert o["intent"] == "onboarding" and "5 onboarding tasks" in o["reply"] and "Direct deposit" in o["reply"]
    dd = push(client, h, uid, "complete_onboarding_task", {"task_id": "direct-deposit"})
    assert dd["status"] == "confirmed", dd
    assert push(client, h, uid, "complete_onboarding_task", {"task_id": "handbook"})["status"] == "failed"      # needs a signature
    assert push(client, h, uid, "complete_onboarding_task", {"task_id": "handbook", "acknowledgment": "Sofia Alvarez"})["status"] == "confirmed"
    e = push(client, h, uid, "enroll_benefits", {"medical": "MED-HSA", "dental": "DEN-BASE", "k401_pct": 4})
    assert e["status"] == "confirmed" and "$28" in e["summary"], e
    t = push(client, h, uid, "request_time_off", {"start_date": "2026-11-27", "end_date": "2026-11-27"})
    assert t["status"] == "submitted" and "Marcus Reid" in t["summary"]
    assert push(client, h, uid, "request_time_off", {"start_date": "2026-12-01", "end_date": "2026-12-12"})["status"] == "failed"
    p = pull(client, h)[("profiles", f"profile::{uid}")]
    assert p["hr"]["benefits"]["enrolled"] and p["hr"]["pto"]["balance_days"] == 2.0
    assert sum(t["status"] != "complete" for t in p["onboarding"]["tasks"]) == 2


# ---- one chatbot, three audiences: the guard rails ------------------------------------
def test_internal_questions_are_refused_for_customers_and_prospects(client):
    for who in (MAYA, DANIEL):
        h, _ = login(client, *who)
        for q in ("How do I reset my VPN password?", "What medical plans do employees get?", "When do I enroll in benefits?"):
            a = ask(client, h, q)
            assert a["restricted"] and a["area"] == "workplace" and "team members" in a["reply"], q
            assert not a["sources"] and not a["actions"] and a["llm"]["status"] == "skipped"


def test_tools_check_the_audience(client):
    h, uid = login(client, *MAYA)
    r = push(client, h, uid, "create_it_ticket", {"category": "vpn", "summary": "let me in please"})
    assert r["status"] == "failed" and "team members" in r["summary"]
    assert push(client, h, uid, "get_orders", {})["status"] == "failed"          # read tools can't be requested from a phone
    h, uid = login(client, *SOFIA)
    assert "customers" in push(client, h, uid, "checkout_cart", {})["summary"]


def test_push_rejects_other_users(client):
    h, uid = login(client, *DANIEL)
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "requests", "id": "req::C00000101::x",
                                                                 "doc": {"user_id": "C00000101", "tool": "checkout_cart"}}]})
    assert r.status_code == 403


def test_personas_are_pinned_to_the_export_date(client):
    import datetime as dt
    day = dt.date(2026, 11, 13)
    h, uid = login(client, *SOFIA)
    p = pull(client, h)[("profiles", f"profile::{uid}")]
    assert (day - dt.date.fromisoformat(p["employment"]["start_date"])).days == 6
