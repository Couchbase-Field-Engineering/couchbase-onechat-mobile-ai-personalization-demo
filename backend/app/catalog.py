"""Reference data for the OneChat demo company.

**Larkfield** is a fictional home-office and electronics retailer: stores in a
dozen cities, an online shop, a business division (Larkfield for Business:
workspace fit-outs sold through consultations) and a few thousand team
members. One assistant - OneChat - serves all of them:

* customers      support & FAQs, order tracking, returns and exchanges, cart recovery
* prospects      product discovery, lead capture and qualification, consultations
* team members   IT help desk, HR benefits, onboarding paperwork

Everything here is shared by the mock export generator
(datagen/generate_mock_export.py), the business logic (actions.py), the For
You ranking (personalization.py) and the Knowledge Base documents
(knowledge.py). Names, prices and policies are invented demo data.
"""
from __future__ import annotations

import datetime as dt
import hashlib

COMPANY = {
    "name": "Larkfield",
    "legal_name": "Larkfield Home & Tech, Inc.",
    "tagline": "Good tools for the places you work.",
    "support_phone": "1-800-555-0142",
    "support_hours": "7am-10pm ET, every day",
    "business_brand": "Larkfield for Business",
    "loyalty_program": "Larkfield Rewards",
    "website": "larkfield.example",
}

AUDIENCES = {"customer": "Customer", "lead": "Business prospect", "employee": "Team member"}

# The four things a company-wide chatbot is asked to do, and the intents
# (assistant.py) that belong to each. The app shows the area on every answer.
AREAS = {
    "support": {"name": "Customer Support", "icon": "help-buoy", "audiences": ["customer", "lead", "employee"]},
    "commerce": {"name": "Orders & Returns", "icon": "cube", "audiences": ["customer"]},
    "sales": {"name": "Sales & Consultations", "icon": "briefcase", "audiences": ["customer", "lead"]},
    "workplace": {"name": "IT & HR", "icon": "id-card", "audiences": ["employee"]},
}

# Groups the company-wide workload draws its users from (workload.py): every
# customer region, both prospect tiers and every department gets sessions.
GROUPS: dict[str, dict] = {
    "CUS-NE": {"name": "Customers · Northeast", "audience": "customer", "region": "Northeast"},
    "CUS-SE": {"name": "Customers · Southeast", "audience": "customer", "region": "Southeast"},
    "CUS-MW": {"name": "Customers · Midwest", "audience": "customer", "region": "Midwest"},
    "CUS-SW": {"name": "Customers · Southwest", "audience": "customer", "region": "Southwest"},
    "CUS-W": {"name": "Customers · West", "audience": "customer", "region": "West"},
    "LEAD-SMB": {"name": "Prospects · Small business", "audience": "lead", "region": None},
    "LEAD-ENT": {"name": "Prospects · Mid-market & enterprise", "audience": "lead", "region": None},
    "EMP-STORE": {"name": "Team · Store Operations", "audience": "employee", "department": "Store Operations"},
    "EMP-CARE": {"name": "Team · Customer Care", "audience": "employee", "department": "Customer Care"},
    "EMP-TECH": {"name": "Team · Technology", "audience": "employee", "department": "Technology"},
    "EMP-SUPPLY": {"name": "Team · Supply Chain", "audience": "employee", "department": "Supply Chain"},
    "EMP-CORP": {"name": "Team · Finance & People", "audience": "employee", "department": "Finance & People"},
}

