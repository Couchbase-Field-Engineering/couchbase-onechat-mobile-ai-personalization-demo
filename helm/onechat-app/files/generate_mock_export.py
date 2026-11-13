#!/usr/bin/env python3
"""Generate the mock nightly export OneChat is loaded from.

Larkfield (the demo company, see backend/app/catalog.py) keeps the people a
company-wide chatbot serves in three systems of record:

* the **CDP / commerce platform** - customers, their orders, carts, loyalty
  status, audience segments and propensity scores
* the **CRM** - business prospects, their company, lead status and score
* the **HRIS and ITSM** - team members, their onboarding tasks, benefits,
  time off, devices, system access and help-desk tickets

Every night a scheduled export lands one JSON Lines dataset with a row per
person (`audience` says which kind) in a time-stamped folder. This script
writes that layout:

    data/onechat-export/exportTime=20261113/
        part-00000-<uuid>-c000.json      # JSON Lines, one person per line
        part-00001-<uuid>-c000.json
        _SUCCESS
        _manifest.json                   # row/byte counts per audience, schema + model versions

Fully deterministic for a given --seed and --export-date, and standard
library only (runs anywhere Python 3.9+ does). Default target is 24 MiB.

    python datagen/generate_mock_export.py                 # today
    python datagen/generate_mock_export.py --export-date 2026-11-13 --target-mb 24
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
from app import catalog as C  # noqa: E402

SCHEMA_VERSION = "onechat_person_v2"
MODEL_VERSION = "onechat-propensity-v3"
PERSONAS = ["C00000101", "L00000201", "E00000301"]

FIRST = ["Ava", "Noah", "Mia", "Liam", "Zoe", "Ethan", "Nora", "Lucas", "Ivy", "Owen", "Leah", "Caleb", "Ruby", "Isaac",
         "Elena", "Mateo", "Amara", "Kofi", "Yuki", "Arjun", "Fatima", "Diego", "Hana", "Tariq", "Ingrid", "Rafael",
         "Chloe", "Jamal", "Mei", "Andre", "Sana", "Victor", "Lena", "Omar", "Tessa", "Reza", "Nia", "Paulo", "Greta", "Dev"]
LAST = ["Nguyen", "Patel", "Garcia", "Johnson", "Kim", "Hernandez", "Brown", "Singh", "Martinez", "Cohen", "Okonkwo",
        "Larsen", "Tanaka", "Ali", "Rossi", "Murphy", "Santos", "Haddad", "Novak", "Park", "Mensah", "Dubois", "Ivanov",
        "Castillo", "Reyes", "Walker", "Fischer", "Banerjee", "Costa", "Holt", "Yamamoto", "Abbasi", "Lindgren", "Okoye"]
CITIES = {
    "Northeast": ["Brooklyn, NY", "Boston, MA", "Philadelphia, PA", "Jersey City, NJ", "Providence, RI"],
    "Southeast": ["Atlanta, GA", "Miami, FL", "Charlotte, NC", "Nashville, TN", "Tampa, FL"],
    "Midwest": ["Chicago, IL", "Minneapolis, MN", "Columbus, OH", "Madison, WI", "Detroit, MI"],
    "Southwest": ["Austin, TX", "Phoenix, AZ", "Dallas, TX", "Denver, CO", "Albuquerque, NM"],
    "West": ["Seattle, WA", "San Francisco, CA", "Portland, OR", "San Diego, CA", "Oakland, CA"],
}
COMPANY_A = ["Brightwater", "Northgate", "Cedar & Finch", "Bluebird", "Ironwood", "Halcyon", "Parallel", "Tidewater",
             "Meridian", "Copperline", "Fieldstone", "Lumen Row", "Quarry", "Wren", "Harborview", "Skylark"]
COMPANY_B = ["Studio", "Labs", "Partners", "Collective", "Group", "Health", "Legal", "Capital", "Works", "Systems", "Academy"]
SEGMENTS = {
    "seg-cart-abandoners": "Cart abandoners",
    "seg-gold-plus": "Gold & Platinum members",
    "seg-home-office": "Home-office upgraders",
    "seg-at-risk": "At risk of churn",
    "seg-new-customers": "New customers (first 60 days)",
    "seg-frequent-returners": "Frequent returners",
    "seg-high-intent-b2b": "High-intent business buyers",
    "seg-researching-b2b": "Business buyers - researching",
    "seg-new-hires": "New hires (first 30 days)",
    "seg-people-managers": "People managers",
    "seg-store-teams": "Store teams",
}


def clamp(x: float, lo=0.01, hi=0.99) -> float:
    return round(max(lo, min(hi, x)), 2)


def seg(*ids) -> list[dict]:
    return [{"id": i, "name": SEGMENTS[i], "status": "realized"} for i in ids if i]


class Gen:
    def __init__(self, export_date: dt.date, seed: int):
        self.r = random.Random(seed)
        self.today = export_date
        self.n = {"customer": 1000, "lead": 1000, "employee": 1000}
        self.account = 6_000_000
        self.order_no = 700_000
        self.ticket_no = 200_000

    # ---- ids -------------------------------------------------------------
    def uid(self, audience: str) -> str:
        self.n[audience] += 1
        return f"{audience[0].upper()}{self.n[audience]:08d}"

    def next_account(self) -> str:
        self.account += self.r.randint(1, 9)
        return str(self.account)

    def next_order(self) -> str:
        self.order_no += self.r.randint(1, 40)
        return f"LF-{self.order_no}"

    def payday(self, later: bool = False) -> str:
        """The next Friday (we pay every other Friday)."""
        d = self.today + dt.timedelta(days=1)
        while d.weekday() != 4:
            d += dt.timedelta(days=1)
        return (d + dt.timedelta(days=7 if later else 0)).isoformat()

    def day(self, offset: int) -> str:
        return (self.today + dt.timedelta(days=offset)).isoformat()

    def person(self):
        return self.r.choice(FIRST), self.r.choice(LAST)

    def base(self, audience, user_id, account_id, first, last, city, region, group):
        return {
            "user_id": user_id, "audience": audience, "group_code": group, "account_id": account_id,
            "export_date": self.today.isoformat(), "schema_version": SCHEMA_VERSION,
            "first_name": first, "last_name": last,
            "email": f"{first}.{last}".lower().replace(" ", "") + ("@larkfield.example" if audience == "employee" else "@example.com"),
            "home_city": city, "region": region,
            "consent": {"personalization_opt_in": True, "marketing_opt_in": self.r.random() < 0.7},
        }

    # ---- customers ---------------------------------------------------------
    def order(self, age_days: int, skus: list[str] | None = None, status: str | None = None, city: str = "") -> dict:
        r = self.r
        skus = skus or r.sample([p["sku"] for p in C.PRODUCTS], r.choice([1, 1, 2, 2, 3]))
        items = [{"sku": s, "name": C.PRODUCT_BY_SKU[s]["name"], "qty": 1, "price": C.PRODUCT_BY_SKU[s]["price"]} for s in skus]
        subtotal = sum(i["price"] * i["qty"] for i in items)
        transit = r.randint(3, 6)
        if not status:
            status = ("processing" if age_days <= 1 else "shipped" if age_days < transit - 1 else
                      "out_for_delivery" if age_days == transit - 1 else "delivered")
            if status == "delivered" and r.random() < 0.03:
                status = "cancelled"
        placed = -age_days
        eta = placed + transit
        carrier = "Larkfield Delivery" if any(C.PRODUCT_BY_SKU[s]["category"] in ("Desks", "Chairs", "Storage") for s in skus) else r.choice(C.CARRIERS[1:])
        events = [{"at": self.day(placed), "text": "Order placed"}]
        if status in ("shipped", "out_for_delivery", "delivered"):
            events.append({"at": self.day(placed + 1), "text": f"Shipped with {carrier}"})
        if status in ("out_for_delivery", "delivered"):
            events.append({"at": self.day(min(eta, 0)), "text": "Out for delivery"})
        if status == "delivered":
            events.append({"at": self.day(min(eta, 0)), "text": "Delivered"})
        if status == "cancelled":
            events.append({"at": self.day(placed + 1), "text": "Cancelled and refunded"})
        return {
            "order_id": self.next_order(), "placed_at": self.day(placed), "status": status, "items": items,
            "subtotal_usd": subtotal, "shipping_usd": 0 if subtotal >= C.FREE_SHIPPING_MIN else C.STANDARD_SHIPPING,
            "total_usd": round(subtotal + (0 if subtotal >= C.FREE_SHIPPING_MIN else C.STANDARD_SHIPPING), 2),
            "carrier": carrier, "tracking_number": f"{'LFD' if carrier == 'Larkfield Delivery' else '1Z'}{r.randint(10**9, 10**10 - 1)}",
            "eta": self.day(eta) if status != "cancelled" else None,
            "delivery_window": r.choice(C.DELIVERY_WINDOWS) if carrier == "Larkfield Delivery" else None,
            "delivered_at": self.day(min(eta, 0)) if status == "delivered" else None,
            "ship_to_city": city, "events": events,
        }

    def cart(self, skus: list[str], abandoned_days: int, pct: int = 10) -> dict:
        items = [{"sku": s, "name": C.PRODUCT_BY_SKU[s]["name"], "qty": 1, "price": C.PRODUCT_BY_SKU[s]["price"]} for s in skus]
        sub = sum(i["price"] for i in items)
        return {"updated_at": self.day(-abandoned_days), "items": items, "subtotal_usd": sub, "abandoned_days": abandoned_days,
                "offer": {"code": f"COMEBACK{pct}", "pct_off": pct, "expires": self.day(4)} if abandoned_days >= 2 else None}

    def customer(self, overrides: dict | None = None) -> dict:
        r = self.r
        first, last = self.person()
        region = r.choice(C.REGIONS)
        city = r.choice(CITIES[region])
        orders_count = r.choice([0, 1, 1, 2, 2, 3, 4, 6, 9, 14])
        tier = "Platinum" if orders_count >= 14 else "Gold" if orders_count >= 6 else "Silver" if orders_count >= 3 else "Member"
        recent = sorted({r.randint(0, 110) for _ in range(min(orders_count, r.choice([1, 2, 2, 3])))})
        orders = [self.order(a, city=city) for a in recent]
        interests = r.sample(C.INTERESTS, r.randint(2, 4))
        has_cart = r.random() < 0.28
        pool = [p["sku"] for p in C.PRODUCTS if set(p["tags"]) & set(interests)] or [p["sku"] for p in C.PRODUCTS]
        cart = self.cart(r.sample(pool, min(len(pool), r.choice([1, 2]))), r.randint(0, 9)) if has_cart else None
        spend = sum(o["total_usd"] for o in orders)
        ltv = round(spend + max(0, orders_count - len(orders)) * r.uniform(90, 420), 2)
        returns_count = r.choice([0, 0, 0, 1, 1, 2, 4]) if orders_count else 0
        churn = clamp(0.5 - orders_count * 0.03 + r.uniform(-0.2, 0.25))
        cart_prop = clamp(0.35 + (0.25 if cart else 0) + r.uniform(-0.2, 0.25))
        row = self.base("customer", self.uid("customer"), self.next_account(), first, last, city, region, C.REGION_GROUP[region])
        row.update({
            "phone": f"+1 555 01{r.randint(10, 99)} {r.randint(1000, 9999)}",
            "identity": {"crm_id": f"CRM-{r.randint(10**6, 10**7 - 1)}", "namespace": "customerId", "source": "cdp"},
            "loyalty": {"program": C.COMPANY["loyalty_program"], "tier": tier, "points": orders_count * r.randint(120, 480),
                        "member_since": self.day(-r.randint(40, 2400))},
            "preferences": {"interests": interests, "communication_channel": r.choice(["email", "sms", "app"]),
                            "preferred_store": r.choice([s["id"] for s in C.STORES if s["region"] == region])},
            "orders": orders, "cart": cart, "returns": [], "credits": [],
            "history": {"lifetime_value_usd": ltv, "orders_count": max(orders_count, len(orders)),
                        "avg_order_usd": round(ltv / max(orders_count, len(orders), 1), 2), "returns_count": returns_count},
            "segments": seg("seg-cart-abandoners" if cart and cart["abandoned_days"] >= 2 else None,
                            "seg-gold-plus" if tier in ("Gold", "Platinum") else None,
                            "seg-home-office" if "home-office" in interests else None,
                            "seg-at-risk" if churn >= 0.6 else None,
                            "seg-new-customers" if orders_count <= 1 else None,
                            "seg-frequent-returners" if returns_count >= 2 else None),
            "ml_scores": {"model_version": MODEL_VERSION, "segment": ("Loyal upgrader" if tier in ("Gold", "Platinum") else "Occasional shopper" if orders_count else "New visitor"),
                          "next_best_action": ("recover_cart" if cart and cart["abandoned_days"] >= 2 else "track_order" if any(o["status"] in ("shipped", "out_for_delivery", "processing") for o in orders) else "recommend_products"),
                          "churn_risk": churn, "cart_recovery_propensity": cart_prop,
                          "upsell_propensity": clamp(0.3 + orders_count * 0.03 + r.uniform(-0.15, 0.3)),
                          "price_sensitivity": clamp(r.uniform(0.15, 0.9)),
                          "recommended_skus": r.sample(pool, min(len(pool), 3))},
        })
        if overrides:
            deep_update(row, overrides)
        return row

    # ---- prospects -------------------------------------------------------------
    def lead(self, overrides: dict | None = None) -> dict:
        r = self.r
        first, last = self.person()
        region = r.choice(C.REGIONS)
        city = r.choice(CITIES[region])
        employees = r.choice([6, 9, 12, 18, 24, 28, 40, 55, 80, 120, 260, 600, 1500])
        group = "LEAD-SMB" if employees < 50 else "LEAD-ENT"
        status = r.choice(["new", "new", "new", "qualified", "qualified", "consult_booked"])
        qualified = status != "new"
        seats = int(employees * r.uniform(0.3, 1.0)) if qualified else None
        score = clamp(0.3 + (0.2 if qualified else 0) + (0.15 if employees >= 50 else 0) + r.uniform(-0.15, 0.25))
        row = self.base("lead", self.uid("lead"), self.next_account(), first, last, city, region, group)
        company = f"{r.choice(COMPANY_A)} {r.choice(COMPANY_B)}"
        row.update({
            "phone": f"+1 555 01{r.randint(10, 99)} {r.randint(1000, 9999)}" if qualified else None,
            "identity": {"crm_id": f"LEAD-{r.randint(10**6, 10**7 - 1)}", "namespace": "leadId", "source": "crm"},
            "company": {"name": company, "industry": r.choice(C.INDUSTRIES), "employees": employees,
                        "size_band": "1-49" if employees < 50 else "50-249" if employees < 250 else "250+", "city": city},
            "lead": {"source": r.choice(["Workspace guide download", "Pricing page visit", "Trade show", "Referral", "Store visit", "Webinar"]),
                     "status": status, "score": score, "seats": seats,
                     "budget_band": r.choice(C.BUDGET_BANDS) if qualified else None,
                     "timeline": r.choice(C.TIMELINES) if qualified else None,
                     "interest": r.sample(C.CONSULT_TOPICS, r.randint(1, 2)), "owner": r.choice(C.SALES_REPS) if qualified else None,
                     "role": r.choice(["Office Manager", "Head of Operations", "Facilities Lead", "IT Director", "Founder", "Workplace Experience Manager"])},
            "browsing": {"viewed_skus": r.sample([p["sku"] for p in C.PRODUCTS], r.randint(2, 5)), "last_visit": self.day(-r.randint(0, 14)),
                         "sessions_30d": r.randint(1, 12)},
            "consultation": ({"date": self.day(r.randint(2, 8)), "time": r.choice(C.CONSULT_TIMES), "topic": r.choice(C.CONSULT_TOPICS),
                              "channel": "video", "rep": r.choice(C.SALES_REPS)} if status == "consult_booked" else None),
            "preferences": {"interests": r.sample(C.INTERESTS, 3), "communication_channel": r.choice(["email", "phone"]), "preferred_store": None},
            "segments": seg("seg-high-intent-b2b" if score >= 0.6 else "seg-researching-b2b"),
            "ml_scores": {"model_version": MODEL_VERSION, "segment": "High-intent buyer" if score >= 0.6 else "Researching",
                          "next_best_action": ("book_consultation" if status != "consult_booked" and score >= 0.5 else "capture_details" if not qualified else "nurture"),
                          "lead_score": score, "fit": clamp(0.4 + (0.2 if employees >= 16 else 0) + r.uniform(-0.2, 0.3)),
                          "recommended_bundle": C.bundle_for_seats(seats or employees)["code"]},
        })
        if overrides:
            deep_update(row, overrides)
        return row

    # ---- team members -----------------------------------------------------------
    def onboarding(self, tenure: int, done: set[str] | None = None) -> dict:
        r = self.r
        tasks = []
        for t in C.ONBOARDING_TASKS:
            complete = (t["task_id"] in done) if done is not None else (tenure > t["due_day"] + 5 or r.random() < min(0.95, tenure / max(t["due_day"], 1) * 0.6))
            tasks.append({"task_id": t["task_id"], "title": t["title"], "kind": t["kind"], "due_date": self.day(t["due_day"] - tenure),
                          "status": "complete" if complete else "pending",
                          "completed_at": self.day(-max(0, tenure - min(t["due_day"], tenure))) if complete else None})
        return {"status": "complete" if all(t["status"] == "complete" for t in tasks) else "in_progress", "tasks": tasks}

    def employee(self, overrides: dict | None = None, onboarding_done: set[str] | None = None, tenure: int | None = None) -> dict:
        r = self.r
        first, last = self.person()
        dept = r.choice(list(C.DEPARTMENTS))
        d = C.DEPARTMENTS[dept]
        region = r.choice(C.REGIONS)
        city = r.choice(CITIES[region])
        tenure = tenure if tenure is not None else r.choice([2, 5, 9, 14, 21, 45, 90, 200, 400, 800, 1500, 2600])
        title = r.choice(d["titles"])
        laptop = r.choice(C.LAPTOPS)
        systems = [s["id"] for s in C.SYSTEMS if s["default"]]
        if dept == "Store Operations":
            systems.append("pos")
        if dept in ("Technology", "Customer Care") or r.random() < 0.4:
            systems.append("vpn")
        tickets = []
        if r.random() < 0.3:
            cat = r.choice(C.IT_CATEGORIES)
            self.ticket_no += r.randint(1, 30)
            tickets.append({"ticket_id": f"INC-{self.ticket_no}", "category": cat["id"], "summary": r.choice([
                "Laptop fan is loud and the battery drains fast", "Can't join video calls from the meeting room",
                "Need the design suite installed", "Shared mailbox isn't showing in Outlook", "VPN drops every few minutes",
                "Register 2 card reader is offline"]), "status": r.choice(["open", "in_progress"]), "priority": r.choice(C.IT_PRIORITIES),
                "opened_at": self.day(-r.randint(0, 6)), "queue": cat["queue"]})
        onboarding = self.onboarding(tenure, onboarding_done)
        enrolled = tenure > C.ENROLLMENT_WINDOW_DAYS or any(t["task_id"] == "benefits" and t["status"] == "complete" for t in onboarding["tasks"])
        accrued = round(min(tenure / 30.4 * C.PTO_ACCRUAL_PER_MONTH + 3, 30), 1)
        used = round(min(accrued, r.choice([0, 0, 1, 2, 3, 5, 8])), 1)
        row = self.base("employee", self.uid("employee"), self.next_account(), first, last, city, region, d["group"])
        row.update({
            "identity": {"employee_number": f"LF{r.randint(10000, 99999)}", "namespace": "employeeId", "source": "hris"},
            "employment": {"title": title, "department": dept, "manager": " ".join(self.person()), "location": city,
                           "start_date": self.day(-tenure), "tenure_days": tenure,
                           "employment_type": "Full-time" if r.random() < 0.85 else "Part-time",
                           "is_manager": "Manager" in title or "Lead" in title},
            "it": {"devices": [{"asset_tag": f"LT-{r.randint(10000, 99999)}", "type": "laptop" if "Laptop" in laptop[0] else "tablet", "model": laptop[0], "os": laptop[1]}],
                   "systems_access": systems, "open_tickets": tickets, "password_expires_in_days": r.randint(1, 85),
                   "mfa_enrolled": tenure > 2 or r.random() < 0.8, "access_requests": []},
            "hr": {"benefits": {"enrolled": enrolled, "medical": r.choice(["MED-CORE", "MED-HSA", "MED-PLUS"]) if enrolled else None,
                                "dental": r.choice(["DEN-BASE", "DEN-PLUS", None]) if enrolled else None,
                                "vision": r.choice(["VIS-STD", None]) if enrolled else None,
                                "k401_pct": r.choice([0, 3, 4, 6, 8]) if enrolled else 0,
                                "enrollment_deadline": self.day(C.ENROLLMENT_WINDOW_DAYS - tenure) if not enrolled else None},
                   "pto": {"balance_days": round(accrued - used, 1), "used_days": used, "accrual_per_month": C.PTO_ACCRUAL_PER_MONTH, "requests": []},
                   "pay": {"frequency": "biweekly", "next_pay_date": self.payday(r.random() < 0.5)}},
            "onboarding": onboarding,
            "preferences": {"interests": r.sample(C.INTERESTS, 2), "communication_channel": "app", "preferred_store": None},
            "segments": seg("seg-new-hires" if tenure <= 30 else None, "seg-people-managers" if "Manager" in title or "Lead" in title else None,
                            "seg-store-teams" if dept == "Store Operations" else None),
            "ml_scores": {"model_version": MODEL_VERSION, "segment": "New hire" if tenure <= 30 else "Tenured team member",
                          "next_best_action": ("finish_onboarding" if onboarding["status"] != "complete" else "enroll_benefits" if not enrolled else "none")},
        })
        if overrides:
            deep_update(row, overrides)
        return row

    # ---- the three people the demo signs in as --------------------------------------
    def personas(self) -> list[dict]:
        saved = dict(self.n)
        city = "Brooklyn, NY"
        self.n["customer"] = 100
        maya = self.customer({
            "account_id": "5510101", "first_name": "Maya", "last_name": "Chen", "email": "maya.chen@example.com",
            "home_city": city, "region": "Northeast", "group_code": "CUS-NE", "phone": "+1 555 0142 1101",
            "loyalty": {"tier": "Gold", "points": 4180, "member_since": self.day(-890)},
            "preferences": {"interests": ["ergonomic", "standing", "home-office"], "communication_channel": "app", "preferred_store": "NYC"},
            "history": {"lifetime_value_usd": 4326.0, "orders_count": 9, "avg_order_usd": 480.67, "returns_count": 1},
            "segments": seg("seg-cart-abandoners", "seg-gold-plus", "seg-home-office"),
            "ml_scores": {"segment": "Loyal upgrader", "next_best_action": "recover_cart", "churn_risk": 0.18,
                          "cart_recovery_propensity": 0.81, "upsell_propensity": 0.74, "price_sensitivity": 0.42,
                          "recommended_skus": ["MON-VST-27", "MON-ARM-DUO", "DCK-HUB-12"]},
        })
        o1 = self.order(2, ["DSK-ARC-60", "MAT-STD-ANTI"], "shipped", city)
        o1.update({"order_id": "LF-881042", "eta": self.day(2), "delivery_window": "12pm-4pm", "carrier": "Larkfield Delivery",
                   "tracking_number": "LFD4410288173",
                   "events": [{"at": self.day(-2), "text": "Order placed"}, {"at": self.day(-1), "text": "Shipped with Larkfield Delivery"},
                              {"at": self.day(0), "text": "At the Brooklyn delivery hub"}]})
        o2 = self.order(16, ["CHR-LUM-BLK", "LGT-HLO-BAR"], "delivered", city)
        o2.update({"order_id": "LF-880517", "placed_at": self.day(-16), "eta": self.day(-12), "delivered_at": self.day(-12),
                   "events": [{"at": self.day(-16), "text": "Order placed"}, {"at": self.day(-15), "text": "Shipped with Larkfield Delivery"},
                              {"at": self.day(-12), "text": "Delivered"}]})
        o3 = self.order(57, ["KBD-TYP-MX"], "delivered", city)
        o3.update({"order_id": "LF-874233", "placed_at": self.day(-57), "eta": self.day(-52), "delivered_at": self.day(-52), "carrier": "UPS",
                   "delivery_window": None,
                   "events": [{"at": self.day(-57), "text": "Order placed"}, {"at": self.day(-56), "text": "Shipped with UPS"},
                              {"at": self.day(-52), "text": "Delivered"}]})
        maya["orders"] = [o1, o2, o3]
        maya["cart"] = self.cart(["MON-VST-27", "MON-ARM-DUO"], 3, 10)

        self.n["lead"] = 200
        daniel = self.lead({
            "account_id": "5520202", "first_name": "Daniel", "last_name": "Okafor", "email": "daniel@brightwaterstudio.example",
            "home_city": "Austin, TX", "region": "Southwest", "group_code": "LEAD-SMB", "phone": None,
            "company": {"name": "Brightwater Studio", "industry": "Architecture & Design", "employees": 28, "size_band": "1-49", "city": "Austin, TX"},
            "lead": {"source": "Workspace guide download", "status": "new", "score": 0.62, "seats": None, "budget_band": None,
                     "timeline": None, "interest": ["Hybrid office refresh", "Ergonomic assessment"], "owner": None, "role": "Office Manager"},
            "browsing": {"viewed_skus": ["DSK-ARC-48", "CHR-LUM-SND", "MON-VST-27", "SPK-ORB-CNF"], "last_visit": self.day(-1), "sessions_30d": 7},
            "consultation": None,
            "preferences": {"interests": ["ergonomic", "standing", "meeting-room"], "communication_channel": "email", "preferred_store": "AUS"},
            "segments": seg("seg-high-intent-b2b"),
            "ml_scores": {"segment": "High-intent buyer", "next_best_action": "book_consultation", "lead_score": 0.62, "fit": 0.78,
                          "recommended_bundle": "WS-TEAM"},
        })

        self.n["employee"] = 300
        self.ticket_no = 204_870
        sofia = self.employee({
            "account_id": "5530303", "first_name": "Sofia", "last_name": "Alvarez", "email": "sofia.alvarez@larkfield.example",
            "home_city": "Charlotte, NC", "region": "Southeast", "group_code": "EMP-CARE",
            "identity": {"employee_number": "LF48213"},
            "employment": {"title": "Care Specialist", "department": "Customer Care", "manager": "Marcus Reid", "location": "Charlotte, NC",
                           "employment_type": "Full-time", "is_manager": False},
            "it": {"devices": [{"asset_tag": "LT-48213", "type": "laptop", "model": "Aero 14 Laptop", "os": "Windows 11"}],
                   "systems_access": ["sso", "email", "hr-portal"], "password_expires_in_days": 5, "mfa_enrolled": True,
                   "open_tickets": [{"ticket_id": "INC-204871", "category": "vpn", "summary": "VPN client won't connect from home",
                                     "status": "open", "priority": "normal", "opened_at": self.day(-1), "queue": "Network"}]},
            "hr": {"benefits": {"enrolled": False, "medical": None, "dental": None, "vision": None, "k401_pct": 0,
                                "enrollment_deadline": self.day(24)},
                   "pto": {"balance_days": 3.0, "used_days": 0, "requests": []},
                   "pay": {"frequency": "biweekly", "next_pay_date": self.payday()}},
            "preferences": {"interests": ["calls", "ergonomic"], "communication_channel": "app", "preferred_store": "CLT"},
            "segments": seg("seg-new-hires"),
            "ml_scores": {"segment": "New hire", "next_best_action": "finish_onboarding"},
        }, onboarding_done={"i9", "w4", "emergency-contact"}, tenure=6)
        self.n = {k: max(v, saved[k]) for k, v in self.n.items()}
        self.n.update(saved)
        rows = [maya, daniel, sofia]
        for row, uid in zip(rows, PERSONAS):
            row["user_id"] = uid
        return rows

    def next_row(self) -> dict:
        x = self.r.random()
        return self.customer() if x < 0.74 else self.lead() if x < 0.86 else self.employee()

    def coverage(self) -> list[dict]:
        """A few users in every group right after the personas, so even a
        small export (tests, the in-memory quick start) covers the whole company."""
        rows = []
        for code, g in C.GROUPS.items():
            for _ in range(4):
                if g["audience"] == "customer":
                    region = g["region"]
                    rows.append(self.customer({"region": region, "group_code": code, "home_city": self.r.choice(CITIES[region])}))
                elif g["audience"] == "lead":
                    n = self.r.choice([8, 14, 30]) if code == "LEAD-SMB" else self.r.choice([90, 300, 1200])
                    rows.append(self.lead({"group_code": code, "company": {"employees": n, "size_band": "1-49" if n < 50 else "50-249" if n < 250 else "250+"}}))
                else:
                    dept = g["department"]
                    rows.append(self.employee({"group_code": code, "employment": {"department": dept, "title": self.r.choice(C.DEPARTMENTS[dept]["titles"])}}))
        return rows


def deep_update(base: dict, upd: dict):
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-date", default=dt.date.today().isoformat())
    ap.add_argument("--target-mb", type=float, default=24.0, help="approximate total size in MiB")
    ap.add_argument("--parts", type=int, default=2, help="number of part files")
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "data", "onechat-export"))
    args = ap.parse_args(argv)

    export_date = dt.date.fromisoformat(args.export_date)
    g = Gen(export_date, args.seed)
    target = int(args.target_mb * 1024 * 1024)
    per_part = target // args.parts + 1
    out_dir = os.path.abspath(os.path.join(args.out, f"exportTime={export_date:%Y%m%d}"))
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.startswith("part-") or f in ("_SUCCESS", "_manifest.json"):
            os.remove(os.path.join(out_dir, f))

    job_uuid = uuid.UUID(int=g.r.getrandbits(128))
    written, rows = 0, 0
    by_audience = {"customer": 0, "lead": 0, "employee": 0}
    files = []
    pending = g.personas() + g.coverage()
    for part in range(args.parts):
        name = f"part-{part:05d}-{job_uuid}-c000.json"
        part_bytes, part_rows = 0, 0
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            while pending or (part_bytes < per_part and written < target):
                row = pending.pop(0) if pending else g.next_row()
                line = json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
                b = len(line.encode("utf-8"))
                fh.write(line)
                part_bytes += b
                written += b
                part_rows += 1
                by_audience[row["audience"]] += 1
        rows += part_rows
        files.append({"file": name, "rows": part_rows, "bytes": part_bytes})
        print(f"  {name}  {part_rows:>7,} rows  {part_bytes / 1048576:6.1f} MiB", flush=True)

    manifest = {
        "system": "larkfield-data-platform", "dataset": "onechat_people", "flow": "onechat-nightly-export",
        "sources": {"customer": "CDP + commerce platform", "lead": "CRM", "employee": "HRIS + ITSM"},
        "export_time": f"{export_date:%Y%m%d}", "export_date": export_date.isoformat(),
        "schema_version": SCHEMA_VERSION, "model_version": MODEL_VERSION,
        "format": "jsonl", "rows": rows, "by_audience": by_audience, "bytes": written, "files": files,
        "generator": "datagen/generate_mock_export.py", "seed": args.seed, "demo_personas": PERSONAS,
    }
    with open(os.path.join(out_dir, "_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    open(os.path.join(out_dir, "_SUCCESS"), "w").close()
    print(f"Wrote {rows:,} people ({by_audience['customer']:,} customers, {by_audience['lead']:,} prospects, "
          f"{by_audience['employee']:,} team members) = {written / 1048576:.1f} MiB to {out_dir}")


if __name__ == "__main__":
    main()
