"""Knowledge Base documents published to AOM by the nightly loader.

Three kinds:

* **Help Center** - what any customer or prospect may be told: store hours,
  delivery, returns, pricing, accounts, products and Larkfield for Business.
  Contains no personal data, so answers grounded only in it are safe to share
  across users through AOM's LLM cache. The customer-facing RAG application
  (`onechat-assistant`) is scoped to this document.
* **Team Handbook** - IT help desk, benefits, time off, pay and onboarding.
  For team members only: the workplace RAG application (`onechat-workplace`)
  is scoped to it, and its phone copy travels on the `employees` channel.
* **User profile** - one per person, rendered from that night's export as
  plain prose. The assistant retrieves it with a `document_id`-scoped search,
  so an answer can only ever be grounded in the asker's *own* profile.

`FAQ` is the bundled copy of the CMS entries, served when no CMS endpoint is
configured (sources.py). Entries are also synced to the phone - customer
entries inside `catalog::v1`, team entries inside `handbook::v1` - so the app
can answer the common questions offline from Couchbase Lite.
"""
from __future__ import annotations

from . import catalog as C
from .docs import days_until

_CO = C.COMPANY

FAQ = [
    # ---- Customer Support & FAQs ------------------------------------------------
    {"section": "Stores", "audience": "all", "intent": "general",
     "q": "What are your store hours?",
     "a": "Most Larkfield stores are open Monday to Saturday 9am-9pm and Sunday 10am-7pm; a few open at 10am and close at 8pm. "
          "Holiday hours are posted on each store's page. Customer care is open 7am-10pm ET every day, and OneChat answers any time.",
     "keywords": ["store hours", "hours", "open", "close", "closing", "when are you open", "sunday"]},
    {"section": "Delivery", "audience": "all", "intent": "general",
     "q": "How long does delivery take?",
     "a": "Small parcels ship with UPS or FedEx and arrive in 3-5 business days. Desks, chairs and storage come with Larkfield "
          "Delivery in 4-6 business days, in a four-hour window you can move yourself in the app. Same-day pickup is free at any "
          "store for items in stock.",
     "keywords": ["delivery", "deliver", "shipping time", "how long", "arrive", "ship", "pickup", "delivery times"]},
    {"section": "Delivery", "audience": "all", "intent": "general",
     "q": "How much is shipping?",
     "a": f"Shipping is free on orders of ${C.FREE_SHIPPING_MIN} or more and ${C.STANDARD_SHIPPING} below that. Larkfield Delivery "
          "of furniture includes room-of-choice placement; assembly is $49 per item, and free for Platinum members.",
     "keywords": ["shipping cost", "shipping", "free shipping", "delivery fee", "assembly", "how much is shipping"]},
    {"section": "Returns", "audience": "all", "intent": "return",
     "q": "What is your return policy?",
     "a": "You can return most items within 30 days of delivery for a full refund - 45 days for Gold members and 60 for Platinum. "
          "Returns are free: start one in OneChat, then drop the item at any Larkfield store or UPS location with your return code. "
          "Refunds go back to the original payment method within 3 business days of the scan.",
     "keywords": ["return policy", "return", "returns", "refund", "send back", "money back", "return window"]},
    {"section": "Returns", "audience": "all", "intent": "return",
     "q": "Can I exchange an item?",
     "a": "Yes. Within your return window you can exchange for another size or colour of the same product, or another item in the "
          "same category. The replacement ships within two business days, before we receive the original; you pay or get back any "
          "price difference.",
     "keywords": ["exchange", "swap", "different size", "different color", "different colour", "replace"]},
    {"section": "Returns", "audience": "all", "intent": "service_recovery",
     "q": "What if my order arrives damaged?",
     "a": "Tell us within 7 days of delivery and we'll replace it or refund it at no cost - you don't need to keep the packaging. "
          "If the item is outside its return window, a care supervisor can approve a store credit as a goodwill gesture.",
     "keywords": ["damaged", "broken", "defective", "arrived damaged", "missing parts", "faulty"]},
    {"section": "Pricing", "audience": "all", "intent": "general",
     "q": "Do you price match?",
     "a": "We match the current price of an identical, in-stock item at a major US retailer, at checkout or within 14 days of your "
          "purchase. Marketplace sellers, clearance and membership-only prices are excluded.",
     "keywords": ["price match", "price", "pricing", "cheaper", "better price", "price adjustment", "discount"]},
    {"section": "Pricing", "audience": "all", "intent": "general",
     "q": "What payment methods do you accept?",
     "a": "All major cards, Apple Pay, Google Pay, PayPal, Larkfield gift cards and store credit. Orders over $299 can be split into "
          "four interest-free payments at checkout.",
     "keywords": ["payment", "pay", "paypal", "apple pay", "gift card", "installments", "financing", "credit card"]},
    {"section": "Orders", "audience": "all", "intent": "order",
     "q": "How do I track my order?",
     "a": "Ask OneChat \"where is my order?\" or open Activity: every order shows its carrier, tracking number and delivery day. "
          "Larkfield Delivery orders also show the four-hour window, and you'll get a text when the driver is 30 minutes away.",
     "keywords": ["track", "tracking", "order status", "where is my order", "shipment"]},
    {"section": "Orders", "audience": "all", "intent": "order",
     "q": "Can I change or cancel an order?",
     "a": "You can cancel free of charge until an order ships, and move a Larkfield Delivery day or window any time before it's out "
          "for delivery. After it ships, refuse the delivery or start a return once it arrives.",
     "keywords": ["cancel", "change order", "modify order", "cancel order", "reschedule"]},
    {"section": "Orders", "audience": "all", "intent": "cart",
     "q": "Why did I get a cart reminder offer?",
     "a": "If you leave items in your cart for a couple of days we'll hold them and may send a one-time offer code. The code applies "
          "to what's in the cart, expires on the date shown, and can't be combined with other promotions.",
     "keywords": ["cart", "offer code", "promo code", "coupon", "comeback", "checkout", "basket"]},
    {"section": "Account", "audience": "all", "intent": "account",
     "q": "How do I update my account details?",
     "a": "In the app, open Profile to change your email, phone, delivery addresses and communication preferences. To change the "
          "name on the account or merge two accounts, customer care needs to verify you first.",
     "keywords": ["account", "account details", "change email", "update address", "phone number", "profile", "password"]},
    {"section": "Account", "audience": "all", "intent": "account",
     "q": "How does Larkfield Rewards work?",
     "a": "You earn 1 point per dollar. Members move up by orders in a rolling year: Silver at 3, Gold at 6, Platinum at 14. Gold adds "
          "a 45-day return window and early access to sales; Platinum adds 60-day returns and free assembly. 500 points is a $5 reward.",
     "keywords": ["rewards", "points", "loyalty", "gold", "platinum", "silver", "tier", "member"]},
    {"section": "Products", "audience": "all", "intent": "product",
     "q": "What warranty do your products have?",
     "a": "Larkfield furniture carries a 5-year warranty and Lumen chairs 12 years. Electronics have the maker's warranty - two "
          "years on Aero laptops and Vista monitors. Protection plans add accidental-damage cover for 2 or 3 years.",
     "keywords": ["warranty", "guarantee", "protection plan", "cover", "repair"]},
    {"section": "Products", "audience": "all", "intent": "product",
     "q": "How do I choose a standing desk?",
     "a": "Measure the wall first: the Arc comes in 48 and 60 inches. Both lift 220 lb with dual motors and remember four heights. "
          "Add an anti-fatigue mat if you'll stand for more than an hour at a time, and a monitor arm to keep the screen at eye level.",
     "keywords": ["standing desk", "desk", "arc", "which desk", "choose", "recommend"]},
    {"section": "Support", "audience": "all", "intent": "general",
     "q": "How do I reach a person?",
     "a": f"Say \"talk to a person\" in OneChat and we'll hand your conversation, with its context, to customer care - "
          f"{_CO['support_hours']} - or call {_CO['support_phone']}.",
     "keywords": ["human", "agent", "person", "representative", "call", "phone number", "speak to someone", "talk to"]},
    # ---- Lead Generation & Sales -----------------------------------------------------
    {"section": "Larkfield for Business", "audience": "all", "intent": "sales",
     "q": "What is Larkfield for Business?",
     "a": "Larkfield for Business fits out workspaces for teams of 5 to 5,000: desks, seating, displays and meeting rooms, delivered "
          "and assembled on a schedule. Three packages - Workspace Starter, Team and Enterprise - are priced per seat, with volume "
          "pricing from 16 seats and lease options from 76.",
     "keywords": ["business", "for business", "office", "workspace", "team", "bulk", "b2b", "company", "fit-out", "fit out"]},
    {"section": "Larkfield for Business", "audience": "all", "intent": "sales",
     "q": "How does a workspace consultation work?",
     "a": "A consultation is a free 45-minute session with a workspace specialist by video, phone or in store. Bring your headcount "
          "and a rough floor plan; you leave with a recommended package, a per-seat price and a delivery plan. There's no obligation.",
     "keywords": ["consultation", "consult", "appointment", "book a call", "specialist", "demo", "meeting", "talk to sales"]},
    {"section": "Larkfield for Business", "audience": "all", "intent": "sales",
     "q": "Do you offer volume pricing?",
     "a": "Yes. Workspace Starter is $890 a seat for up to 15 seats, Workspace Team $1,450 a seat for 16-75, and Workspace Enterprise "
          "$1,320 a seat from 76 seats with a dedicated project manager. Quotes are valid for 30 days.",
     "keywords": ["volume", "bulk", "quote", "per seat", "pricing", "discount", "wholesale", "lease"]},
    # ---- Internal Operations & HR (Team Handbook) ------------------------------------------
    {"section": "IT help desk", "audience": "employee", "intent": "it",
     "q": "How do I reset my password?",
     "a": "Ask OneChat to reset it: you'll approve a prompt in your authenticator app and choose a new password within 15 minutes. "
          "Passwords expire every 90 days and need 14 characters. If you haven't set up multi-factor sign-in yet, open an Account & "
          "access ticket and the Identity team will verify you.",
     "keywords": ["password", "reset", "locked out", "forgot", "expired", "sign in", "login", "log in"]},
    {"section": "IT help desk", "audience": "employee", "intent": "it",
     "q": "How do I set up the VPN?",
     "a": "Install Larkfield Connect from the Self Service app, sign in with SSO and approve the multi-factor prompt. Remote VPN "
          "access is a standard request that's granted straight away. If the client won't connect from home, restart it once and "
          "then open a VPN & network ticket - the Network team answers within 4 business hours.",
     "keywords": ["vpn", "remote access", "connect from home", "network", "wifi", "wi-fi"]},
    {"section": "IT help desk", "audience": "employee", "intent": "it",
     "q": "How do I get access to a system?",
     "a": "Standard systems - VPN and store point of sale - are granted as soon as you ask. Systems that hold customer, financial or "
          "production data (Sales Analytics, Finance ERP, CRM admin, the production database) are privileged: you give a business "
          "justification, your request is held for approval, and you need your security awareness training complete first.",
     "keywords": ["access", "permission", "analytics", "erp", "crm", "database", "request access", "system access"]},
    {"section": "IT help desk", "audience": "employee", "intent": "it",
     "q": "My laptop is broken - what do I do?",
     "a": "Open a Laptop & hardware ticket with what's wrong; the Deskside team responds within 8 business hours and can ship a "
          "loaner overnight. Store teams can swap a device at any Larkfield store with a Deskside bench. Standard refresh is every "
          "three years.",
     "keywords": ["laptop", "hardware", "broken", "screen", "battery", "keyboard", "monitor", "loaner", "new laptop", "device"]},
    {"section": "IT help desk", "audience": "employee", "intent": "it",
     "q": "How do I install software?",
     "a": "Approved apps install in one click from Self Service. Anything else needs a Software install ticket with the app name and "
          "why you need it; licensed tools also need your manager's cost-centre approval.",
     "keywords": ["software", "install", "application", "app", "license", "self service"]},
    {"section": "Benefits", "audience": "employee", "intent": "hr",
     "q": "When do I enroll in benefits?",
     "a": "New hires enroll within 30 days of their start date, and coverage starts the first of the following month. After that, "
          "changes wait for annual enrollment in November unless you have a qualifying life event such as marriage or a new child.",
     "keywords": ["enroll", "enrollment", "benefits", "open enrollment", "coverage start", "sign up for benefits"]},
    {"section": "Benefits", "audience": "employee", "intent": "hr",
     "q": "What medical plans are there?",
     "a": "Three: Core PPO ($48 per paycheck, $1,500 deductible, $25 office visits), HSA Advantage ($22 per paycheck, $3,200 "
          "deductible, with a $1,000 company HSA contribution) and Plus PPO ($92 per paycheck, $500 deductible, $15 office visits). "
          "Dental Base is $6 and Dental Plus $14 per paycheck; Vision Standard is $3.",
     "keywords": ["medical", "health insurance", "ppo", "hsa", "dental", "vision", "plan", "deductible", "insurance"]},
    {"section": "Benefits", "audience": "employee", "intent": "hr",
     "q": "Does Larkfield match 401(k) contributions?",
     "a": f"Yes - dollar for dollar up to {C.K401_MATCH_PCT}% of pay, from your first paycheck, vested immediately. New hires are "
          "enrolled at 3% unless they choose another rate.",
     "keywords": ["401k", "401(k)", "retirement", "match", "pension", "contribution"]},
    {"section": "Time off", "audience": "employee", "intent": "hr",
     "q": "How much paid time off do I get?",
     "a": f"You start with 3 days and accrue {C.PTO_ACCRUAL_PER_MONTH:g} days a month (18 a year), rising to 2 days a month after "
          "three years. Request time off in OneChat; it goes to your manager for approval. Up to 5 unused days carry over.",
     "keywords": ["pto", "time off", "vacation", "holiday", "leave", "days off", "accrue", "sick"]},
    {"section": "Time off", "audience": "employee", "intent": "hr",
     "q": "What is the parental leave policy?",
     "a": "16 weeks fully paid for birthing parents and 8 weeks for all other new parents, after 90 days of service, taken within a "
          "year of the birth or placement. Tell your People Partner at least 30 days ahead where you can.",
     "keywords": ["parental", "maternity", "paternity", "family leave", "baby", "adoption"]},
    {"section": "Pay", "audience": "employee", "intent": "hr",
     "q": "When do I get paid?",
     "a": "Every other Friday. Your first paycheck is a paper check unless direct deposit is set up before the payroll cut-off, the "
          "Monday of pay week. Pay stubs and tax forms are in the People Portal.",
     "keywords": ["paid", "payday", "paycheck", "pay stub", "payroll", "direct deposit", "salary", "w-2"]},
    {"section": "Onboarding", "audience": "employee", "intent": "onboarding",
     "q": "What paperwork do I need to finish as a new hire?",
     "a": "Eight items: Form I-9 (documents within three days), Form W-4 and direct deposit in your first week, the Team Handbook "
          "and Code of Conduct to sign by day 10, security awareness training and an emergency contact by day 14, and benefits "
          "enrollment within 30 days. OneChat lists what's left and you can sign most of them right here.",
     "keywords": ["onboarding", "paperwork", "new hire", "i-9", "i9", "w-4", "w4", "handbook", "first week", "forms", "orientation"]},
    {"section": "Onboarding", "audience": "employee", "intent": "onboarding",
     "q": "What documents do I need for the I-9?",
     "a": "Either one List A document (a US passport or permanent resident card) or one each from List B and List C (for example a "
          "driver's licence plus a Social Security card or birth certificate). Show the originals to your manager or a People "
          "Partner within three days of your start date.",
     "keywords": ["i-9", "i9", "documents", "passport", "eligibility", "identification"]},
    {"section": "Perks", "audience": "employee", "intent": "hr",
     "q": "What is the team member discount?",
     "a": "30% off Larkfield-brand products and 15% off everything else, from your first day, online and in store. It's for you and "
          "your household and can't be combined with promotions.",
     "keywords": ["employee discount", "team discount", "discount", "perk", "staff discount"]},
]
CUSTOMER_FAQ = [f for f in FAQ if f["audience"] == "all"]
EMPLOYEE_FAQ = [f for f in FAQ if f["audience"] == "employee"]


