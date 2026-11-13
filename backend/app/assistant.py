"""OneChat - the agent behind the app's Chat tab. One assistant for the whole
company: customer support, orders and returns, sales, and the internal IT
and HR help desk.

One turn:

1. **Classify** the question into an intent and its *area* (support,
   commerce, sales, workplace), and decide whether it is *personal* (needs
   this person's data) or a *shared* question anyone could ask ("what's
   your return policy?").
2. **Audience gate.** IT, HR and onboarding intents are for signed-in team
   members. A customer or prospect who asks one gets a polite refusal and
   nothing is retrieved - the Team Handbook is never in their context.
3. **Shared questions -> an AOM RAG Application.** One call to
   `/v1/agent/rag/<app>/query`: the customer app (scoped to today's Help
   Center) or, for a team member's IT/HR question, the workplace app (scoped
   to today's Team Handbook). AOM runs retrieval behind its Context Cache and
   generation behind its LLM Cache, and counts the query on its RAG
   Applications page.
4. **Personal questions -> Context Caching.** Look the context up in AOM's
   Context Cache (`/v1/context/get`, namespace `rag:<app>:user-context`),
   then in the Couchbase `ctx::<user>::<intent>` document. On a miss,
   assemble it: the person's current record from their system of record
   (CDP, CRM or HRIS - segments and scores), AOM Knowledge Base retrieval
   scoped to this person's profile document and to the right knowledge
   document, plus live facts from the governed MCP tools (orders, return
   options, cart, consultation slots, tickets, benefits, onboarding tasks).
   It is stored in AOM (`/v1/context/set`, with the real build time) and in
   Couchbase, keyed by the export date and the profile revision, so the next
   nightly export or anything the person does invalidates it. The Couchbase
   copy carries the person's channel, so Sync Gateway puts it on the phone
   too - which is what lets the app answer offline.
5. **Memory** - recall what this person told OneChat before (AOM agent
   memory), live every turn.
6. **LLM Caching** - complete through AOM `/v1/llm/complete` in the
   `rag:<app>:personal` namespace.
7. Suggest one-tap actions; the app turns a tap into an offline-first
   `requests` document.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from . import catalog as C
from . import config, knowledge, metrics, rag_app, sources, tool_gateway
from .aom_client import AOMError, aom, current_trace
from .docs import STATE, chat_id, ctx_id, days_until, money, nice_date, now_iso, profile_id, user_channel
from .rag_app import EMPLOYEE_INTENTS
from .store import store

log = logging.getLogger("onechat.assistant")

INTENTS = ["order", "return", "cart", "product", "sales", "account", "it", "hr", "onboarding", "service_recovery", "general"]
AREA = {"general": "support", "account": "support", "service_recovery": "support",
        "order": "commerce", "return": "commerce", "cart": "commerce",
        "product": "sales", "sales": "sales",
        "it": "workplace", "hr": "workplace", "onboarding": "workplace"}
# Which intents can be *personal* for each audience. Anything else is answered
# as a shared question from the knowledge document.
APPLICABLE = {
    "customer": {"order", "return", "cart", "product", "sales", "account", "service_recovery", "general"},
    "lead": {"product", "sales", "account", "general"},
    "employee": {"it", "hr", "onboarding", "product", "general"},
}
# Context-cache keys: personal context per intent, plus a shared context per
# intent for generic questions (no personal data in it).
CONTEXT_KEYS = INTENTS + [f"playbook_{i}" for i in INTENTS]

# Order matters: on a tie the earlier intent wins.
KEYWORDS = {
    "service_recovery": ["damaged", "defective", "never arrived", "missing", "disappointed", "upset", "terrible", "awful", "complain",
                         "unacceptable", "wrong item", "frustrated", "scratched", "faulty", "broke", "stopped working"],
    "return": ["return", "refund", "exchange", "send back", "send it back", "swap", "money back"],
    "order": ["order", "track", "tracking", "where is my", "where's my", "delivery", "deliver", "shipped", "shipping", "shipment",
              "arrive", "package", "reschedule", "assembly"],
    "cart": ["cart", "checkout", "check out", "basket", "promo code", "offer code", "coupon", "comeback"],
    "onboarding": ["onboarding", "paperwork", "i-9", "i9", "w-4", "w4", "direct deposit", "handbook", "new hire", "first week",
                   "checklist", "code of conduct", "security training", "orientation", "forms"],
    "it": ["password", "vpn", "laptop", "locked out", "ticket", "software", "install", "access to", "wifi", "wi-fi", "printer",
           "outlook", "mfa", "help desk", "helpdesk", "sso", "log in", "login", "sign in", "authenticator", "point of sale",
           "connect from home", "need approval", "system access", "systems do i"],
    "hr": ["benefits", "medical", "dental", "vision", "401k", "401(k)", "pto", "time off", "vacation", "day off", "days off",
           "payday", "paycheck", "get paid", "parental", "insurance", "hsa", "enroll", "team discount", "employee discount",
           "team member discount", "sick"],
    "product": ["recommend", "looking for", "suggest", "desk", "chair", "monitor", "headset", "webcam", "keyboard", "tablet",
                "compare", "best", "standing", "warranty", "lamp", "dock"],
    "sales": ["consultation", "consult", "quote", "office", "workspace", "seats", "bulk", "volume", "for business", "appointment",
              "book a call", "specialist", "team of", "fit-out", "fit out", "our team", "employees", "headcount", "per seat", "lease"],
    "account": ["account", "points", "rewards", "loyalty", "tier", "my email", "my address", "my details", "store credit", "member", "my contact"],
}
PERSONAL_RE = re.compile(r"\b(i|i'm|im|i've|me|my|mine|we|we're|our|us)\b", re.I)
# "How do I reset my password?" has a pronoun but asks how something works:
# everyone gets the same answer, so it stays on the shared (cacheable) path.
PROCEDURAL_RE = re.compile(r"^\s*(how (do|can|would|should) (i|we)\b|how (much|many|long|often)\b.*\bdo (i|we) get\b|what (do|should) (i|we) (need|do)\b"
                           r"|what \w+ do (i|we) need\b|where (do|can) (i|we)\b|when (do|can|should) (i|we)\b|why did (i|we)\b|do (i|we) need\b)", re.I)
PERSONAL_INTENTS = {"service_recovery"}

# Canonical retrieval query per intent: the cached context is per intent, so
# it is retrieved with a stable query rather than the wording of whichever
# question happened to miss the cache first.
INTENT_QUERY = {
    "order": "order status tracking delivery window carrier",
    "return": "return policy window exchange refund",
    "cart": "cart offer code checkout shipping",
    "product": "product recommendation interests warranty",
    "sales": "Larkfield for Business consultation workspace package per seat pricing",
    "account": "account details Larkfield Rewards tier points",
    "it": "IT help desk password VPN access ticket device",
    "hr": "benefits enrollment medical 401(k) paid time off pay",
    "onboarding": "new hire onboarding paperwork I-9 W-4 direct deposit handbook training",
    "service_recovery": "damaged order replacement goodwill store credit",
    "general": "store hours delivery times return policy pricing payment",
}
FACT_TOOL = {"order": "get_orders", "service_recovery": "get_orders", "return": "get_return_options", "cart": "get_cart",
             "product": "recommend_products", "sales": "get_consultation_slots", "account": "get_user_context",
             "it": "get_it_context", "hr": "get_benefits_summary", "onboarding": "get_onboarding_tasks"}

PERSONA = ("You are OneChat, the assistant for Larkfield - one chat for customers, business prospects and team members. "
           "Be warm, concise (under 120 words) and specific. Use only the facts in CONTEXT. Never invent prices, dates, "
           "availability, policies or ticket numbers. Never say an action is done - the person confirms actions with the "
           "buttons shown under your reply.")
RESTRICTED = ("That one's for the Larkfield team workspace - IT, benefits and onboarding answers are only available to "
              "signed-in team members. I can help you with orders, returns, products, store information or a business "
              "consultation.")


def classify(message: str, audience: str = "customer") -> tuple[str, bool]:
    m = message.lower()
    scores = {i: sum(1 for k in kws if k in m) for i, kws in KEYWORDS.items()}
    scores["service_recovery"] *= 2
    intent = max(scores, key=scores.get)
    if scores[intent] == 0:
        intent = "general"
    # A team member's broken laptop is a help-desk ticket, not an order complaint.
    if audience == "employee" and intent == "service_recovery":
        intent = "it"
    # A prospect talking about desks for the team is a sales conversation.
    if audience == "lead" and intent == "product" and scores["sales"] > 0:
        intent = "sales"
    pron = bool(PERSONAL_RE.search(message))
    personal = (pron and not PROCEDURAL_RE.match(m)) or intent in PERSONAL_INTENTS
    if intent == "general" and not personal:
        return "general", False
    # A product or policy question phrased generically ("what is your return
    # policy?") stays on the shared path even though its intent can be personal.
    if not pron and re.match(r"\s*(how|what|is|are|can|do|does|who|when|where|which)\b", m) and intent != "service_recovery":
        return intent, False
    return intent, personal


def _norm(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()


async def kb_doc_id(key: str) -> str | None:
    doc = await store.get("lookups", f"kbdoc::{key}")
    return doc.get("document_id") if doc else None


# --------------------------------------------------------------------------
# Context cache
# --------------------------------------------------------------------------
async def invalidate_context(user_id: str):
    for key in CONTEXT_KEYS:
        await store.remove("context_cache", ctx_id(user_id, key))


async def _kb(query: str, document_id: str | None, top_k=3) -> tuple[list[dict], str]:
    if not (aom.enabled and document_id):
        return [], "unavailable"
    try:
        res = await aom.knowledge_search(query, top_k=top_k, document_id=document_id)
        return [{"title": r.get("document_title"), "content": r.get("content"), "score": round(r.get("score") or 0, 3),
                 "document_id": r.get("document_id"), "source": "aom-kb"} for r in res.get("results", [])], "aom"
    except AOMError as exc:
        log.warning("KB search failed: %s", exc)
        return [], "error"


_PROFILE_SECTIONS = {
    "order": ["Orders", "Account"], "return": ["Orders", "Account"], "service_recovery": ["Orders", "Account"], "cart": ["Cart", "Personalization"],
    "product": ["Preferences", "Personalization", "Browsing"], "sales": ["Company", "Lead", "Consultation", "Preferences"],
    "account": ["Account", "Company", "Lead"], "it": ["IT", "Employment"], "hr": ["Benefits", "Employment"],
    "onboarding": ["Onboarding", "Employment"], "general": ["Account", "Company", "Employment"],
}


def _local_profile_chunks(profile: dict, intent: str) -> list[dict]:
    md = knowledge.user_profile_markdown(profile)
    want = _PROFILE_SECTIONS[intent]
    out = []
    for s in md.split("\n## "):
        if any(s.startswith(w) for w in want):
            out.append({"title": f"User profile {profile['user_id']}", "content": s[:1200], "score": None,
                        "document_id": None, "source": "local-export"})
    return out


def _local_playbook_chunks(query: str, audience: str, workplace: bool | None = None) -> list[dict]:
    """Keyword match over the bundled entries. Team Handbook entries are only
    ever considered for a team member."""
    q = query.lower()
    pool = knowledge.FAQ if audience == "employee" else knowledge.CUSTOMER_FAQ
    if workplace is True:
        pool = knowledge.EMPLOYEE_FAQ if audience == "employee" else []
    elif workplace is False:
        pool = knowledge.CUSTOMER_FAQ
    scored = []
    for f in pool:
        s = sum(1 + k.count(" ") for k in f["keywords"] if k in q)
        if s:
            scored.append((s, f))
    scored.sort(key=lambda x: -x[0])
    return [{"title": "Team Handbook" if f["audience"] == "employee" else "Help Center", "content": f"{f['q']} {f['a']}",
             "answer": f["a"], "score": None, "document_id": None, "source": "local-playbook"} for _, f in scored[:3]]


async def _facts(user_id: str, intent: str) -> dict:
    tool = FACT_TOOL.get(intent)
    if not tool:
        return {}
    res = await tool_gateway.invoke(tool, {"user_id": user_id})
    data = res.get("data", res)
    return {"tool": tool, "governed": res.get("governed", False), "trace_id": res.get("trace_id"), "data": data}


def _aom_context_key(user_id: str, cache_key: str, profile: dict, personal: bool) -> str:
    """Key in AOM's Context Cache. The export date and (for personal context)
    the profile revision are part of the key, so a new nightly export or any
    action makes the old entry unreachable at once. Shared context holds no
    personal data, so every user of that app shares one entry per intent."""
    if personal:
        return f"{user_id}:{cache_key}:{profile.get('export_date')}:r{profile.get('rev', 0)}"
    return f"{cache_key}:{profile.get('export_date')}"


def _local_valid(doc: dict | None, profile: dict, personal: bool) -> bool:
    return bool(doc and doc.get("export_date") == profile.get("export_date")
                and (not personal or doc.get("profile_rev") == profile.get("rev", 0)))


async def get_context(user_id: str, intent: str, profile: dict, personal: bool = True) -> dict:
    """Context Caching, with AOM's Context Cache in front of the assembly.

    1. AOM `/v1/context/get` in the app's `rag:<app>:user-context` namespace,
       so hit rate and latency avoided show on AOM's Context Cache and RAG
       Applications pages.
    2. On a miss (or with AOM unreachable), the Couchbase `context_cache`
       document, if it was built from today's export and the current profile.
    3. Otherwise assemble: the person's current system-of-record view
       (segments, scores), KB retrieval scoped to this person's profile
       document and the knowledge document, plus live facts from the governed
       MCP tools. The result goes to AOM (`/v1/context/set` with the real
       build time as `source_latency_ms`) and to Couchbase, where the
       person's channel puts it on the phone for offline answers.
    """
    audience = profile["audience"]
    app_key = rag_app.app_for(intent, audience)
    app = rag_app.APPS[app_key]
    namespace = config.context_namespace(app["app_id"])
    cache_key = intent if personal else f"playbook_{intent}"
    key = ctx_id(user_id, cache_key)
    aom_key = _aom_context_key(user_id, cache_key, profile, personal)
    t0 = time.perf_counter()
    aom_status = "off"
    if aom.enabled:
        try:
            res = await aom.context_get(aom_key, namespace)
            aom_status = (res.get("cache") or {}).get("status") or ("hit" if res.get("hit") else "miss")
            value = res.get("value")
            if res.get("hit") and isinstance(value, dict):
                # A shared entry may have been stored by another person's
                # turn: re-home it to this user before it syncs to their phone.
                doc = dict(value, user_id=user_id, channels=[user_channel(user_id)])
                local = await store.get("context_cache", key)
                if not _local_valid(local, profile, personal):
                    # Keep the phone's copy current for offline answers.
                    await store.upsert("context_cache", key, doc, ttl=config.CONTEXT_CACHE_TTL_SECONDS)
                doc["_cache"] = {"status": "hit", "source": "aom", "namespace": namespace,
                                 "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
                return doc
        except AOMError as exc:
            aom_status = "error"
            log.info("AOM context get failed: %s", exc)

    cached = await store.get("context_cache", key)
    if _local_valid(cached, profile, personal):
        cached["_cache"] = {"status": "hit", "source": "couchbase", "aom": aom_status,
                            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        if aom_status == "miss":
            await _aom_context_set(aom_key, cached, cached.get("build_ms"), namespace)
        return cached

    query = INTENT_QUERY[intent]
    user_doc = await kb_doc_id(user_id) if personal else None
    playbook_doc = await kb_doc_id(app["kb_key"])
    kb_profile, kb_mode = ([], "skipped")
    if personal and intent != "general":
        kb_profile, kb_mode = await _kb(query, user_doc)
        if not kb_profile:
            kb_profile = _local_profile_chunks(profile, intent)
    kb_playbook, pb_mode = await _kb(query, playbook_doc)
    if not kb_playbook:
        kb_playbook = _local_playbook_chunks(query + " " + intent, audience, workplace=app_key == "workplace")
    if kb_mode == "skipped":
        kb_mode = pb_mode
    facts = await _facts(user_id, intent) if personal and intent != "general" else {}
    # The person's *current* record from their system of record: segments and
    # scores as of now, not as of last night's export.
    sor = await sources.profile_view(user_id, profile) if personal else None
    build_ms = round((time.perf_counter() - t0) * 1000, 1)
    doc = {
        "type": "context_cache", "user_id": user_id, "audience": audience, "intent": intent, "area": AREA[intent],
        "personal": personal, "query": query, "rag_app": app["app_id"], "knowledge": app["kb_key"],
        "export_date": profile.get("export_date"), "profile_rev": profile.get("rev", 0),
        "built_at": now_iso(), "build_ms": build_ms, "kb_mode": kb_mode,
        "kb_profile": kb_profile, "kb_playbook": kb_playbook, "facts": facts, "sor": sor,
        "user_document_id": user_doc, "playbook_document_id": playbook_doc,
        "aom_key": aom_key, "channels": [user_channel(user_id)],
    }
    await store.upsert("context_cache", key, doc, ttl=config.CONTEXT_CACHE_TTL_SECONDS)
    await _aom_context_set(aom_key, doc, build_ms, namespace)
    doc = dict(doc)
    doc["_cache"] = {"status": "miss", "source": "built", "aom": aom_status, "latency_ms": build_ms}
    return doc


async def _aom_context_set(aom_key: str, doc: dict, build_ms, namespace: str) -> None:
    if not aom.enabled:
        return
    value = {k: v for k, v in doc.items() if not k.startswith("_")}
    if not value.get("personal"):
        if value.get("kb_profile") or value.get("facts") or value.get("sor"):
            return  # never share personal data across users
        for k in ("user_id", "channels", "user_document_id", "audience"):
            value.pop(k, None)
    try:
        await aom.context_set(aom_key, value, namespace, ttl_seconds=config.CONTEXT_CACHE_TTL_SECONDS,
                              source_latency_ms=int(build_ms or 0))
    except AOMError as exc:
        # 409 = context caching switched off in AOM's policy, 413 = over its size limit.
        log.info("AOM context set skipped: %s", exc)


# --------------------------------------------------------------------------
# Answer composition
# --------------------------------------------------------------------------
def _user_summary(p: dict) -> str:
    base = f"{p['first_name']} {p['last_name']} ({C.AUDIENCES[p['audience']]}), {p.get('home_city')}."
    if p["audience"] == "customer":
        return (f"{base} {p['loyalty']['program']} {p['loyalty']['tier']} with {p['loyalty']['points']:,} points; "
                f"{C.return_window_days(p['loyalty']['tier'])}-day return window. Interests: {', '.join(p['preferences']['interests'])}.")
    if p["audience"] == "lead":
        ld = p["lead"]
        return (f"{base} {ld.get('role')} at {p['company']['name']} ({p['company']['industry']}, {p['company']['employees']} employees). "
                f"Lead status {ld['status']}; seats {ld.get('seats') or 'unknown'}, budget {ld.get('budget_band') or 'unknown'}, "
                f"timeline {ld.get('timeline') or 'unknown'}.")
    e = p["employment"]
    return f"{base} {e['title']} in {e['department']}, reporting to {e['manager']}, started {e['start_date']}."


def _when(iso: str | None) -> str:
    d = days_until(iso)
    if d is None:
        return "soon"
    return "today" if d == 0 else "tomorrow" if d == 1 else f"on {nice_date(iso)}"


def _facts_text(facts: dict) -> str:
    d = facts.get("data") or {}
    t = facts.get("tool")
    if t == "get_orders":
        rows = [f"{o['order_id']} ({', '.join(i['name'] for i in o['items'])}): {o['status'].replace('_', ' ')}"
                + (f", arriving {o['eta']}" + (f" {o['delivery_window']}" if o.get('delivery_window') else "") + f" with {o['carrier']}"
                   if o["status"] in ("processing", "shipped", "out_for_delivery") else f", delivered {o.get('delivered_at')}" if o.get("delivered_at") else "")
                + (", delivery can be rescheduled" if o.get("can_reschedule") else "") for o in d.get("orders", [])[:5]]
        return "Orders: " + ("; ".join(rows) or "none")
    if t == "get_return_options":
        rows = [f"{i['name']} (order {i['order_id']}, ${i['price']}): " + (f"returnable, {i['days_left']} days left" if i["eligible"] else
                f"outside the {i['window_days']}-day window (delivered {i['days_since_delivery']} days ago)")
                + (f"; can exchange for {', '.join(x['name'] for x in i['exchange_options'][:2])}" if i["eligible"] and i["exchange_options"] else "")
                for i in d.get("items", [])[:6]]
        return f"Return options ({d.get('window_days')}-day window): " + ("; ".join(rows) or "nothing delivered recently")
    if t == "get_cart":
        c = d.get("cart")
        if not c:
            return "Cart: empty."
        return (f"Cart: {', '.join(i['name'] for i in c['items'])}, subtotal ${c['subtotal_usd']:,}"
                + (f"; offer {c['offer']['code']} {c['offer']['pct_off']}% off valid {d.get('offer_days_left')} more days, total ${d.get('total_usd'):,}" if d.get("offer_valid") else f"; total ${d.get('total_usd'):,}")
                + (f"; low stock: {', '.join(d['low_stock'])}" if d.get("low_stock") else ""))
    if t == "recommend_products":
        txt = "Recommended: " + "; ".join(f"{x['name']} ${x['price']} ({', '.join(x['matched_interests']) or 'popular'})" for x in d.get("products", [])[:4])
        if d.get("bundle"):
            b = d["bundle"]
            txt += f". Business package: {b['name']} ${b['price_per_seat']:,}/seat, about ${b['estimate_usd']:,} for {b['estimated_seats']} seats"
        return txt
    if t == "get_consultation_slots":
        if d.get("booked"):
            b = d["booked"]
            return f"Consultation booked: {b['date']} {b['time']} with {b['rep']} ({b['topic']})."
        opens = [f"{day['date']} {s['time']}" for day in d.get("days", []) for s in day["slots"] if s["open"] > 0][:5]
        return "Open consultation slots: " + ", ".join(opens)
    if t == "get_it_context":
        return (f"IT: password expires in {d.get('password_expires_in_days')} days; access to {', '.join(d.get('systems_access', []))}; "
                f"open tickets: " + ("; ".join(f"{x['ticket_id']} {x['summary']} ({x['status']}, {x.get('queue')})" for x in d.get("open_tickets", [])) or "none")
                + f"; can request: {', '.join(x['name'] + (' (needs approval)' if x['needs_approval'] else '') for x in d.get('requestable', []))}")
    if t == "get_benefits_summary":
        return ((f"Benefits: enrolled in {(d.get('medical') or {}).get('name')}" if d.get("enrolled") else
                 f"Benefits: not enrolled, window closes {d.get('enrollment_deadline')} ({d.get('days_to_enroll')} days)")
                + f"; PTO balance {d.get('pto', {}).get('balance_days')} days; next pay date {d.get('pay', {}).get('next_pay_date')}; "
                  f"401(k) {d.get('k401_pct')}% with a {d.get('k401_match_pct')}% match")
    if t == "get_onboarding_tasks":
        return "Onboarding still to do: " + ("; ".join(f"{x['title']} (due {x['due_date']})" for x in d.get("pending", [])) or "nothing - all complete")
    if t == "get_user_context" and d:
        return f"Account: {d}"[:600]
    return ""


def build_prompt(message: str, personal: bool, ctx: dict, profile: dict, memories: list[str]) -> str:
    parts = [PERSONA, "", "CONTEXT:"]
    if personal:
        parts.append("Person: " + _user_summary(profile))
        for c in ctx.get("kb_profile", [])[:3]:
            parts.append("Profile note: " + (c.get("content") or "")[:900])
        ft = _facts_text(ctx.get("facts") or {})
        if ft:
            parts.append(ft)
        if ctx.get("sor"):
            parts.append(f"{ctx['sor'].get('source_label', 'System of record')} segments: " + sources.segments_text(ctx["sor"]) + ".")
        for m in memories[:3]:
            parts.append("Earlier this person said: " + m[:300])
    for c in ctx.get("kb_playbook", [])[:3]:
        parts.append("Knowledge: " + (c.get("content") or "")[:900])
    parts += ["", f"QUESTION: {message.strip()}", "", "ANSWER:"]
    return "\n".join(parts)


def _mentioned(message: str, rows: list[dict], name_key="name") -> dict | None:
    """The order line or product a message is about: an order number, or a
    distinctive word from the item's name ("the keyboard", "my chair")."""
    m = message.lower()
    for r in rows:
        if str(r.get("order_id", "")).lower() in m and r.get("order_id"):
            return r
    for r in rows:
        words = [w for w in re.findall(r"[a-z]+", str(r.get(name_key, "")).lower()) if len(w) >= 4 and w not in ("with", "inch")]
        if any(w in m for w in words):
            return r
    return None