STORES = [
    {"id": "NYC", "name": "Larkfield Flatiron", "city": "New York, NY", "region": "Northeast", "hours": "Mon-Sat 9am-9pm, Sun 10am-7pm"},
    {"id": "BOS", "name": "Larkfield Seaport", "city": "Boston, MA", "region": "Northeast", "hours": "Mon-Sat 9am-9pm, Sun 10am-7pm"},
    {"id": "PHL", "name": "Larkfield Rittenhouse", "city": "Philadelphia, PA", "region": "Northeast", "hours": "Mon-Sat 10am-8pm, Sun 11am-6pm"},
    {"id": "ATL", "name": "Larkfield Ponce", "city": "Atlanta, GA", "region": "Southeast", "hours": "Mon-Sat 10am-9pm, Sun 11am-7pm"},
    {"id": "MIA", "name": "Larkfield Wynwood", "city": "Miami, FL", "region": "Southeast", "hours": "Mon-Sat 10am-9pm, Sun 11am-7pm"},
    {"id": "CLT", "name": "Larkfield South End", "city": "Charlotte, NC", "region": "Southeast", "hours": "Mon-Sat 10am-8pm, Sun 11am-6pm"},
    {"id": "CHI", "name": "Larkfield Fulton Market", "city": "Chicago, IL", "region": "Midwest", "hours": "Mon-Sat 9am-9pm, Sun 10am-7pm"},
    {"id": "MSP", "name": "Larkfield North Loop", "city": "Minneapolis, MN", "region": "Midwest", "hours": "Mon-Sat 10am-8pm, Sun 11am-6pm"},
    {"id": "AUS", "name": "Larkfield Domain", "city": "Austin, TX", "region": "Southwest", "hours": "Mon-Sat 10am-9pm, Sun 11am-7pm"},
    {"id": "PHX", "name": "Larkfield Biltmore", "city": "Phoenix, AZ", "region": "Southwest", "hours": "Mon-Sat 10am-8pm, Sun 11am-6pm"},
    {"id": "SEA", "name": "Larkfield Capitol Hill", "city": "Seattle, WA", "region": "West", "hours": "Mon-Sat 9am-9pm, Sun 10am-7pm"},
    {"id": "SFO", "name": "Larkfield Hayes Valley", "city": "San Francisco, CA", "region": "West", "hours": "Mon-Sat 9am-9pm, Sun 10am-7pm"},
]
STORE_BY_ID = {s["id"]: s for s in STORES}
REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
REGION_GROUP = {"Northeast": "CUS-NE", "Southeast": "CUS-SE", "Midwest": "CUS-MW", "Southwest": "CUS-SW", "West": "CUS-W"}

# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------
PRODUCTS = [
    {"sku": "DSK-ARC-60", "name": "Arc Standing Desk 60\"", "category": "Desks", "price": 649, "tags": ["standing", "ergonomic", "home-office", "desk"], "family": "arc-desk", "blurb": "Dual-motor sit-stand desk with four height presets and a solid oak top."},
    {"sku": "DSK-ARC-48", "name": "Arc Standing Desk 48\"", "category": "Desks", "price": 549, "tags": ["standing", "ergonomic", "small-space", "desk"], "family": "arc-desk", "blurb": "The Arc in a compact footprint for apartments and spare rooms."},
    {"sku": "DSK-FLD-42", "name": "Fold Writing Desk", "category": "Desks", "price": 289, "tags": ["small-space", "home-office", "desk"], "family": "fold-desk", "blurb": "Wall-friendly writing desk with a cable tray and a hidden drawer."},
    {"sku": "CHR-LUM-BLK", "name": "Lumen Ergonomic Chair · Graphite", "category": "Chairs", "price": 429, "tags": ["ergonomic", "chair", "home-office"], "family": "lumen-chair", "blurb": "Adjustable lumbar, 4D arms and a breathable mesh back; 12-year warranty."},
    {"sku": "CHR-LUM-SND", "name": "Lumen Ergonomic Chair · Sand", "category": "Chairs", "price": 429, "tags": ["ergonomic", "chair", "home-office"], "family": "lumen-chair", "blurb": "The Lumen in a warm sand fabric."},
    {"sku": "CHR-PRC-GRY", "name": "Perch Task Chair", "category": "Chairs", "price": 219, "tags": ["chair", "small-space", "value"], "family": "perch-chair", "blurb": "A lighter task chair with a tilt lock and flip-up arms."},
    {"sku": "MON-VST-27", "name": "Vista 27\" 4K Monitor", "category": "Monitors", "price": 379, "tags": ["monitor", "creative", "home-office"], "family": "vista-monitor", "blurb": "27-inch 4K IPS with USB-C power delivery (90W) and a height-adjustable stand."},
    {"sku": "MON-VST-34", "name": "Vista 34\" Ultrawide", "category": "Monitors", "price": 599, "tags": ["monitor", "creative", "multitasking"], "family": "vista-monitor", "blurb": "Curved 34-inch ultrawide for two full windows side by side."},
    {"sku": "MON-ARM-DUO", "name": "Dual Monitor Arm", "category": "Accessories", "price": 129, "tags": ["ergonomic", "accessory", "multitasking"], "family": "monitor-arm", "blurb": "Gas-spring arm for two displays up to 32 inches."},
    {"sku": "DCK-HUB-12", "name": "Relay 12-in-1 Dock", "category": "Accessories", "price": 189, "tags": ["accessory", "laptop", "multitasking"], "family": "relay-dock", "blurb": "One cable to your laptop: dual 4K, ethernet, SD and 100W charging."},
    {"sku": "KBD-TYP-MX", "name": "Tactile Mechanical Keyboard", "category": "Accessories", "price": 139, "tags": ["accessory", "creative", "ergonomic"], "family": "tactile-keyboard", "blurb": "Hot-swappable switches, three devices over Bluetooth."},
    {"sku": "MSE-GLD-ERG", "name": "Glide Vertical Mouse", "category": "Accessories", "price": 69, "tags": ["accessory", "ergonomic", "value"], "family": "glide-mouse", "blurb": "A 57-degree grip that takes the twist out of your wrist."},
    {"sku": "HDS-QT-ANC", "name": "Quiet Noise-Cancelling Headset", "category": "Audio", "price": 249, "tags": ["audio", "calls", "travel"], "family": "quiet-headset", "blurb": "Adaptive noise cancelling with a boom mic certified for video calls."},
    {"sku": "SPK-ORB-CNF", "name": "Orbit Conference Speaker", "category": "Audio", "price": 199, "tags": ["audio", "calls", "meeting-room"], "family": "orbit-speaker", "blurb": "360-degree pickup for rooms of up to eight people."},
    {"sku": "CAM-CLR-4K", "name": "Clarity 4K Webcam", "category": "Video", "price": 159, "tags": ["video", "calls", "creative"], "family": "clarity-webcam", "blurb": "Auto-framing 4K camera with a privacy shutter."},
    {"sku": "LGT-HLO-BAR", "name": "Halo Monitor Light Bar", "category": "Lighting", "price": 89, "tags": ["lighting", "accessory", "value"], "family": "halo-light", "blurb": "Glare-free desk lighting that clips onto any monitor."},
    {"sku": "LGT-BEAM-FL", "name": "Beam Floor Lamp", "category": "Lighting", "price": 179, "tags": ["lighting", "home-office"], "family": "beam-lamp", "blurb": "Tunable white floor lamp with a reading arm."},
    {"sku": "STG-CUB-3", "name": "Cubby 3-Drawer Pedestal", "category": "Storage", "price": 199, "tags": ["storage", "home-office"], "family": "cubby", "blurb": "Locking pedestal that tucks under any Larkfield desk."},
    {"sku": "STG-SHL-5", "name": "Ladder Shelf 5-Tier", "category": "Storage", "price": 159, "tags": ["storage", "small-space"], "family": "ladder-shelf", "blurb": "Leaning oak shelf for books, plants and a printer."},
    {"sku": "LAP-AER-14", "name": "Aero 14 Laptop", "category": "Computers", "price": 1299, "tags": ["laptop", "travel", "creative"], "family": "aero-laptop", "blurb": "14-inch, 16GB / 512GB, 18-hour battery; 2-year warranty included."},
    {"sku": "TAB-NOTE-11", "name": "Note 11 Tablet", "category": "Computers", "price": 499, "tags": ["tablet", "travel", "creative"], "family": "note-tablet", "blurb": "11-inch tablet with pen support for notes and markup."},
    {"sku": "PRT-INK-AIO", "name": "Inkwell All-in-One Printer", "category": "Printers", "price": 229, "tags": ["printer", "home-office", "value"], "family": "inkwell-printer", "blurb": "Print, scan and copy with refillable tanks: two years of ink in the box."},
    {"sku": "NET-MSH-3", "name": "Mesh Wi-Fi 6 System (3-pack)", "category": "Networking", "price": 279, "tags": ["networking", "home-office"], "family": "mesh-wifi", "blurb": "Whole-home Wi-Fi 6 with a dedicated work network."},
    {"sku": "MAT-STD-ANTI", "name": "Anti-Fatigue Standing Mat", "category": "Accessories", "price": 79, "tags": ["standing", "ergonomic", "accessory", "value"], "family": "standing-mat", "blurb": "Contoured mat that keeps you moving at a standing desk."},
]
PRODUCT_BY_SKU = {p["sku"]: p for p in PRODUCTS}
INTERESTS = ["ergonomic", "standing", "small-space", "creative", "multitasking", "calls", "travel", "value", "home-office", "meeting-room"]