def faq_public(entries: list[dict]) -> list[dict]:
    return [{"q": f["q"], "a": f["a"], "keywords": f["keywords"], "section": f.get("section"), "intent": f.get("intent")} for f in entries]


def _faq_md(entries: list[dict]) -> list[str]:
    lines, section = [], None
    for f in entries:
        if f.get("section") != section:
            section = f.get("section")
            lines += ["", f"## {section}", ""]
        lines += [f"### {f['q']}", f["a"], ""]
    return lines


def help_center_markdown(export_date: str, entries: list[dict] | None = None) -> str:
    entries = [e for e in (entries or FAQ) if e.get("audience", "all") == "all"]
    lines = [f"# {_CO['name']} Help Center", f"Published {export_date}. Public information for customers and business prospects.", ""]
    lines += _faq_md(entries)
    lines += ["", "## Stores and hours", ""]
    for s in C.STORES:
        lines.append(f"- {s['name']} ({s['city']}): {s['hours']}.")
    lines += ["", "## Products", ""]
    for p in C.PRODUCTS:
        lines.append(f"- {p['name']} ({p['sku']}), {p['category']}: ${p['price']}. {p['blurb']} Good for {', '.join(p['tags'])}.")
    lines += ["", f"## {_CO['business_brand']} packages", ""]
    for b in C.BUNDLES:
        lines.append(f"- {b['name']} ({b['code']}): {b['seats'][0]}-{b['seats'][1]} seats at ${b['price_per_seat']:,} per seat. "
                     f"Includes {', '.join(b['includes'])}. {b['blurb']}")
    return "\n".join(lines)