_GENERIC_WORDS = {"standing", "ergonomic", "with", "inch", "noise", "cancelling", "system", "pack", "tier", "floor", "task"}


def _named_products(message: str, profile: dict) -> list[dict]:
    """Products of the kind the message names ("a monitor", "a desk chair"),
    best match for this person's interests first. Deterministic and local, so
    the same question gives the same answer online and from the phone."""
    words = set(re.findall(r"[a-z]+", message.lower()))
    words |= {w[:-1] for w in words if w.endswith("s")}
    likes = set(profile.get("preferences", {}).get("interests", []))
    bought = {i["sku"] for o in profile.get("orders", []) for i in o["items"]}
    out = []
    for p in C.PRODUCTS:
        kinds = {w for w in re.findall(r"[a-z]+", p["name"].lower()) if len(w) >= 4 and w not in _GENERIC_WORDS}
        kinds.add(p["category"].lower().rstrip("s"))
        hit = len(kinds & words)
        if hit and p["sku"] not in bought:
            out.append((hit, len(likes & set(p["tags"])), -p["price"], p))
    out.sort(key=lambda x: x[:3], reverse=True)
    return [x[3] for x in out]


def _match_system(m: str, requestable: list[dict]) -> dict | None:
    """The system an access request names: most name words matched wins
    ("sales analytics workspace" is Sales Analytics, not point of *sale*)."""
    words = set(re.findall(r"[a-z0-9-]+", m))
    best, score = None, 0
    for s in requestable:
        n = sum(1 for w in re.findall(r"[a-z]+", s["name"].lower()) if len(w) > 3 and w in words) + (2 if s["id"] in words else 0)
        if n > score:
            best, score = s, n
    return best