# Larkfield for Business: workspace packages sold through a consultation.
BUNDLES = [
    {"code": "WS-STARTER", "name": "Workspace Starter", "seats": (1, 15), "price_per_seat": 890,
     "includes": ["Perch Task Chair", "Fold Writing Desk", "Halo Monitor Light Bar"],
     "blurb": "A complete desk setup per seat, delivered and assembled in two weeks."},
    {"code": "WS-TEAM", "name": "Workspace Team", "seats": (16, 75), "price_per_seat": 1450,
     "includes": ["Arc Standing Desk 48\"", "Lumen Ergonomic Chair", "Vista 27\" 4K Monitor", "Relay 12-in-1 Dock"],
     "blurb": "Sit-stand desks and docking for hybrid teams, with a floor plan and phased delivery."},
    {"code": "WS-ENTERPRISE", "name": "Workspace Enterprise", "seats": (76, 5000), "price_per_seat": 1320,
     "includes": ["Arc Standing Desk 60\"", "Lumen Ergonomic Chair", "Vista 34\" Ultrawide", "meeting-room kits", "asset tagging"],
     "blurb": "Multi-site rollouts with a dedicated project manager, volume pricing and lease options."},
]
BUNDLE_BY_CODE = {b["code"]: b for b in BUNDLES}
INDUSTRIES = ["Software", "Architecture & Design", "Healthcare", "Legal", "Financial Services", "Education", "Nonprofit",
              "Marketing Agency", "Logistics", "Biotech"]
BUDGET_BANDS = ["under $10k", "$10k-$50k", "$50k-$150k", "$150k+"]
TIMELINES = ["this month", "1-3 months", "3-6 months", "just researching"]
CONSULT_TOPICS = ["Workspace fit-out", "Hybrid office refresh", "Ergonomic assessment", "Meeting rooms & AV", "Home-office program"]
CONSULT_TIMES = ["09:00", "10:30", "13:00", "14:30", "16:00"]
CONSULT_CHANNELS = ["video", "phone", "in-store"]
SALES_REPS = ["Jordan Avery", "Sam Whitlock", "Renee Castellano", "Imani Brooks", "Theo Lindqvist"]

# --------------------------------------------------------------------------
# Orders, delivery, returns
# --------------------------------------------------------------------------
CARRIERS = ["Larkfield Delivery", "UPS", "FedEx"]
DELIVERY_WINDOWS = ["8am-12pm", "12pm-4pm", "4pm-8pm"]
ORDER_STATUSES = ["processing", "shipped", "out_for_delivery", "delivered", "cancelled"]
RETURN_REASONS = ["Changed my mind", "Wrong size or fit", "Arrived damaged", "Not as described", "Found a better price", "Ordered by mistake"]
RETURN_WINDOW_DAYS = {"Member": 30, "Silver": 30, "Gold": 45, "Platinum": 60}
LOYALTY_TIERS = ["Member", "Silver", "Gold", "Platinum"]
FREE_SHIPPING_MIN = 75
STANDARD_SHIPPING = 7.95
GOODWILL_CREDIT_MAX = 150