def handbook_markdown(export_date: str, entries: list[dict] | None = None) -> str:
    entries = [e for e in (entries or FAQ) if e.get("audience") == "employee"]
    lines = [f"# {_CO['name']} Team Handbook", f"Published {export_date}. Internal - for {_CO['name']} team members only.", ""]
    lines += _faq_md(entries)
    lines += ["", "## IT help desk queues", ""]
    for c in C.IT_CATEGORIES:
        lines.append(f"- {c['name']} ({c['id']}): {c['queue']} team, first response within {c['sla_hours']} business hours.")
    lines += ["", "## Systems and access", ""]
    for s in C.SYSTEMS:
        lines.append(f"- {s['name']} ({s['id']}): " + ("given to everyone on day one." if s["default"] else
                                                      "privileged - needs a justification and approval." if s["approval"] else "standard request, granted straight away."))
    lines += ["", "## Benefit plans", ""]
    for kind, plans in C.BENEFIT_PLANS.items():
        for p in plans:
            lines.append(f"- {p['name']} ({p['id']}, {kind}): ${p['employee_cost_per_paycheck']} per paycheck. {p['blurb']}")
    lines += ["", "## New-hire onboarding checklist", ""]
    for t in C.ONBOARDING_TASKS:
        lines.append(f"- {t['title']} (due day {t['due_day']}): {t['detail']}")
    return "\n".join(lines)