def _order_lines(d: dict) -> list[dict]:
    return [{"order_id": o["order_id"], "name": i["name"], "sku": i["sku"], "price": i["price"], "order": o}
            for o in d.get("orders", []) for i in o["items"]]


def goodwill_amount(order: dict | None) -> int:
    """What the assistant proposes; a care supervisor approves or declines it."""
    base = (order or {}).get("total_usd") or 100
    return int(max(20, min(C.GOODWILL_CREDIT_MAX, round(base * 0.25 / 5) * 5)))


def compose_fallback(intent: str, personal: bool, message: str, ctx: dict, profile: dict) -> str:
    """Deterministic answer from the same context - used when AOM has no LLM
    provider key (it returns a labelled stub) or AOM is not configured."""
    d = (ctx.get("facts") or {}).get("data") or {}
    first = profile["first_name"]
    audience = profile["audience"]
    m = message.lower()
    if not personal or intent == "general":
        # Answer the question actually asked from the bundled entries when it
        # matches; otherwise the best retrieved chunk.
        workplace = True if ctx.get("knowledge") == "handbook" else None
        pb = _local_playbook_chunks(message, audience, workplace) or ctx.get("kb_playbook")
        if pb:
            return pb[0].get("answer") or pb[0]["content"]
        return ("I can help with IT, benefits, time off and onboarding - or anything a customer would ask." if audience == "employee"
                else "I can help with orders, returns, products, store information and business consultations.")
    if intent == "order":
        orders = d.get("orders", [])
        if not orders:
            return f"I don't see any orders on your account yet, {first}."
        line = _mentioned(message, _order_lines(d))
        o = line["order"] if line else next((o for o in orders if o["status"] in ("processing", "shipped", "out_for_delivery")), orders[0])
        names = " and ".join(i["name"] for i in o["items"][:2])
        if o["status"] in ("processing", "shipped", "out_for_delivery"):
            return (f"Your {names} (order {o['order_id']}) is {o['status'].replace('_', ' ')} with {o['carrier']} and arrives "
                    f"{_when(o['eta'])}" + (f", between {o['delivery_window']}" if o.get("delivery_window") else "")
                    + (f". Tracking {o['tracking_number']}" if o.get("tracking_number") else "")
                    + (". If that day doesn't work, you can move it." if o.get("can_reschedule") else "."))
        return f"Order {o['order_id']} ({names}) was {o['status']}" + (f" on {nice_date(o['delivered_at'])}." if o.get("delivered_at") else ".")
    if intent == "return":
        items = d.get("items", [])
        if not items:
            return f"Nothing delivered recently is open for return, {first}. Your window is {d.get('window_days', 30)} days from delivery."
        it = _mentioned(message, items)
        if it and not it["eligible"]:
            return (f"Your {it['name']} was delivered {it['days_since_delivery']} days ago, so it's outside your {it['window_days']}-day "
                    f"window, {first}. If something's wrong with it, I can ask a care supervisor to approve a store credit.")
        if it:
            ex = [x for x in it["exchange_options"] if x["in_stock"] > 0][:2]
            return (f"Yes - your {it['name']} can go back for a full ${it['price']} refund; you have {it['days_left']} days left. "
                    + (f"Or exchange it for {' or '.join(x['name'] for x in ex)}. " if ex else "") + "Returns are free: drop it at any store or UPS.")
        ok = [i for i in items if i["eligible"]]
        return (f"As a {d.get('tier')} member you have {d.get('window_days')} days, {first}. "
                + ("You can return or exchange: " + "; ".join(f"{i['name']} ({i['days_left']} days left)" for i in ok[:3]) + "." if ok
                   else "Nothing is inside the window right now."))
    if intent == "service_recovery":
        lines = _order_lines(d)
        line = _mentioned(message, lines) or (lines[0] if lines else None)
        amt = goodwill_amount(line["order"] if line else None)
        return (f"I'm sorry, {first} - that's not the experience we want for you"
                + (f" with your {line['name']}" if line else "") + f". I can ask a care supervisor to approve a {money(amt)} store "
                "credit right now; you'll see their decision here"
                + (", and you can still return or exchange it." if line and line["sku"] in line["order"].get("returnable_items", []) else "."))
    if intent == "cart":
        c = d.get("cart")
        if not c:
            return f"Your cart is empty, {first}. Want a recommendation?"
        names = " and ".join(i["name"] for i in c["items"][:2])
        return (f"You left the {names} in your cart, {first} ({money(c['subtotal_usd'])}). "
                + (f"Code {c['offer']['code']} takes {c['offer']['pct_off']}% off for {d['offer_days_left']} more day{'s' if d['offer_days_left'] != 1 else ''}: "
                   f"{money(d['total_usd'])} with {'free' if not d['shipping_usd'] else money(d['shipping_usd'])} shipping. " if d.get("offer_valid")
                   else f"Your total is {money(d['total_usd'])}. ")
                + (f"Only a few {d['low_stock'][0]} are left." if d.get("low_stock") else ""))
    if intent == "product":
        b = d.get("bundle")
        named = _named_products(message, profile)
        if named:
            top = named[0]
            txt = (f"{top['name']} (${top['price']}) is my pick, {first}: {top['blurb']}"
                   + (f" Also worth a look: {'; '.join(x['name'] + ' ($' + str(x['price']) + ')' for x in named[1:3])}." if named[1:] else ""))
        else:
            prods = d.get("products", [])[:3]
            if not prods and not b:
                return "Tell me what you're setting up - a desk, seating, a display - and I'll narrow it down."
            txt = (f"Based on what you like, {first}: " + "; ".join(f"{x['name']} (${x['price']})" for x in prods) + "." if prods else "")
        if b:
            txt += f" For the team, {b['name']} runs ${b['price_per_seat']:,} a seat - about {money(b['estimate_usd'])} for {b['estimated_seats']} seats."
        return txt.strip()
    if intent == "sales":
        if d.get("booked"):
            b = d["booked"]
            return f"You're booked with {b['rep']} on {nice_date(b['date'])} at {b['time']} ({b['channel']}) to talk about {b['topic'].lower()}, {first}."
        opens = [(day["date"], s["time"]) for day in d.get("days", []) for s in day["slots"] if s["open"] > 0][:3]
        if audience == "lead":
            c, ld = profile["company"], profile["lead"]
            seats = ld.get("seats") or c["employees"]
            b = C.bundle_for_seats(seats)
            return (f"For a team like {c['name']} (about {seats} seats), {b['name']} is the usual fit at ${b['price_per_seat']:,} a seat, "
                    f"delivered and assembled. " + ("" if ld.get("budget_band") else "Share your headcount, budget and timeline and I'll size a quote. ")
                    + (f"A free 45-minute consultation is open {nice_date(opens[0][0])} at {opens[0][1]}." if opens else ""))
        return ("A free 45-minute consultation with a workspace specialist covers layout, ergonomics and pricing"
                + (f" - the next opening is {nice_date(opens[0][0])} at {opens[0][1]}." if opens else "."))
    if intent == "account":
        if audience == "customer":
            lo = profile["loyalty"]
            credit = d.get("store_credit_usd") or 0
            return (f"You're a {lo['tier']} {lo['program']} member with {lo['points']:,} points - {money(lo['points'] // 500 * 5)} in "
                    f"rewards - and a {C.return_window_days(lo['tier'])}-day return window, {first}."
                    + (f" You also have {money(credit)} in store credit." if credit else " You have no store credit right now." if "credit" in m else ""))
        ld = profile["lead"]
        return (f"You're registered as {ld.get('role')} at {profile['company']['name']}, {first}. "
                + (f"{ld['owner']} is your {C.COMPANY['business_brand']} contact." if ld.get("owner") else "No specialist is assigned yet - a consultation gets you one."))
    if intent == "it":
        tickets = d.get("open_tickets", [])
        if "password" in m or "locked" in m or "sign in" in m or "log in" in m or "login" in m:
            return (f"Your password expires in {d.get('password_expires_in_days')} days, {first}. I can send a reset to your authenticator "
                    "app now - you'll have 15 minutes to choose a new one." if d.get("mfa_enrolled") else
                    f"You haven't set up multi-factor sign-in yet, {first}, so the Identity team has to verify you - I'll open a ticket.")
        if "vpn" in m:
            t = next((x for x in tickets if x["category"] == "vpn"), None)
            has = "Remote VPN" in d.get("systems_access", [])
            return ((f"{t['ticket_id']} is already open with the {t.get('queue', 'Network')} team for that ({t['status'].replace('_', ' ')} since {nice_date(t['opened_at'])}). " if t else "")
                    + ("You have VPN access; install Larkfield Connect from Self Service and sign in with SSO." if has else
                       "You don't have Remote VPN access yet - it's a standard request, so I can grant it right now."))
        if "access" in m:
            sysm = _match_system(m, d.get("requestable", []))
            if sysm:
                return (f"{sysm['name']} is a privileged system, {first}: I'll send your request with a justification and it's held for "
                        "approval before access is granted." if sysm["needs_approval"] else f"{sysm['name']} is a standard request - I can grant it now.")
        if "ticket" in m or "update" in m:
            return ("Your open tickets: " + "; ".join(f"{t['ticket_id']} - {t['summary']} ({t['status'].replace('_', ' ')}, {t.get('queue')} team)" for t in tickets) + "."
                    if tickets else f"You have no open tickets, {first}.")
        return (f"I can open a ticket with the right team for that, {first}. They'll have your "
                f"{(d.get('devices') or [{}])[0].get('model', 'device')} details already.")
    if intent == "hr":
        pto = d.get("pto", {})
        if any(k in m for k in ("time off", "pto", "vacation", "day off", "days off", "sick")):
            return (f"You have {pto.get('balance_days', 0):g} days of paid time off, {first}, and accrue {pto.get('accrual_per_month', 1.5):g} a month. "
                    f"Pick your dates and I'll send the request to {profile['employment']['manager']}.")
        if any(k in m for k in ("paid", "payday", "paycheck")):
            return f"Your next pay date is {nice_date(d.get('pay', {}).get('next_pay_date'))}, {first} - we pay every other Friday."
        if d.get("enrolled"):
            med = d.get("medical") or {}
            return (f"You're enrolled in {med.get('name')} (${med.get('cost_per_paycheck')} per paycheck), {first}, with "
                    f"{d.get('k401_pct')}% going to your 401(k); we match up to {d.get('k401_match_pct')}%.")
        return (f"You haven't enrolled yet, {first} - your new-hire window closes on {nice_date(d.get('enrollment_deadline'))} "
                f"({d.get('days_to_enroll')} days). Core PPO is $48 a paycheck, HSA Advantage $22 with a $1,000 company contribution, "
                "Plus PPO $92. Compare them and enroll below.")
    if intent == "onboarding":
        pend = d.get("pending", [])
        if not pend:
            return f"Your onboarding is complete, {first} - nothing left to sign."
        nxt = pend[0]
        return (f"You have {len(pend)} onboarding task{'s' if len(pend) > 1 else ''} left, {first}. Next is {nxt['title']}, due "
                f"{_when(nxt['due_date'])}. Then: " + ", ".join(t["title"] for t in pend[1:4]) + ". You can sign most of them right here.")
    return "Here's what I found."