# --------------------------------------------------------------------------
# Workplace: IT help desk and HR
# --------------------------------------------------------------------------
DEPARTMENTS = {
    "Store Operations": {"group": "EMP-STORE", "titles": ["Store Associate", "Assistant Store Manager", "Store Manager", "Visual Merchandiser"]},
    "Customer Care": {"group": "EMP-CARE", "titles": ["Care Specialist", "Senior Care Specialist", "Care Team Lead", "Quality Analyst"]},
    "Technology": {"group": "EMP-TECH", "titles": ["Software Engineer", "Data Analyst", "Site Reliability Engineer", "Product Manager"]},
    "Supply Chain": {"group": "EMP-SUPPLY", "titles": ["Inventory Planner", "Logistics Coordinator", "Warehouse Lead", "Buyer"]},
    "Finance & People": {"group": "EMP-CORP", "titles": ["Accountant", "People Partner", "Payroll Specialist", "Financial Analyst"]},
}
IT_CATEGORIES = [
    {"id": "access", "name": "Account & access", "queue": "Identity", "sla_hours": 4},
    {"id": "hardware", "name": "Laptop & hardware", "queue": "Deskside", "sla_hours": 8},
    {"id": "vpn", "name": "VPN & network", "queue": "Network", "sla_hours": 4},
    {"id": "software", "name": "Software install", "queue": "Deskside", "sla_hours": 8},
    {"id": "email", "name": "Email & calendar", "queue": "Collaboration", "sla_hours": 8},
    {"id": "pos", "name": "Store point of sale", "queue": "Store Systems", "sla_hours": 2},
]
IT_CATEGORY_BY_ID = {c["id"]: c for c in IT_CATEGORIES}
IT_PRIORITIES = ["low", "normal", "high"]
# Systems a team member can ask for. `approval` ones change what a person can
# see or spend, so AOM holds the request for a human (request_system_access).
SYSTEMS = [
    {"id": "sso", "name": "Larkfield SSO", "approval": False, "default": True},
    {"id": "email", "name": "Email & calendar", "approval": False, "default": True},
    {"id": "hr-portal", "name": "People Portal", "approval": False, "default": True},
    {"id": "vpn", "name": "Remote VPN", "approval": False, "default": False},
    {"id": "pos", "name": "Store point of sale", "approval": False, "default": False},
    {"id": "analytics", "name": "Sales Analytics workspace", "approval": True, "default": False},
    {"id": "erp-finance", "name": "Finance ERP", "approval": True, "default": False},
    {"id": "crm-admin", "name": "CRM admin console", "approval": True, "default": False},
    {"id": "prod-db", "name": "Production database (read-only)", "approval": True, "default": False},
]
SYSTEM_BY_ID = {s["id"]: s for s in SYSTEMS}
LAPTOPS = [("Aero 14 Laptop", "macOS 15"), ("Aero 14 Laptop", "Windows 11"), ("Note 11 Tablet", "iPadOS 18")]

BENEFIT_PLANS = {
    "medical": [
        {"id": "MED-CORE", "name": "Core PPO", "employee_cost_per_paycheck": 48, "deductible": 1500, "blurb": "Broad network, $1,500 deductible, $25 office visits."},
        {"id": "MED-HSA", "name": "HSA Advantage", "employee_cost_per_paycheck": 22, "deductible": 3200, "blurb": "High-deductible plan with a $1,000 company HSA contribution."},
        {"id": "MED-PLUS", "name": "Plus PPO", "employee_cost_per_paycheck": 92, "deductible": 500, "blurb": "Lowest deductible and $15 office visits."},
    ],
    "dental": [
        {"id": "DEN-BASE", "name": "Dental Base", "employee_cost_per_paycheck": 6, "blurb": "Two cleanings a year and basic restorative care."},
        {"id": "DEN-PLUS", "name": "Dental Plus", "employee_cost_per_paycheck": 14, "blurb": "Adds orthodontia and major restorative care."},
    ],
    "vision": [
        {"id": "VIS-STD", "name": "Vision Standard", "employee_cost_per_paycheck": 3, "blurb": "Annual exam and a $180 frame allowance."},
    ],
}
PLAN_BY_ID = {p["id"]: {**p, "kind": k} for k, plans in BENEFIT_PLANS.items() for p in plans}
ENROLLMENT_WINDOW_DAYS = 30          # new hires enroll within 30 days of their start date
PTO_ACCRUAL_PER_MONTH = 1.5          # days
K401_MATCH_PCT = 4
ONBOARDING_TASKS = [
    {"task_id": "i9", "title": "Form I-9 employment eligibility", "kind": "form", "due_day": 3,
     "detail": "Section 1 is due by your first day; bring your documents to your manager or a People Partner within three days."},
    {"task_id": "w4", "title": "Form W-4 tax withholding", "kind": "form", "due_day": 7,
     "detail": "Sets the federal tax withheld from each paycheck. You can change it any time in the People Portal."},
    {"task_id": "direct-deposit", "title": "Direct deposit", "kind": "form", "due_day": 7,
     "detail": "Add the bank account your pay goes to. Set it up before the payroll cut-off to avoid a paper check."},
    {"task_id": "handbook", "title": "Team Handbook acknowledgment", "kind": "sign", "due_day": 10,
     "detail": "Read the Team Handbook and sign to confirm you've received it."},
    {"task_id": "code-of-conduct", "title": "Code of Conduct", "kind": "sign", "due_day": 10,
     "detail": "Our standards for how we treat customers and each other."},
    {"task_id": "security-training", "title": "Security awareness training", "kind": "training", "due_day": 14,
     "detail": "A 25-minute course on phishing, passwords and customer data. Required before production access."},
    {"task_id": "benefits", "title": "Benefits enrollment", "kind": "form", "due_day": 30,
     "detail": "Choose medical, dental and vision within 30 days of your start date or wait for open enrollment."},
    {"task_id": "emergency-contact", "title": "Emergency contact", "kind": "form", "due_day": 14,
     "detail": "Who we should call if something happens at work."},
]
ONBOARDING_BY_ID = {t["task_id"]: t for t in ONBOARDING_TASKS}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def a_or_an(noun: str) -> str:
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


