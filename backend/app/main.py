"""Backend for the Couchbase OneChat demo - one chatbot for a whole company.

  /api/*         app sign-in (mints a Sync Gateway session), the assistant, status,
                 and a REST "preview sync" used only by the browser preview build
  /oc/mcp/       the onechat-services MCP server AOM governs

Background tasks: the nightly export loader/poller and the offline-first
request worker.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import logging
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import aom_bootstrap, assistant, config, demo_reset, loader, metrics, personalization, rag_app, sgw, sources, worker, workload
from . import catalog as C
from .aom_client import aom
from .docs import (CATALOG_ID, HANDBOOK_ID, STATE, activity_id, channels_for, chat_id, ctx_id, feed_id, now_iso,
                   profile_id, user_channel)
from .mcp_server import mcp
from .store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("onechat.api")

PERSONA_BLURBS = {
    "C00000101": "Customer support and e-commerce: a desk arriving in 2 days, a chair she can still return, a cart with a 10% offer.",
    "L00000201": "Lead generation and sales: office manager at a 28-person studio - capture details, qualify, book a consultation.",
    "E00000301": "Internal IT and HR: a new hire on day 6 - onboarding paperwork, benefits enrollment, a VPN ticket.",
}
_bg: list = []


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await store.connect()

    auto_register = config.AOM_AUTO_REGISTER and bool(config.AOM_ADMIN_PASSWORD)

    async def initial_load():
        try:
            # With self-registration the KB is published once AOM sign-in works.
            await loader.load(kb=not auto_register)
        except Exception:  # noqa: BLE001
            log.exception("initial export load failed")

    first = asyncio.create_task(initial_load())
    _bg.append(first)
    if auto_register:
        _bg.append(asyncio.create_task(aom_bootstrap.run(first)))
    _bg.append(asyncio.create_task(worker.loop()))
    _bg.append(asyncio.create_task(loader.poll_forever()))
    async with mcp.session_manager.run():
        yield
    for t in _bg:
        t.cancel()


app = FastAPI(title="Couchbase OneChat Demo", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.mount("/oc", mcp.streamable_http_app())


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
def _sign(payload: str) -> str:
    return hmac.new(config.APP_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_token(user_id: str) -> str:
    payload = f"{user_id}|{int(time.time()) + config.APP_TOKEN_TTL_SECONDS}"
    return base64.urlsafe_b64encode(f"{payload}|{_sign(payload)}".encode()).decode()


def current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first")
    try:
        uid, exp, sig = base64.urlsafe_b64decode(authorization.split(" ", 1)[1].encode()).decode().split("|")
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "Invalid session") from None
    if not hmac.compare_digest(sig, _sign(f"{uid}|{exp}")) or int(exp) < time.time():
        raise HTTPException(401, "Session expired - sign in again")
    return uid


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    """Landing page: where everything in the demo lives."""
    rows = [
        ("https://localhost:5150/story", "The story: one chatbot for the whole company, without a model call per question (start here)"),
        ("https://localhost:5150", "The app in a browser (docker compose service <code>web</code>)"),
        ("http://localhost:8202/api/status", "Backend status: export load, Knowledge Base publishing, AOM, Sync Gateway"),
        ("http://localhost:8202/docs", "Backend API (OpenAPI)"),
        ("http://localhost:8202/oc/mcp", "MCP server <code>onechat-services</code> (called by AOM)"),
        ("http://localhost:18093", "Couchbase Web Console (Administrator / password123)"),
        ("ws://localhost:4988/onechat", "Sync Gateway - Couchbase Lite replicates here"),
        ("https://localhost:8090", "Couchbase Agent Operations Manager (its own stack)"),
    ]
    items = "".join(f'<li><a href="{u}">{u}</a> &nbsp;{d}</li>' for u, d in rows)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Couchbase OneChat demo backend</title>
<style>body{{font:16px/1.6 Inter,-apple-system,Segoe UI,sans-serif;max-width:860px;margin:48px auto;padding:0 20px;color:#000}}
h1{{font-weight:600}}a{{color:#EC1218}}code{{background:#F7F7F7;padding:2px 6px;border-radius:6px}}li{{margin:6px 0}}</style></head><body>
<h1>Couchbase OneChat · demo backend</h1>
<p>This is the backend. Open the app at <a href="https://localhost:5150">https://localhost:5150</a>.
Loaded export: <b>{STATE.get("export_date") or "loading..."}</b> ({loader.STATUS.get("state")}).</p>
<ul>{items}</ul></body></html>"""