def suggest_actions(intent: str, ctx: dict, profile: dict, message: str) -> list[dict]:
    d = (ctx.get("facts") or {}).get("data") or {}
    m = message.lower()
    audience = profile["audience"]
    acts: list[dict] = []
    if intent == "order":
        line = _mentioned(message, _order_lines(d))
        orders = d.get("orders", [])
        o = line["order"] if line else next((o for o in orders if o["status"] in ("processing", "shipped", "out_for_delivery")), None)
        if o:
            acts.append({"label": f"Track {o['order_id']}", "screen": "order", "args": {"order_id": o["order_id"]}})
            if o.get("can_reschedule"):
                acts.append({"label": "Move the delivery day", "screen": "order", "args": {"order_id": o["order_id"], "reschedule": "1"}})
    elif intent == "return":
        items = d.get("items", [])
        it = _mentioned(message, items)
        if it and it["eligible"]:
            acts.append({"label": f"Return {it['name']} · ${it['price']} back", "screen": "return", "args": {"order_id": it["order_id"], "sku": it["sku"]}})
            ex = next((x for x in it["exchange_options"] if x["in_stock"] > 0), None)
            if ex:
                acts.append({"label": f"Exchange for {ex['name']}", "screen": "return",
                             "args": {"order_id": it["order_id"], "sku": it["sku"], "resolution": "exchange", "exchange_sku": ex["sku"]}})
        elif it:
            amt = goodwill_amount({"total_usd": it["price"]})
            acts.append({"label": f"Request {money(amt)} store credit", "tool": "issue_goodwill_credit",
                         "args": {"amount_usd": amt, "order_id": it["order_id"],
                                  "reason": f"Outside return window; customer said: {message.strip()[:160]}"}})
        elif any(i["eligible"] for i in items):
            acts.append({"label": "Start a return or exchange", "screen": "return"})
    elif intent == "service_recovery":
        lines = _order_lines(d)
        line = _mentioned(message, lines) or (lines[0] if lines else None)
        amt = goodwill_amount(line["order"] if line else None)
        acts.append({"label": f"Request {money(amt)} store credit", "tool": "issue_goodwill_credit",
                     "args": {"amount_usd": amt, "order_id": line["order_id"] if line else "",
                              "reason": f"Reported in OneChat: {message.strip()[:200]}"}})
        if line and line["sku"] in line["order"].get("returnable_items", []):
            acts.append({"label": f"Return or exchange {line['name']}", "screen": "return", "args": {"order_id": line["order_id"], "sku": line["sku"]}})
    elif intent == "cart":
        if d.get("cart"):
            acts.append({"label": f"Check out · {money(d['total_usd'])}", "tool": "checkout_cart", "args": {"apply_offer": True}})
    elif intent in ("sales", "product") and audience in ("lead", "customer"):
        if intent == "sales" or audience == "lead":
            slots = d.get("days")
            if audience == "lead" and not profile["lead"].get("budget_band"):
                acts.append({"label": "Share details for a quote", "screen": "consult", "args": {"step": "details"}})
            if not (d.get("booked") or profile.get("consultation")):
                nxt = next(((day["date"], s["time"]) for day in (slots or []) for s in day["slots"] if s["open"] > 0), None)
                if nxt:
                    acts.append({"label": f"Book {nice_date(nxt[0])} at {nxt[1]}", "tool": "book_consultation",
                                 "args": {"date": nxt[0], "time": nxt[1], "channel": "video"}})
                acts.append({"label": "See all consultation times", "screen": "consult"})
    elif intent == "it":
        if any(k in m for k in ("password", "locked", "sign in", "log in", "login")):
            if d.get("mfa_enrolled"):
                acts.append({"label": "Reset my password", "tool": "reset_password", "args": {"system": "sso"}})
            else:
                acts.append({"label": "Open an access ticket", "screen": "ticket", "args": {"category": "access", "summary": message.strip()[:160]}})
        elif "vpn" in m and "Remote VPN" not in d.get("systems_access", []):
            acts.append({"label": "Request VPN access", "tool": "request_system_access",
                         "args": {"system": "vpn", "justification": f"Remote work: {message.strip()[:120]}"}})
        elif "access" in m:
            sysm = _match_system(m, d.get("requestable", []))
            if sysm:
                acts.append({"label": f"Request {sysm['name']}", "tool": "request_privileged_access" if sysm["needs_approval"] else "request_system_access",
                             "args": {"system": sysm["id"], "justification": message.strip()[:200]}})
        if not acts and not ("ticket" in m and "update" in m):
            cat = ("vpn" if "vpn" in m or "network" in m or "wifi" in m or "wi-fi" in m else "hardware" if any(k in m for k in ("laptop", "screen", "battery", "keyboard", "monitor", "printer")) else
                   "software" if "install" in m or "software" in m else "email" if "outlook" in m or "email" in m or "calendar" in m else
                   "pos" if "point of sale" in m or "register" in m else "access")
            acts.append({"label": "Open a help desk ticket", "screen": "ticket", "args": {"category": cat, "summary": message.strip()[:160]}})
    elif intent == "hr":
        if any(k in m for k in ("time off", "pto", "vacation", "day off", "days off", "sick")):
            acts.append({"label": "Request time off", "screen": "timeoff"})
        elif not d.get("enrolled") and not any(k in m for k in ("paid", "payday", "paycheck")):
            acts.append({"label": "Compare plans & enroll", "screen": "benefits"})
    elif intent == "onboarding":
        if d.get("pending"):
            acts.append({"label": "Open my checklist", "screen": "onboarding"})
            nxt = d["pending"][0]
            if nxt["kind"] != "sign" and nxt["task_id"] != "benefits":
                acts.append({"label": f"Mark {nxt['title']} done", "tool": "complete_onboarding_task", "args": {"task_id": nxt["task_id"]}})
    return acts