def user_profile_markdown(p: dict) -> str:
    s = p.get("ml_scores", {})
    head = [f"# User profile {p['user_id']}: {p['first_name']} {p['last_name']} ({C.AUDIENCES[p['audience']]})",
            f"Source: OneChat nightly export {p.get('export_date')}, scores by {s.get('model_version')}"
            + (f"; segments: {', '.join(a['name'] for a in p['segments'])}" if p.get("segments") else "") + ".", ""]
    prefs = p.get("preferences", {})
    if p["audience"] == "customer":
        orders = "; ".join(
            f"order {o['order_id']} placed {o['placed_at']} - {', '.join(i['name'] for i in o['items'])} - ${o['total_usd']:,.2f}, "
            f"{o['status'].replace('_', ' ')}" + (f", arriving {o['eta']}" + (f" {o['delivery_window']}" if o.get("delivery_window") else "") + f" with {o['carrier']}"
                                                 if o["status"] in ("processing", "shipped", "out_for_delivery") else
                                                 f", delivered {o['delivered_at']}" if o.get("delivered_at") else "")
            for o in p.get("orders", [])) or "no recent orders"
        cart = p.get("cart")
        cart_txt = ("empty" if not cart else f"{', '.join(i['name'] for i in cart['items'])} (${cart['subtotal_usd']:,}), left "
                    f"{cart['abandoned_days']} days ago" + (f"; offer {cart['offer']['code']} for {cart['offer']['pct_off']}% off until {cart['offer']['expires']}" if cart.get("offer") else ""))
        body = [
            "## Account and loyalty",
            f"{p['first_name']} lives in {p['home_city']} and is a {p['loyalty']['program']} {p['loyalty']['tier']} member with "
            f"{p['loyalty']['points']:,} points, a member since {p['loyalty']['member_since']}. Return window: "
            f"{C.return_window_days(p['loyalty']['tier'])} days. Lifetime value ${p['history']['lifetime_value_usd']:,.0f} over "
            f"{p['history']['orders_count']} orders; {p['history']['returns_count']} past returns. Preferred store: "
            f"{(C.STORE_BY_ID.get(prefs.get('preferred_store')) or {}).get('name', 'none')}.",
            "", "## Orders", f"Recent orders: {orders}.",
            "", "## Cart", f"Cart: {cart_txt}.",
            "", "## Preferences", f"Interests: {', '.join(prefs.get('interests', []))}. Prefers {prefs.get('communication_channel')} messages.",
            "", "## Personalization signals",
            f"Segment: {s.get('segment')}. Next best action: {s.get('next_best_action')}. Cart recovery propensity "
            f"{s.get('cart_recovery_propensity')}, upsell propensity {s.get('upsell_propensity')}, churn risk {s.get('churn_risk')}, "
            f"price sensitivity {s.get('price_sensitivity')}. Recommended: {', '.join(C.PRODUCT_BY_SKU[x]['name'] for x in s.get('recommended_skus', []) if x in C.PRODUCT_BY_SKU)}.",
        ]
    elif p["audience"] == "lead":
        c, lead = p["company"], p["lead"]
        consult = p.get("consultation")
        body = [
            "## Company",
            f"{p['first_name']} is {lead.get('role', 'a contact')} at {c['name']}, a {c['industry']} company with {c['employees']} "
            f"employees in {c['city']}.",
            "", "## Lead",
            f"Source: {lead['source']}. Status: {lead['status']}. Lead score {lead['score']}. Seats needed: {lead.get('seats') or 'not captured'}. "
            f"Budget: {lead.get('budget_band') or 'not captured'}. Timeline: {lead.get('timeline') or 'not captured'}. Interested in: "
            f"{', '.join(lead.get('interest', []))}. Owner: {lead.get('owner') or 'unassigned'}.",
            "", "## Browsing",
            f"Viewed {', '.join(C.PRODUCT_BY_SKU[x]['name'] for x in p['browsing']['viewed_skus'] if x in C.PRODUCT_BY_SKU)}; "
            f"{p['browsing']['sessions_30d']} sessions in 30 days, last visit {p['browsing']['last_visit']}.",
            "", "## Consultation",
            (f"Booked {consult['date']} at {consult['time']} ({consult['channel']}) with {consult['rep']} on {consult['topic']}." if consult else "None booked."),
            "", "## Personalization signals",
            f"Segment: {s.get('segment')}. Next best action: {s.get('next_best_action')}. Fit {s.get('fit')}. Recommended package: "
            f"{C.BUNDLE_BY_CODE[s['recommended_bundle']]['name'] if s.get('recommended_bundle') in C.BUNDLE_BY_CODE else 'n/a'}.",
        ]
    else:
        e, it, hr = p["employment"], p["it"], p["hr"]
        pend = [t for t in p["onboarding"]["tasks"] if t["status"] != "complete"]
        b = hr["benefits"]
        body = [
            "## Employment",
            f"{p['first_name']} is a {e['title']} in {e['department']}, based in {e['location']}, reporting to {e['manager']}. "
            f"Started {e['start_date']} ({e['employment_type']}).",
            "", "## Onboarding",
            f"Status: {p['onboarding']['status']}. " + ("Still to do: " + "; ".join(f"{t['title']} (due {t['due_date']})" for t in pend) + "." if pend else "All tasks complete."),
            "", "## IT",
            f"Devices: {', '.join(d['model'] + ' (' + d['os'] + ', ' + d['asset_tag'] + ')' for d in it['devices'])}. Access: "
            f"{', '.join(C.SYSTEM_BY_ID[x]['name'] for x in it['systems_access'] if x in C.SYSTEM_BY_ID)}. Password expires in "
            f"{it['password_expires_in_days']} days; multi-factor sign-in {'set up' if it['mfa_enrolled'] else 'not set up'}. Open tickets: "
            + ("; ".join(f"{t['ticket_id']} {t['summary']} ({t['status']})" for t in it["open_tickets"]) or "none") + ".",
            "", "## Benefits and time off",
            (f"Enrolled: medical {b.get('medical')}, dental {b.get('dental') or 'waived'}, vision {b.get('vision') or 'waived'}; 401(k) {b.get('k401_pct')}%."
             if b["enrolled"] else f"Not enrolled yet; the new-hire window closes {b.get('enrollment_deadline')} ({days_until(b.get('enrollment_deadline'))} days).")
            + f" Paid time off balance {hr['pto']['balance_days']:g} days. Paid {hr['pay']['frequency']}; next pay date {hr['pay']['next_pay_date']}.",
            "", "## Personalization signals", f"Segment: {s.get('segment')}. Next best action: {s.get('next_best_action')}.",
        ]
    return "\n".join(head + body)
