"""Company-wide chatbot workload - a demo of AOM's LLM Cache and Context Cache
under a realistic OneChat load.

`POST /api/demo/workload` (or scripts/run_chatbot_workload.py) plays a crowd
of people from every part of the company against the assistant, exactly the
way the mobile app does: customers from every region, business prospects of
both sizes and team members from every department each get a session, ask
the things that kind of person asks, and every turn runs the real path - an
AOM RAG Application for shared questions (Help Center or Team Handbook), AOM
Context Cache + Knowledge Base + governed MCP tools for personal ones, AOM
Agent Memory for what people say about themselves, and AOM
`/v1/llm/complete` in the `rag:onechat-*` namespaces for generation. Nothing
is stubbed here; the point is to make AOM's LLM Cache, Context Cache, RAG
Applications and Traces pages fill up with a workload that looks like
production.

How the traffic is shaped (what makes the caches hit the way they would in
production):

* **Shared questions** (store hours, delivery, returns policy, password
  resets, benefits enrollment, ...) are drawn Zipf-style from USE_CASES, so a
  few questions dominate - as in a real support queue. Most people use the
  canonical wording (exact hits once the first person has paid for the
  answer), a minority reword it (semantic hits), and the long tail misses.
* **Personal questions** build a per-person, per-intent context once
  (`Context cache: built`) and the follow-up in the same intent reuses it
  (`hit`). Asking the very same thing again in a session is an exact LLM hit;
  a reworded follow-up shares the context but needs a (semantically cached)
  completion.
* **Statements** ("I'm left-handed", "our office is open plan") go to Agent
  Memory and are recalled on that person's later turns.
* A few customers and prospects ask an **IT or HR question**; the audience
  gate refuses those without retrieving anything.

The run is in-process (it calls `assistant.ask` directly), so it needs no
app sessions, and it reports per group, per use case and per cache outcome.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random
import time
from zoneinfo import ZoneInfo

from . import assistant, config, rag_app
from . import catalog as C
from .aom_client import aom
from .docs import STATE
from .store import store

log = logging.getLogger("onechat.workload")

CUS, LEAD, EMP = ["customer"], ["lead"], ["employee"]
SHOPPERS = ["customer", "lead"]
EVERYONE = ["customer", "lead", "employee"]
# --------------------------------------------------------------------------
# What people ask. `personal` questions take the person's own data path
# (context cache); the rest go to a RAG application over the Help Center or
# the Team Handbook. `audiences` says who asks it, `weight` is the share of
# the queue (Zipf-ish), `variants[0]` is the wording most people use; the
# others are paraphrases for semantic hits.
# --------------------------------------------------------------------------
USE_CASES: list[dict] = [
    # --- Customer Support & FAQs -----------------------------------------------------
    {"id": "store_hours", "area": "support", "intent": "general", "personal": False, "weight": 10, "audiences": EVERYONE,
     "variants": ["What are your store hours?", "What time do you close on Sunday?", "When are your stores open?"]},
    {"id": "delivery_times", "area": "support", "intent": "order", "personal": False, "weight": 10, "audiences": SHOPPERS,
     "variants": ["How long does delivery take?", "What are your delivery times?", "How fast do orders ship?"]},
    {"id": "shipping_cost", "area": "support", "intent": "order", "personal": False, "weight": 6, "audiences": SHOPPERS,
     "variants": ["How much is shipping?", "Is delivery free?", "What does assembly cost?"]},
    {"id": "return_policy", "area": "support", "intent": "return", "personal": False, "weight": 10, "audiences": EVERYONE,
     "variants": ["What is your return policy?", "How do returns work?", "How long is the return window?"]},
    {"id": "exchange_policy", "area": "support", "intent": "return", "personal": False, "weight": 4, "audiences": SHOPPERS,
     "variants": ["Can an item be exchanged for a different size?", "How do exchanges work?"]},
    {"id": "pricing", "area": "support", "intent": "general", "personal": False, "weight": 7, "audiences": SHOPPERS,
     "variants": ["Do you price match?", "What is your price match policy?", "Will you match a competitor's price?"]},
    {"id": "payment", "area": "support", "intent": "general", "personal": False, "weight": 5, "audiences": SHOPPERS,
     "variants": ["What payment methods do you accept?", "Do you take PayPal?", "Is there a pay-in-four option?"]},
    {"id": "account_details", "area": "support", "intent": "account", "personal": False, "weight": 5, "audiences": SHOPPERS,
     "variants": ["How do I update my account details?", "How do I change the email on an account?"]},
    {"id": "account_mine", "area": "support", "intent": "account", "personal": True, "weight": 5, "audiences": CUS,
     "variants": ["How many rewards points do I have?", "What tier is my account?", "Do I have any store credit?"]},
    {"id": "rewards", "area": "support", "intent": "account", "personal": False, "weight": 4, "audiences": SHOPPERS,
     "variants": ["How does Larkfield Rewards work?", "What do Gold members get?"]},
    {"id": "warranty", "area": "support", "intent": "product", "personal": False, "weight": 4, "audiences": SHOPPERS,
     "variants": ["What warranty do your products have?", "How long is the chair warranty?"]},
    {"id": "human", "area": "support", "intent": "general", "personal": False, "weight": 3, "audiences": SHOPPERS,
     "variants": ["How do I reach a person?", "Is there a phone number for customer care?"]},
    {"id": "damaged", "area": "support", "intent": "service_recovery", "personal": True, "weight": 2, "audiences": CUS,
     "variants": ["My order arrived damaged and I'm really disappointed.", "The item I received is defective.",
                  "My delivery came scratched, this is unacceptable."]},
    # --- E-Commerce & Order Tracking ---------------------------------------------------
    {"id": "order_mine", "area": "commerce", "intent": "order", "personal": True, "weight": 10, "audiences": CUS,
     "variants": ["Where is my order?", "When will my order arrive?", "Can you track my package?"]},
    {"id": "order_followup", "area": "commerce", "intent": "order", "personal": True, "weight": 6, "audiences": CUS, "followup_of": "order_mine",
     "variants": ["Can I reschedule my delivery?", "Which carrier is delivering my order?", "What's my tracking number?"]},
    {"id": "track_how", "area": "commerce", "intent": "order", "personal": False, "weight": 5, "audiences": SHOPPERS,
     "variants": ["How do I track an order?", "Can an order be cancelled after it ships?"]},
    {"id": "return_mine", "area": "commerce", "intent": "return", "personal": True, "weight": 8, "audiences": CUS,
     "variants": ["Can I return something from my last order?", "I want to return an item.", "What can I still send back?"]},
    {"id": "return_followup", "area": "commerce", "intent": "return", "personal": True, "weight": 5, "audiences": CUS, "followup_of": "return_mine",
     "variants": ["Can I exchange it instead of a refund?", "How many days do I have left to return it?"]},
    {"id": "cart_mine", "area": "commerce", "intent": "cart", "personal": True, "weight": 7, "audiences": CUS,
     "variants": ["What's in my cart?", "Is the offer on my cart still valid?", "Can I check out my saved cart?"]},
    {"id": "cart_offer", "area": "commerce", "intent": "cart", "personal": False, "weight": 3, "audiences": SHOPPERS,
     "variants": ["Why did I get a cart reminder offer?", "How do cart offer codes work?"]},
    # --- Lead Generation & Sales ---------------------------------------------------------
    {"id": "discover_mine", "area": "sales", "intent": "product", "personal": True, "weight": 7, "audiences": SHOPPERS,
     "variants": ["Can you recommend a desk for me?", "What would you suggest for my desk setup?", "I'm looking for a monitor, which one fits me?"]},
    {"id": "desk_how", "area": "sales", "intent": "product", "personal": False, "weight": 5, "audiences": SHOPPERS,
     "variants": ["How do I choose a standing desk?", "Which standing desk size is right?"]},
    {"id": "business_what", "area": "sales", "intent": "sales", "personal": False, "weight": 8, "audiences": SHOPPERS,
     "variants": ["What is Larkfield for Business?", "Do you furnish offices?", "Do you offer volume pricing?"]},
    {"id": "consult_how", "area": "sales", "intent": "sales", "personal": False, "weight": 6, "audiences": SHOPPERS,
     "variants": ["How does a workspace consultation work?", "Is the consultation free?"]},
    {"id": "sales_mine", "area": "sales", "intent": "sales", "personal": True, "weight": 10, "audiences": LEAD,
     "variants": ["We need to furnish our office - where do I start?", "Can I get a quote for our team?", "What would a workspace for my company cost?"]},
    {"id": "consult_mine", "area": "sales", "intent": "sales", "personal": True, "weight": 8, "audiences": LEAD, "followup_of": "sales_mine",
     "variants": ["Can I book a consultation this week?", "When is the next consultation I can get?", "Can we do the consultation by video?"]},
    # --- Internal Operations & HR ----------------------------------------------------------
    {"id": "password_how", "area": "workplace", "intent": "it", "personal": False, "weight": 10, "audiences": EMP,
     "variants": ["How do I reset my password?", "What do I do if I'm locked out?", "How often do passwords expire?"]},
    {"id": "vpn_how", "area": "workplace", "intent": "it", "personal": False, "weight": 8, "audiences": EMP,
     "variants": ["How do I set up the VPN?", "How do I connect from home?"]},
    {"id": "access_how", "area": "workplace", "intent": "it", "personal": False, "weight": 5, "audiences": EMP,
     "variants": ["How do I get access to a system?", "Which systems need approval?"]},
    {"id": "it_mine", "area": "workplace", "intent": "it", "personal": True, "weight": 9, "audiences": EMP,
     "variants": ["My laptop won't connect to the VPN.", "I need a ticket for my laptop.", "Is there any update on my ticket?"]},
    {"id": "it_followup", "area": "workplace", "intent": "it", "personal": True, "weight": 5, "audiences": EMP, "followup_of": "it_mine",
     "variants": ["When does my password expire?", "What systems do I have access to?"]},
    {"id": "benefits_how", "area": "workplace", "intent": "hr", "personal": False, "weight": 9, "audiences": EMP,
     "variants": ["When do I enroll in benefits?", "What medical plans are there?", "Does Larkfield match 401(k) contributions?"]},
    {"id": "pto_how", "area": "workplace", "intent": "hr", "personal": False, "weight": 7, "audiences": EMP,
     "variants": ["How much paid time off do I get?", "What is the parental leave policy?", "When do I get paid?"]},
    {"id": "hr_mine", "area": "workplace", "intent": "hr", "personal": True, "weight": 8, "audiences": EMP,
     "variants": ["How many vacation days do I have?", "Am I enrolled in benefits?", "When is my next paycheck?"]},
    {"id": "onboarding_how", "area": "workplace", "intent": "onboarding", "personal": False, "weight": 6, "audiences": EMP,
     "variants": ["What paperwork do I need to finish as a new hire?", "What documents do I need for the I-9?"]},
    {"id": "onboarding_mine", "area": "workplace", "intent": "onboarding", "personal": True, "weight": 6, "audiences": EMP,
     "variants": ["What's left on my onboarding checklist?", "Which onboarding forms do I still need to sign?"]},
    {"id": "discount", "area": "workplace", "intent": "hr", "personal": False, "weight": 3, "audiences": EMP,
     "variants": ["What is the team member discount?", "Is there an employee discount?"]},
    # --- the audience gate: a shopper asking an internal question ---------------------------
    {"id": "gate_internal", "area": "workplace", "intent": "it", "personal": False, "weight": 1, "audiences": SHOPPERS, "restricted": True,
     "variants": ["How do I reset my VPN password?", "How do I get the VPN client installed?"]},
]
USE_CASE_BY_ID = {u["id"]: u for u in USE_CASES}

# What people tell OneChat about themselves - written to AOM Agent Memory,
# recalled on their later personal turns.
STATEMENTS = {
    "customer": ["I'm left-handed, so the mouse matters.", "I work from a small apartment.", "I have a bad back and need real lumbar support.",
                 "We always prefer oak finishes.", "I don't like glossy screens.", "I'm usually only home after 4pm for deliveries."],
    "lead": ["Our office is open plan with about 30 desks.", "We're moving to a new floor in March.", "We need everything assembled on site.",
             "I'm comparing three vendors right now.", "Our team is hybrid, in the office three days a week."],
    "employee": ["I work the closing shift most days.", "I'm remote on Mondays and Fridays.", "I prefer a Mac if a refresh comes up.",
                 "I'm new, I started last week.", "My manager asked me to get analytics access."],
}

RUN: dict = {"state": "idle"}
_TASK: asyncio.Task | None = None


def _normalize_outcome(llm: dict) -> str:
    """AOM reports `hit_exact`, `hit_semantic` or `miss` (plus bypass/error)."""
    st = (llm or {}).get("status") or "local"
    if st.startswith("hit"):
        return "exact_hit" if st in ("hit", "hit_exact") or (llm.get("similarity") or 0) >= 0.999 else "semantic_hit"
    if st == "miss":
        return "miss"
    return st  # local / error / skipped / bypass


class _Plan:
    """The people and their questions, before anything runs."""

    def __init__(self, users: list[dict], turns_per_user: int, seed: int, repeat_ratio: float, paraphrase_ratio: float):
        self.rng = random.Random(seed)
        self.users = users
        self.turns = turns_per_user
        self.repeat_ratio = repeat_ratio
        self.paraphrase_ratio = paraphrase_ratio
        self.followups: dict[str, list] = {}
        for u in USE_CASES:
            if u.get("followup_of"):
                self.followups.setdefault(u["followup_of"], []).append(u)

    def _phrase(self, uc: dict) -> str:
        v = uc["variants"]
        if len(v) > 1 and self.rng.random() < self.paraphrase_ratio:
            return self.rng.choice(v[1:])
        return v[0]

    def _turn(self, uc: dict, message: str | None = None, **extra) -> dict:
        return {"use_case": uc["id"], "area": uc["area"], "intent": uc["intent"], "personal": uc["personal"],
                "message": message or self._phrase(uc), **extra}

    def session(self, user: dict) -> list[dict]:
        """One person's conversation: a statement, a personal thread (open +
        follow-up + maybe repeat), the rest shared questions for their audience."""
        rng, aud = self.rng, user["audience"]
        mine = [u for u in USE_CASES if aud in u["audiences"]]
        playbook = [u for u in mine if not u["personal"]]
        openers = [u for u in mine if u["personal"] and not u.get("followup_of")]
        turns: list[dict] = []
        if rng.random() < 0.5:
            turns.append({"use_case": "statement", "area": "memory", "intent": "memory", "personal": True,
                          "message": rng.choice(STATEMENTS[aud])})
        opener = rng.choices(openers, weights=[u["weight"] for u in openers])[0]
        first = self._phrase(opener)
        turns.append(self._turn(opener, first))
        fu = [f for f in self.followups.get(opener["id"], []) if aud in f["audiences"]]
        if fu:
            turns.append(self._turn(rng.choice(fu)))
        if rng.random() < self.repeat_ratio:
            turns.append(self._turn(opener, first, repeat=True))
        while len(turns) < self.turns:
            turns.append(self._turn(rng.choices(playbook, weights=[u["weight"] for u in playbook])[0]))
        return turns[: max(self.turns, 2)]


async def pick_users(users_per_group: int, groups: list[str] | None, seed: int) -> list[dict]:
    if not STATE.get("export_date"):
        raise RuntimeError("no export loaded yet")
    rows = await store.users_by_group()
    rng = random.Random(seed)
    rng.shuffle(rows)
    want = set(groups or C.GROUPS)
    by_group: dict[str, list[dict]] = {}
    for r in rows:
        code = r.get("group_code")
        if code in want and len(by_group.setdefault(code, [])) < users_per_group:
            by_group[code].append(r)
    out = []
    for code, g in C.GROUPS.items():
        for r in by_group.get(code, []):
            out.append({"user_id": r["user_id"], "group_code": code, "group_name": g["name"], "audience": g["audience"]})
    return out


def plan(users: list[dict], turns_per_user=6, seed=7, repeat_ratio=0.5, paraphrase_ratio=0.3) -> list[dict]:
    p = _Plan(users, turns_per_user, seed, repeat_ratio, paraphrase_ratio)
    return [{**u, "turns": p.session(u)} for u in users]


def _empty_bucket() -> dict:
    return {"turns": 0, "llm_exact_hit": 0, "llm_semantic_hit": 0, "llm_miss": 0, "llm_other": 0,
            "context_hit": 0, "context_miss": 0, "rag_app": 0, "memory_writes": 0, "restricted": 0, "errors": 0,
            "tokens_saved": 0, "cost_saved_usd": 0.0, "latency_ms_total": 0.0}


def _count(bucket: dict, rec: dict):
    bucket["turns"] += 1
    o = rec["llm_outcome"]
    bucket[{"exact_hit": "llm_exact_hit", "semantic_hit": "llm_semantic_hit", "miss": "llm_miss"}.get(o, "llm_other")] += 1
    if rec.get("context") == "hit":
        bucket["context_hit"] += 1
    elif rec.get("context") in ("miss", "built"):
        bucket["context_miss"] += 1
    if rec.get("path") == "rag_app":
        bucket["rag_app"] += 1
    if rec.get("use_case") == "statement":
        bucket["memory_writes"] += 1
    if rec.get("restricted"):
        bucket["restricted"] += 1
    if rec.get("error"):
        bucket["errors"] += 1
    bucket["tokens_saved"] += rec.get("tokens_saved") or 0
    bucket["cost_saved_usd"] = round(bucket["cost_saved_usd"] + (rec.get("cost_saved_usd") or 0), 6)
    bucket["latency_ms_total"] += rec.get("latency_ms") or 0


def _finish_bucket(b: dict) -> dict:
    cacheable = b["llm_exact_hit"] + b["llm_semantic_hit"] + b["llm_miss"]
    ctx = b["context_hit"] + b["context_miss"]
    b["llm_hit_rate"] = round(100 * (b["llm_exact_hit"] + b["llm_semantic_hit"]) / cacheable, 1) if cacheable else None
    b["context_hit_rate"] = round(100 * b["context_hit"] / ctx, 1) if ctx else None
    b["avg_latency_ms"] = round(b["latency_ms_total"] / b["turns"], 1) if b["turns"] else None
    return b


async def _one_turn(user: dict, turn: dict, session_id: str) -> dict:
    t0 = time.perf_counter()
    rec = {"user_id": user["user_id"], "group_code": user["group_code"], "group_name": user["group_name"],
           "audience": user["audience"], "use_case": turn["use_case"], "expected_intent": turn["intent"],
           "message": turn["message"], "repeat": bool(turn.get("repeat"))}
    try:
        res = await assistant.ask(user["user_id"], turn["message"], session_id)
        llm = res.get("llm") or {}
        ctx = res.get("context") or {}
        rec.update({
            "intent": res.get("intent"), "area": res.get("area"), "personal": res.get("personal"),
            "restricted": bool(res.get("restricted")),
            "path": ("restricted" if res.get("restricted") else "rag_app" if ctx.get("source") == "aom-rag"
                     else "personal" if res.get("personal") else "playbook"),
            "rag_app": ctx.get("rag_app"),
            "llm_status": llm.get("status"), "llm_outcome": _normalize_outcome(llm), "similarity": llm.get("similarity"),
            "stub": bool(llm.get("stub")), "provider": llm.get("provider"), "model": llm.get("model"),
            "tokens_saved": llm.get("tokens_saved") or 0, "cost_saved_usd": llm.get("cost_saved_usd") or 0,
            "context": ctx.get("status"), "context_source": ctx.get("source"),
            "memory_recalled": res.get("memory_recalled", 0), "trace_id": res.get("trace_id"),
            "reply": (res.get("reply") or "")[:160],
        })
    except Exception as exc:  # noqa: BLE001 - one failing turn must not stop the run
        rec.update({"error": str(exc)[:200], "llm_outcome": "error", "path": "error"})
    rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return rec


# A day in a company chatbot's queue: relative traffic per local hour (0-23).
# Quiet overnight, a morning ramp as offices and stores open, steady afternoon,
# an evening peak when shoppers are home, tailing off late. Used when a run is spread over
# `duration_hours` so the AOM charts look like a real queue, not a metronome.
DIURNAL = [0.25, 0.18, 0.15, 0.15, 0.2, 0.35, 0.6, 0.85, 1.0, 1.1, 1.15, 1.15,
           1.1, 1.05, 1.0, 1.0, 1.1, 1.3, 1.5, 1.6, 1.5, 1.2, 0.8, 0.45]
WORKLOAD_TZ = ZoneInfo("America/New_York")


def _traffic_integral(start: dt.datetime, hours: float) -> float:
    """Area under the diurnal curve from `start` for `hours` (hour-weights)."""
    total, t = 0.0, start
    remaining = hours
    while remaining > 1e-9:
        step = min(remaining, 1.0 - (t.minute * 60 + t.second) / 3600.0)
        total += DIURNAL[t.hour] * step
        t += dt.timedelta(hours=step)
        remaining -= step
    return total


class _Pacer:
    """Holds the run to a schedule: by `elapsed` hours the run should have
    completed total_turns * (traffic so far / traffic over the whole run)."""

    def __init__(self, total_turns: int, duration_hours: float):
        self.total = total_turns
        self.hours = duration_hours
        self.start = dt.datetime.now(WORKLOAD_TZ)
        self.whole = _traffic_integral(self.start, duration_hours) or 1.0

    def target(self, now: dt.datetime | None = None) -> int:
        now = now or dt.datetime.now(WORKLOAD_TZ)
        elapsed = min(self.hours, max(0.0, (now - self.start).total_seconds() / 3600.0))
        return int(self.total * _traffic_integral(self.start, elapsed) / self.whole)

    async def wait(self, done: int):
        """Sleep until the schedule allows the next turn (polling, so Stop works)."""
        while done >= self.target() and not RUN.get("cancel"):
            if (dt.datetime.now(WORKLOAD_TZ) - self.start).total_seconds() / 3600.0 >= self.hours:
                return
            await asyncio.sleep(2)


async def _run(sessions: list[dict], concurrency: int, pace_ms: int, duration_hours: float | None = None):
    sem = asyncio.Semaphore(max(1, concurrency))
    by_group = {s["group_code"]: _empty_bucket() | {"group_name": s["group_name"], "audience": s["audience"], "users": 0} for s in sessions}
    by_use_case: dict[str, dict] = {}
    by_path: dict[str, dict] = {}
    by_area: dict[str, dict] = {}
    total = _empty_bucket()
    recent: list[dict] = []
    RUN.update(by_group=by_group, by_use_case=by_use_case, by_path=by_path, by_area=by_area, total=total, recent=recent,
               done_turns=0, done_users=0)
    pacer = _Pacer(RUN["total_turns"], duration_hours) if duration_hours else None
    if pacer:
        RUN["ends_at"] = (pacer.start + dt.timedelta(hours=duration_hours)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def one_user(s: dict):
        async with sem:
            by_group[s["group_code"]]["users"] += 1
            session_id = f"workload-{RUN['run_id']}-{s['user_id']}"
            for turn in s["turns"]:
                if RUN.get("cancel"):
                    return
                if pacer:
                    await pacer.wait(RUN["done_turns"])
                    if RUN.get("cancel"):
                        return
                rec = await _one_turn(s, turn, session_id)
                for b in (total, by_group[s["group_code"]], by_use_case.setdefault(rec["use_case"], _empty_bucket()),
                          by_path.setdefault(rec["path"], _empty_bucket()),
                          by_area.setdefault(rec.get("area") or turn["area"], _empty_bucket())):
                    _count(b, rec)
                recent.append(rec)
                del recent[:-40]
                RUN["done_turns"] += 1
                if pace_ms:
                    await asyncio.sleep(pace_ms / 1000)
            RUN["done_users"] += 1

    t0 = time.time()
    try:
        await asyncio.gather(*(one_user(s) for s in sessions))
        RUN["state"] = "cancelled" if RUN.get("cancel") else "done"
    except asyncio.CancelledError:
        RUN["state"] = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001
        RUN.update(state="error", error=str(exc)[:300])
        log.exception("workload failed")
    finally:
        RUN["seconds"] = round(time.time() - t0, 1)
        RUN["finished_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for b in [total, *by_group.values(), *by_use_case.values(), *by_path.values(), *by_area.values()]:
            _finish_bucket(b)
        log.info("Workload %s: %s turns in %.1fs - LLM hit rate %s%%, context hit rate %s%%", RUN["state"],
                 total["turns"], RUN["seconds"], total["llm_hit_rate"], total["context_hit_rate"])


async def start(users_per_group=3, turns_per_user=6, concurrency=4, groups: list[str] | None = None, seed: int = 7,
                repeat_ratio=0.5, paraphrase_ratio=0.3, pace_ms=0, duration_hours: float | None = None) -> dict:
    """`duration_hours` spreads the run over that long (e.g. 24) following the
    DIURNAL curve; otherwise it runs as fast as `concurrency` allows."""
    global _TASK
    if RUN.get("state") == "running":
        raise RuntimeError("a workload is already running - stop it first (DELETE /api/demo/workload)")
    unknown = [g for g in (groups or []) if g not in C.GROUPS]
    if unknown:
        raise ValueError(f"unknown group code(s): {', '.join(unknown)}; groups are {', '.join(C.GROUPS)}")
    users = await pick_users(users_per_group, groups, seed)
    if not users:
        raise RuntimeError(f"no users loaded from export {STATE.get('export_date')}")
    sessions = plan(users, turns_per_user, seed, repeat_ratio, paraphrase_ratio)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    apps = rag_app.app_ids()
    RUN.clear()
    RUN.update(state="running", run_id=run_id, started_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               params={"users_per_group": users_per_group, "turns_per_user": turns_per_user, "concurrency": concurrency,
                       "groups": groups or list(C.GROUPS), "seed": seed, "repeat_ratio": repeat_ratio,
                       "paraphrase_ratio": paraphrase_ratio, "pace_ms": pace_ms, "duration_hours": duration_hours},
               total_users=len(sessions), total_turns=sum(len(s["turns"]) for s in sessions),
               groups_covered=sorted({s["group_code"] for s in sessions}), group_count=len(C.GROUPS),
               aom={"configured": aom.enabled, "url": config.AOM_URL or None, "dashboard_url": config.AOM_DASHBOARD_URL or None,
                    "rag_apps": apps,
                    "llm_namespaces": [config.llm_namespace(a, p) for a in apps for p in (False, True)],
                    "context_namespaces": [config.context_namespace(a) for a in apps]},
               export_date=STATE.get("export_date"))
    if duration_hours:
        RUN["ends_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=duration_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _TASK = asyncio.create_task(_run(sessions, concurrency, pace_ms, duration_hours))
    return status()


def status() -> dict:
    out = dict(RUN)
    out.pop("cancel", None)
    if out.get("state") == "running":
        if out.get("params", {}).get("duration_hours") and out.get("started_at"):
            started = dt.datetime.strptime(out["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            out["elapsed_hours"] = round((dt.datetime.now(dt.timezone.utc) - started).total_seconds() / 3600, 2)
        # live rates while it runs
        out["total"] = _finish_bucket(dict(out.get("total") or _empty_bucket()))
        for k in ("by_group", "by_area"):
            out[k] = {g: _finish_bucket(dict(v)) for g, v in (out.get(k) or {}).items()}
    return out


async def stop() -> dict:
    if RUN.get("state") == "running":
        RUN["cancel"] = True
        if _TASK:
            try:
                await asyncio.wait_for(asyncio.shield(_TASK), timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _TASK.cancel()
    return status()


def catalog() -> dict:
    """The scenario, for the story page and the CLI: groups and use cases."""
    return {
        "company": C.COMPANY["name"],
        "groups": [{"code": c, **g} for c, g in C.GROUPS.items()],
        "areas": C.AREAS,
        "use_cases": [{k: v for k, v in u.items()} for u in USE_CASES],
        "statements": STATEMENTS,
    }