def return_window_days(tier: str | None) -> int:
    return RETURN_WINDOW_DAYS.get(tier or "Member", 30)


def bundle_for_seats(seats: int | None) -> dict:
    n = int(seats or 10)
    return next((b for b in BUNDLES if b["seats"][0] <= n <= b["seats"][1]), BUNDLES[-1])


def exchange_options(sku: str) -> list[dict]:
    """What an item can be exchanged for: the same product family first (another
    size or colour), then the same category."""
    p = PRODUCT_BY_SKU.get(sku)
    if not p:
        return []
    same = [x for x in PRODUCTS if x["family"] == p["family"] and x["sku"] != sku]
    cat = [x for x in PRODUCTS if x["category"] == p["category"] and x["family"] != p["family"]]
    return (same + cat)[:4]


def business_days(start: dt.date, n: int) -> list[dt.date]:
    out, d = [], start
    while len(out) < n:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def slot_id(date: str, time: str) -> str:
    return f"{date}T{time}"


def initial_inventory(today: dt.date) -> dict:
    """Unsold stock per SKU and open consultation seats per slot. One
    CAS-protected document (`inv::v1`): two people can't take the last desk or
    the same consultation slot. Deterministic, so a reset restores it."""
    stock = {p["sku"]: 3 + _h("stock", p["sku"]) % 40 for p in PRODUCTS}
    stock["DSK-ARC-48"] = 2          # scarcity for the exchange story
    slots = {}
    for d in business_days(today, 8):
        for t in CONSULT_TIMES:
            slots[slot_id(d.isoformat(), t)] = _h("slot", d.isoformat(), t) % 4   # 0 = fully booked
    return {"stock": stock, "slots": slots}


def public_catalog() -> dict:
    """What every signed-in user's phone gets (`catalog::v1`, channel `catalog`)."""
    return {
        "company": COMPANY,
        "areas": AREAS,
        "stores": STORES,
        "products": PRODUCTS,
        "bundles": [{**b, "seats": list(b["seats"])} for b in BUNDLES],
        "delivery_windows": DELIVERY_WINDOWS,
        "return_reasons": RETURN_REASONS,
        "return_window_days": RETURN_WINDOW_DAYS,
        "consult_topics": CONSULT_TOPICS,
        "consult_times": CONSULT_TIMES,
        "consult_channels": CONSULT_CHANNELS,
        "budget_bands": BUDGET_BANDS,
        "timelines": TIMELINES,
    }


def workplace_catalog() -> dict:
    """Team-members-only reference data (`handbook::v1`, channel `employees`):
    Sync Gateway never sends this document to a customer's phone."""
    return {
        "it_categories": IT_CATEGORIES,
        "it_priorities": IT_PRIORITIES,
        "systems": SYSTEMS,
        "benefit_plans": BENEFIT_PLANS,
        "onboarding_tasks": ONBOARDING_TASKS,
        "pto_accrual_per_month": PTO_ACCRUAL_PER_MONTH,
        "k401_match_pct": K401_MATCH_PCT,
        "enrollment_window_days": ENROLLMENT_WINDOW_DAYS,
    }