# Only durable things a person says about themselves become memories ("I'm
# left-handed", "our office is all standing desks"). Plain questions don't,
# which also keeps repeat questions' prompts stable for the LLM cache.
STATEMENT_RE = re.compile(r"\b(i|we)('m|'re| am| are| love| like| prefer| hate| don't| do not| want| need| always| never| work| have)\b"
                          r"|\bmy (wife|husband|partner|kids?|son|daughter|team|office|manager|back|desk)\b|\ballerg", re.I)


async def _remember(user_id: str, message: str, reply: str, intent: str, session_id: str):
    if not aom.enabled or not STATEMENT_RE.search(message) or message.strip().endswith("?"):
        return
    try:
        await aom.memory_add(user_id, f"User said ({intent}): {message.strip()[:500]}", session_id=session_id,
                             metadata={"intent": intent, "app": "onechat-mobile"})
    except AOMError as exc:
        log.info("memory add skipped: %s", exc)


async def _recall(user_id: str, message: str) -> list[str]:
    if not aom.enabled:
        return []
    try:
        res = await aom.memory_search(user_id, message, top_k=3)
        return [e.get("content", "") for e in res.get("entries", []) if e.get("content")]
    except AOMError:
        return []


async def _ask_rag_app(message: str, intent: str, profile: dict) -> dict | None:
    """Shared questions go to one of OneChat's AOM RAG Applications: one call
    that runs AOM's Context Cache (retrieval), the KB search scoped to today's
    Help Center or Team Handbook, and the LLM Cache, and is counted on the RAG
    Applications page."""
    key = rag_app.app_for(intent, profile["audience"])
    app = rag_app.APPS[key]
    if not rag_app.usable(key):
        return None
    l0 = time.perf_counter()
    try:
        res = await aom.rag_query(app["app_id"], message)
    except AOMError as exc:
        rag_app.query_failed(key, exc)
        log.info("RAG app query failed, answering on the assistant's own path: %s", exc)
        return None
    ms = round((time.perf_counter() - l0) * 1000, 1)
    retrieval = res.get("retrieval") or {}
    llm_res = res.get("llm") or {}
    cache = llm_res.get("cache") or {}
    srcs = res.get("sources") or []
    chunks = [{"title": c.get("document_title"), "content": c.get("preview"), "source": "aom-rag"} for c in srcs]
    reply = (res.get("answer") or "").strip()
    llm = {"status": cache.get("status", "skipped" if not res.get("llm") else "miss"), "similarity": cache.get("similarity"),
           "namespace": f"rag:{app['app_id']}", "provider": llm_res.get("provider"), "model": llm_res.get("model"),
           "latency_ms": ms, "stub": bool(llm_res.get("stub")), "tokens_saved": llm_res.get("tokens_saved") or 0,
           "cost_saved_usd": llm_res.get("cost_saved_usd") or 0, "rag_app": app["app_id"]}
    if not res.get("llm") or llm["stub"] or not reply:
        # No LLM provider key in AOM (stub) or nothing retrieved: answer from
        # the same knowledge deterministically.
        reply = compose_fallback(intent, False, message, {"kb_playbook": chunks, "knowledge": app["kb_key"]}, profile)
        llm["composed_locally"] = True
    return {
        "reply": reply, "llm": llm,
        "sources": [{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": "aom-rag"} for c in chunks[:3]],
        "context": {"status": retrieval.get("cache", "miss"), "latency_ms": retrieval.get("latency_ms", 0),
                    "source": "aom-rag", "rag_app": app["app_id"], "knowledge": app["kb_key"], "chunks": retrieval.get("chunks"),
                    "export_date": profile.get("export_date"), "kb_mode": "aom"},
        "trace_id": (res.get("trace") or {}).get("trace_id"),
    }


async def ask(user_id: str, message: str, session_id: str | None = None) -> dict:
    session_id = session_id or f"app-{user_id}"
    trace_id = uuid.uuid4().hex
    token = current_trace.set({"trace_id": trace_id, "session_id": session_id})
    t0 = time.perf_counter()
    try:
        profile = await store.get("profiles", profile_id(user_id))
        if not profile:
            raise ValueError("unknown user")
        audience = profile["audience"]
        intent, personal = classify(message, audience)
        base = {"intent": intent, "area": AREA[intent], "audience": audience, "export_date": STATE.get("export_date")}
        if intent in EMPLOYEE_INTENTS and audience != "employee":
            # Nothing is retrieved or generated: the handbook never enters a
            # customer's or prospect's context.
            result = {**base, "reply": RESTRICTED, "personal": False, "restricted": True, "actions": [], "sources": [],
                      "context": {"status": None, "latency_ms": 0, "source": "audience-gate"}, "memory_recalled": 0,
                      "llm": {"status": "skipped", "namespace": None}, "trace_id": None, "governed": aom.enabled,
                      "total_ms": round((time.perf_counter() - t0) * 1000, 1)}
            metrics.assistant(result)
            await _append_chat(user_id, message, result)
            return result
        if personal and intent not in APPLICABLE[audience]:
            personal = False
        if not personal:
            via_rag = await _ask_rag_app(message, intent, profile)
            if via_rag:
                result = {**base, "reply": via_rag["reply"], "personal": False, "actions": [],
                          "sources": via_rag["sources"], "context": via_rag["context"], "memory_recalled": 0,
                          "llm": via_rag["llm"], "trace_id": via_rag["trace_id"] or trace_id, "governed": True,
                          "total_ms": round((time.perf_counter() - t0) * 1000, 1)}
                metrics.assistant(result)
                await _append_chat(user_id, message, result)
                return result
        ctx = await get_context(user_id, intent, profile, personal)
        memories = await _recall(user_id, message) if personal else []
        prompt = build_prompt(message, personal, ctx, profile, memories)
        app_id = rag_app.APPS[rag_app.app_for(intent, audience)]["app_id"]
        namespace = config.llm_namespace(app_id, personal)
        llm = {"status": "local", "namespace": namespace, "provider": None, "model": None, "similarity": None,
               "latency_ms": None, "stub": False, "tokens_saved": 0}
        reply = None
        if aom.enabled:
            try:
                l0 = time.perf_counter()
                res = await aom.complete(prompt, namespace=namespace)
                cache = res.get("cache") or {}
                llm.update({"status": cache.get("status", "miss"), "similarity": cache.get("similarity"),
                            "provider": res.get("provider"), "model": res.get("model"),
                            "latency_ms": round((time.perf_counter() - l0) * 1000, 1), "stub": bool(res.get("stub")),
                            "tokens_saved": res.get("tokens_saved", 0), "cost_saved_usd": res.get("cost_saved_usd", 0)})
                if not res.get("stub") and (res.get("response") or "").strip():
                    reply = res["response"].strip()
            except AOMError as exc:
                llm["status"] = "error"
                llm["error"] = str(exc)[:200]
        if not reply:
            reply = compose_fallback(intent, personal, message, ctx, profile)
            llm["composed_locally"] = True
        actions = suggest_actions(intent, ctx, profile, message) if personal else []
        sources_out = ([{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": c.get("source")}
                        for c in (ctx.get("kb_profile", []) if personal else [])[:2]]
                       + [{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": c.get("source")}
                          for c in ctx.get("kb_playbook", [])[:2]])
        sor = ctx.get("sor")
        result = {
            **base, "reply": reply, "personal": personal, "actions": actions, "sources": sources_out,
            "context": {"status": ctx["_cache"]["status"], "latency_ms": ctx["_cache"]["latency_ms"],
                        "source": ctx["_cache"].get("source"), "rag_app": app_id, "knowledge": ctx.get("knowledge"),
                        "built_at": ctx.get("built_at"), "build_ms": ctx.get("build_ms"), "kb_mode": ctx.get("kb_mode"),
                        "export_date": ctx.get("export_date"),
                        "sor": ({"system": sor.get("source"), "label": sor.get("source_label"), "mode": sor.get("mode"),
                                 "latency_ms": sor.get("latency_ms"), "segments": [s["name"] for s in sor.get("segments", [])]}
                                if sor else None)},
            "memory_recalled": len(memories), "llm": llm, "trace_id": trace_id if aom.enabled else None,
            "governed": aom.enabled, "total_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        metrics.assistant(result)
        await _append_chat(user_id, message, result)
        await _remember(user_id, message, reply, intent, session_id)
        return result
    finally:
        current_trace.reset(token)


async def _append_chat(user_id: str, message: str, result: dict):
    doc = await store.get("chat", chat_id(user_id)) or {
        "type": "chat", "user_id": user_id, "messages": [], "answers": {}, "channels": [user_channel(user_id)]}
    now = now_iso()
    doc["messages"] = (doc["messages"] + [
        {"id": uuid.uuid4().hex[:12], "role": "user", "text": message, "at": now},
        {"id": uuid.uuid4().hex[:12], "role": "assistant", "text": result["reply"], "at": now,
         "intent": result["intent"], "area": result["area"], "actions": result["actions"], "context": result["context"],
         "llm": result["llm"], "sources": result["sources"], "restricted": result.get("restricted", False)},
    ])[-40:]
    # Answer cache the phone can reuse offline for the same (normalized) question.
    if not result.get("restricted"):
        doc["answers"][_norm(message)[:120]] = {"reply": result["reply"], "intent": result["intent"], "area": result["area"], "at": now}
    if len(doc["answers"]) > 60:
        doc["answers"] = dict(list(doc["answers"].items())[-60:])
    doc["updated_at"] = now
    await store.upsert("chat", chat_id(user_id), doc)