@app.get("/api/health")
async def health():
    return {"status": "ok", "export_date": STATE.get("export_date"), "load": loader.STATUS.get("state")}


@app.get("/api/status")
async def status():
    aom_state = {"configured": aom.enabled, "url": config.AOM_URL or None, "kb_publisher": aom.admin_enabled,
                 "last_error": aom.last_error, "registration": aom_bootstrap.STATUS, "rag_apps": rag_app.STATUS,
                 "context_namespaces": [config.context_namespace(a) for a in rag_app.app_ids()],
                 "dashboard_url": config.AOM_DASHBOARD_URL or None}
    if aom.enabled:
        try:
            aom_state["health"] = await aom.health()
        except Exception as exc:  # noqa: BLE001
            aom_state["health"] = {"error": str(exc)[:200]}
    return {"store": store.driver, "company": C.COMPANY["name"], "export_date": STATE.get("export_date"),
            "load": {k: v for k, v in loader.STATUS.items()},
            "sources": {"profile": {**sources.STATUS["profile"], "endpoint": config.SOR_PROFILE_API_URL or None},
                        "cms": {**sources.STATUS["cms"], "endpoint": config.CMS_KB_ENDPOINT or None},
                        "export_dir": config.EXPORT_DIR},
            "aom": aom_state, "metrics": metrics.snapshot(),
            "sync_gateway": {"configured": sgw.enabled(), "public_url": config.SG_PUBLIC_URL or None, "db": config.SG_DB},
            "mcp_server": {"server_id": config.AOM_MCP_SERVER_ID, "registered_url": config.AOM_MCP_PUBLIC_URL},
            "workload": {k: v for k, v in workload.status().items()
                         if k in ("state", "run_id", "started_at", "finished_at", "seconds", "done_turns", "total_turns",
                                  "done_users", "total_users", "groups_covered", "group_count", "total", "by_area")}}


def _headline(p: dict) -> str:
    if p["audience"] == "customer":
        return f"{p['loyalty']['tier']} member · {p.get('home_city')}"
    if p["audience"] == "lead":
        return f"{p['lead'].get('role')} · {p['company']['name']}"
    return f"{p['employment']['title']} · {p['employment']['department']}"


@app.get("/api/demo/personas")
async def personas():
    out = []
    for uid in loader.PERSONAS:
        p = await store.get("profiles", profile_id(uid))
        if not p:
            continue
        out.append({"user_id": uid, "name": f"{p['first_name']} {p['last_name']}", "last_name": p["last_name"],
                    "account_id": p["account_id"], "audience": p["audience"], "audience_label": C.AUDIENCES[p["audience"]],
                    "headline": _headline(p), "blurb": PERSONA_BLURBS.get(uid, "")})
    return {"personas": out, "export_date": STATE.get("export_date"), "company": C.COMPANY["name"]}


class LoginRequest(BaseModel):
    account_id: str
    last_name: str


def _who(profile: dict) -> dict:
    return {"first_name": profile["first_name"], "last_name": profile["last_name"], "audience": profile["audience"],
            "headline": _headline(profile), "email": profile.get("email")}


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    idx = await store.get("lookups", f"account::{req.account_id.strip()}")
    ln = req.last_name.strip().lower()
    if not idx or ln not in idx.get("last_names", []):
        raise HTTPException(401, "We couldn't find that account. Check the number and last name.")
    user_id = None
    for uid in idx["users"]:
        p = await store.get("profiles", profile_id(uid))
        if p and p["last_name"].lower() == ln:
            user_id = uid
            break
    if not user_id:
        raise HTTPException(401, "We couldn't find that account. Check the number and last name.")
    await personalization.refresh_feed(user_id)
    profile = await store.get("profiles", profile_id(user_id))
    sg = await sgw.mint_session(user_id, profile["audience"])
    return {"token": make_token(user_id), "user_id": user_id, "user": _who(profile),
            "channels": channels_for(profile["audience"], user_id), "sync_gateway": sg,
            "export_date": STATE.get("export_date")}


@app.post("/api/auth/refresh")
async def refresh(user_id: str = Depends(current_user)):
    """Re-mint the Sync Gateway session (24h) for a signed-in user - called by
    the app on launch when it has connectivity."""
    profile = await store.get("profiles", profile_id(user_id))
    if not profile:
        raise HTTPException(401, "Session expired - sign in again")
    await personalization.refresh_feed(user_id)
    return {"token": make_token(user_id), "user_id": user_id, "sync_gateway": await sgw.mint_session(user_id, profile["audience"]),
            "export_date": STATE.get("export_date")}


@app.get("/api/me")
async def me(user_id: str = Depends(current_user)):
    return await store.get("profiles", profile_id(user_id))


async def _user_docs(user_id: str) -> list[dict]:
    """What this person's Sync Gateway channels carry. The Team Handbook
    document is on the `employees` channel, so only a team member gets it."""
    out = []
    profile = await store.get("profiles", profile_id(user_id))
    wanted = [("profiles", profile_id(user_id)), ("feed", feed_id(user_id)), ("activity", activity_id(user_id)),
              ("chat", chat_id(user_id)), ("catalog", CATALOG_ID)]
    if profile and profile.get("audience") == "employee":
        wanted.append(("catalog", HANDBOOK_ID))
    for col, key in wanted:
        d = profile if col == "profiles" else await store.get(col, key)
        if d:
            out.append({"collection": col, "id": key, "doc": d})
    for key in assistant.CONTEXT_KEYS:
        d = await store.get("context_cache", ctx_id(user_id, key))
        if d:
            out.append({"collection": "context_cache", "id": ctx_id(user_id, key), "doc": d})
    for d in await store.requests_for_user(user_id):
        key = d.pop("_id")
        out.append({"collection": "requests", "id": key, "doc": d})
    return out


@app.get("/api/sync/pull")
async def sync_pull(user_id: str = Depends(current_user)):
    """Browser-preview stand-in for Sync Gateway: the same documents and ids
    the person's channels would replicate into Couchbase Lite."""
    return {"docs": await _user_docs(user_id), "at": now_iso(), "export_date": STATE.get("export_date")}


class PushDoc(BaseModel):
    collection: str
    id: str
    doc: dict


class PushRequest(BaseModel):
    docs: list[PushDoc] = Field(default_factory=list)


@app.post("/api/sync/push")
async def sync_push(req: PushRequest, user_id: str = Depends(current_user)):
    """Browser-preview stand-in for a push replication. Same rule the Sync
    Gateway sync function enforces: a person may only create `requests`
    documents, only for themselves, only as `pending`."""
    accepted = []
    for d in req.docs:
        if d.collection != "requests" or d.doc.get("user_id") != user_id or not d.id.startswith(f"req::{user_id}::"):
            raise HTTPException(403, "Only your own action requests can be pushed")
        if await store.get("requests", d.id):
            continue
        doc = {**d.doc, "type": "request", "status": "pending", "channels": [user_channel(user_id)],
               "received_at": now_iso()}
        await store.upsert("requests", d.id, doc)
        accepted.append(d.id)
    if accepted:
        _bg.append(asyncio.create_task(worker.run_once()))
    return {"accepted": accepted}


class AskRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.post("/api/chat")
async def ask(req: AskRequest, user_id: str = Depends(current_user)):
    if not req.message.strip():
        raise HTTPException(400, "Ask me something")
    return await assistant.ask(user_id, req.message[:1000], req.session_id)


# --------------------------------------------------------------------------
# demo: company-wide chatbot workload (see workload.py)
# --------------------------------------------------------------------------
class WorkloadRequest(BaseModel):
    users_per_group: int = Field(3, ge=1, le=1000)    # 12 groups x this many sessions
    turns_per_user: int = Field(6, ge=2, le=30)
    concurrency: int = Field(4, ge=1, le=64)
    groups: list[str] | None = None         # catalog codes, e.g. ["CUS-NE", "EMP-TECH"]; default: the whole company
    seed: int = 7
    repeat_ratio: float = Field(0.5, ge=0, le=1)      # people who ask their personal question twice (exact hit)
    paraphrase_ratio: float = Field(0.3, ge=0, le=1)  # turns that reword a question (semantic hit)
    pace_ms: int = Field(0, ge=0, le=5000)            # pause between a person's turns
    duration_hours: float | None = Field(None, gt=0, le=168)  # spread the run over this long, day/night curve


@app.post("/api/demo/workload")
async def workload_start(req: WorkloadRequest):
    """Start the company-wide workload against AOM: customers from every
    region, prospects and team members from every department ask OneChat
    what such people ask, through the real RAG app / Context Cache / LLM
    Cache / Agent Memory path. Poll GET for progress; the outcome shows on
    AOM's LLM Cache, Context Cache, RAG Applications and Traces pages."""
    try:
        return await workload.start(**req.model_dump())
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409 if "already running" in str(exc) else 400, str(exc)) from None


@app.get("/api/demo/workload")
async def workload_status():
    return workload.status()


@app.delete("/api/demo/workload")
async def workload_stop():
    return await workload.stop()


@app.get("/api/demo/workload/plan")
async def workload_plan(users_per_group: int = 1, turns_per_user: int = 6, seed: int = 7, groups: str | None = None):
    """Preview who would ask what, without running anything."""
    codes = [c.strip().upper() for c in groups.split(",")] if groups else None
    try:
        users = await workload.pick_users(users_per_group, codes, seed)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"sessions": workload.plan(users, turns_per_user, seed), "export_date": STATE.get("export_date")}


@app.get("/api/demo/workload/catalog")
async def workload_catalog():
    """The groups and the use cases the workload draws from."""
    return workload.catalog()


# --------------------------------------------------------------------------
# demo: reset (see demo_reset.py)
# --------------------------------------------------------------------------
class ResetRequest(BaseModel):
    users: list[str] | None = None    # default: the personas + everyone who changed something since the load
    aom_memory: bool = True           # delete these people's AOM Agent Memory entries
    aom_caches: bool = True           # purge OneChat's LLM / Context Cache namespaces in AOM
    counters: bool = True             # zero the in-process counters and forget the last workload report


@app.post("/api/demo/reset")
async def demo_reset_run(req: ResetRequest):
    """Back to the state of today's export: requests, chat, cached context,
    orders/cart/returns, lead, tickets, benefits and onboarding, the feed -
    here and on the phone via Sync Gateway - plus these people's AOM memories
    and OneChat's AOM caches."""
    if workload.RUN.get("state") == "running":
        raise HTTPException(409, "a workload is running - stop it first (DELETE /api/demo/workload)")
    return await demo_reset.run(req.users, req.aom_memory, req.aom_caches, req.counters)


@app.get("/api/demo/reset")
async def demo_reset_last():
    return {"last": demo_reset.LAST, "default_users": await demo_reset.default_users()}


@app.post("/api/admin/reload")
async def reload_export(force: bool = True):
    return {k: v for k, v in (await loader.load(force=force)).items()}
