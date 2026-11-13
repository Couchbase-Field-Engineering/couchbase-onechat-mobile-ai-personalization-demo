#!/usr/bin/env python3
"""Register the Couchbase OneChat demo with the Couchbase Agent Operations Manager.

Idempotent. Standard library only. Does five things through AOM's API, signed
in as an AOM dashboard admin:

  1. Registers this backend's MCP server `onechat-services` as a trusted
     server (POST /v1/servers) - or re-ingests it if it is already registered -
     so AOM pulls its 22 tools into the vetted catalog, open to the
     `support_agent` and `admin` roles.
  2. Issues two agent identities (POST /v1/agents, role support_agent):
     **OneChat Assistant**, scoped to all 22 tools and written to ../.env as
     AOM_AGENT_API_KEY, and **OneChat Returns Agent**, scoped to the 5
     order-and-return tools and written as AOM_RETURNS_AGENT_API_KEY (it runs
     every Confirm on the Return screen and keeps the outcome in AOM Agent
     Memory). With --rotate, rotates the keys of existing agents instead.
  3. Turns on AOM's human-approval tier for
     `onechat-services::issue_goodwill_credit` and
     `onechat-services::request_privileged_access` (store credits and access to
     systems with customer, financial or production data wait for a person),
     leaving every other approval setting as it was.
  4. Registers OneChat's two RAG Applications (POST /v1/rag/apps, or PUT if
     they exist), queryable by the `support_agent` and `admin` roles:
     `onechat-assistant`, scoped to the Help Center document, and
     `onechat-workplace`, scoped to the Team Handbook. Their activity
     (queries, LLM cache hits, Context Cache retrievals) shows on AOM's RAG
     Applications page. The backend re-points them at each night's new
     documents after the load.
  5. Writes AOM_ADMIN_* into ../.env so the backend's nightly loader can
     publish Knowledge Base documents and manage the RAG applications.

    python scripts/register_with_aom.py --aom-url https://localhost:8090 \
        --admin-user admin --admin-password '<your AOM admin password>'
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", ".env")
SERVER_ID = "onechat-services"
OWNER = "Larkfield Digital"
# Keep in step with backend/app/actions.py (TOOLS, APPROVAL_TOOLS).
READ_TOOLS = ["get_user_context", "get_orders", "get_return_options", "get_cart", "recommend_products",
              "get_consultation_slots", "get_it_context", "get_benefits_summary", "get_onboarding_tasks"]
WRITE_TOOLS = ["reschedule_delivery", "start_return", "issue_goodwill_credit", "checkout_cart", "submit_lead_details",
               "book_consultation", "create_it_ticket", "reset_password", "request_system_access",
               "request_privileged_access", "request_time_off", "enroll_benefits", "complete_onboarding_task"]
TOOLS = READ_TOOLS + WRITE_TOOLS
APPROVAL_TOOLS = [f"{SERVER_ID}::issue_goodwill_credit", f"{SERVER_ID}::request_privileged_access"]
AGENTS = [
    {"name": "OneChat Assistant", "env": "AOM_AGENT_API_KEY", "tools": TOOLS,
     "description": ("Larkfield's company-wide chatbot in the OneChat mobile app: customer support and FAQs, order tracking, "
                     "returns and exchanges, lead capture and consultations, and the internal IT and HR help desk. RAG over the "
                     "nightly Help Center, Team Handbook and per-person profiles.")},
    {"name": "OneChat Returns Agent", "env": "AOM_RETURNS_AGENT_API_KEY",
     "tools": ["get_user_context", "get_orders", "get_return_options", "start_return", "issue_goodwill_credit"],
     "description": ("Larkfield returns and exchanges agent. Triggered when a customer confirms a return, an exchange or a "
                     "goodwill credit in the OneChat mobile app: recalls the customer's return history and stated preferences "
                     "from Agent Memory, processes the return as a governed tool call, and remembers the outcome.")},
]
# Keep in step with backend/app/rag_app.py, which owns the definitions at runtime.
_RULES = ("Answer concisely (under 120 words) using only the numbered passages. Never invent prices, policies, dates or "
          "availability. Cite the passages you used as [1], [2].")
RAG_APPS = [
    {"app_id": "onechat-assistant", "title_prefix": "Larkfield Help Center", "name": "OneChat Assistant (customers & prospects)",
     "description": ("Larkfield's company-wide chatbot, customer side: support FAQs, orders and returns policy, products and "
                     "Larkfield for Business. Shared questions are answered here from the nightly Help Center document. "
                     "Personal answers use the asker's own profile, cached in the user-context namespace."),
     "system_prompt": ("You are OneChat, Larkfield's assistant for customers and business prospects. " + _RULES +
                       " If the passages do not answer the question, offer to connect the person with customer care."),
     "no_answer_text": "I couldn't find that in the Help Center. I can connect you with customer care."},
    {"app_id": "onechat-workplace", "title_prefix": "Larkfield Team Handbook", "name": "OneChat Workplace (team members)",
     "description": ("Larkfield's company-wide chatbot, internal side: IT help desk, HR benefits, time off, pay and "
                     "onboarding. Scoped to the nightly Team Handbook document; only signed-in team members are routed here."),
     "system_prompt": ("You are OneChat, the internal assistant for Larkfield team members: IT help desk and HR. " + _RULES +
                       " If the passages do not answer the question, offer to open a ticket or point to a People Partner."),
     "no_answer_text": "I couldn't find that in the Team Handbook. I can open a ticket or point you to your People Partner."},
]


def rag_app_definition(spec: dict, document_id):
    return {
        "app_id": spec["app_id"],
        "name": spec["name"],
        "description": spec["description"],
        "owner": OWNER,
        # Never enabled without a document scope: unscoped, a support_agent
        # query could retrieve any person's profile, or the other audience's knowledge.
        "enabled": bool(document_id),
        "allowed_roles": ["support_agent", "admin"],
        "set_id": "default",
        "document_ids": [document_id] if document_id else [],
        "top_k": 4,
        "retrieval_ttl_seconds": 6 * 3600,
        "semantic_cache": True,
        "system_prompt": spec["system_prompt"],
        "no_answer_text": spec["no_answer_text"],
    }


class Api:
    def __init__(self, base: str, verify: bool):
        self.base = base.rstrip("/")
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                                  urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, ok=(200, 201, 202)):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=180) as r:
                txt = r.read().decode() or "{}"
                return r.status, json.loads(txt)
        except urllib.error.HTTPError as e:
            txt = e.read().decode()
            try:
                payload = json.loads(txt)
            except json.JSONDecodeError:
                payload = {"detail": txt}
            if e.code in ok:
                return e.code, payload
            return e.code, payload


def set_env(updates: dict):
    lines = open(ENV_PATH).read().splitlines() if os.path.exists(ENV_PATH) else []
    seen = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if k in updates:
            lines[i] = f"{k}={updates[k]}"
            seen.add(k)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    with open(ENV_PATH, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def die(msg):
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aom-url", default=os.getenv("AOM_URL_HOST", "https://localhost:8090"),
                    help="AOM as reachable from THIS machine")
    ap.add_argument("--admin-user", default=os.getenv("AOM_ADMIN_USERNAME", "admin"))
    ap.add_argument("--admin-password", default=os.getenv("AOM_ADMIN_PASSWORD"))
    ap.add_argument("--mcp-url", default="http://host.docker.internal:8202/oc/mcp",
                    help="this backend's MCP endpoint as reachable FROM the AOM container")
    ap.add_argument("--aom-url-for-backend", default="https://host.docker.internal:8090",
                    help="AOM as reachable from the demo backend container (written to .env)")
    ap.add_argument("--rotate", action="store_true", help="rotate the agent keys if the agents already exist")
    ap.add_argument("--verify-tls", action="store_true")
    args = ap.parse_args()
    if not args.admin_password:
        die("Pass --admin-password (the AOM dashboard admin password you set at first login)")

    api = Api(args.aom_url, args.verify_tls)
    print(f"→ Signing in to AOM at {args.aom_url} as {args.admin_user}")
    st, body = api.call("POST", "/v1/auth/login", {"username": args.admin_user, "password": args.admin_password})
    if st != 200:
        die(f"AOM login failed ({st}): {body.get('detail')}")

    # 1. MCP server ----------------------------------------------------------
    print(f"→ Registering MCP server '{SERVER_ID}' at {args.mcp_url}")
    st, body = api.call("POST", "/v1/servers", {
        "server_id": SERVER_ID, "label": "Larkfield OneChat Services", "owner": OWNER, "mcp_url": args.mcp_url,
        "trust_status": "trusted", "default_allowed_roles": ["support_agent", "admin"],
    })
    if st == 409:
        st, body = api.call("POST", f"/v1/servers/{SERVER_ID}/reingest")
        if st != 200:
            die(f"Re-ingest failed ({st}): {body.get('detail')}")
        print(f"  already registered - re-ingested {body.get('ingested_tools')} tools")
    elif st == 200:
        if body.get("ingest_error"):
            die(f"Registered, but AOM could not reach {args.mcp_url}: {body['ingest_error']}\n"
                "  Is the demo backend running (docker compose up) and reachable from the AOM container?")
        print(f"  registered - {body.get('ingested_tools')} tools ingested into the vetted catalog")
    else:
        die(f"Server registration failed ({st}): {body.get('detail')}")

    # 2. agent identities -------------------------------------------------------
    st, body = api.call("GET", "/v1/agents")
    if st != 200:
        die(f"Listing agents failed ({st}): {body.get('detail')}")
    agents = body.get("agents", [])
    updates = {"AOM_URL": args.aom_url_for_backend, "AOM_ADMIN_USERNAME": args.admin_user,
               "AOM_ADMIN_PASSWORD": args.admin_password}
    for spec in AGENTS:
        existing = next((a for a in agents if a.get("name") == spec["name"] and a.get("status") == "active"), None)
        if existing and args.rotate:
            print(f"→ Rotating key for agent '{spec['name']}' ({existing['agent_id']})")
            st, body = api.call("POST", f"/v1/agents/{existing['agent_id']}/rotate", {"revoke_immediately": False})
            if st != 200:
                die(f"Rotate failed ({st}): {body.get('detail')}")
            updates[spec["env"]] = body["api_key"]
        elif existing:
            print(f"  agent '{spec['name']}' already exists ({existing['agent_id']}); keeping its key (use --rotate for a new one)")
        else:
            print(f"→ Issuing agent identity '{spec['name']}' (role support_agent, {len(spec['tools'])} scoped tools)")
            st, body = api.call("POST", "/v1/agents", {
                "name": spec["name"], "role": "support_agent", "owner": OWNER, "description": spec["description"],
                "allowed_tools": [f"{SERVER_ID}::{t}" for t in spec["tools"]],
            })
            if st != 200:
                die(f"Agent creation failed ({st}): {body.get('detail')}")
            updates[spec["env"]] = body["api_key"]
            print(f"  agent {body['agent']['agent_id']} issued")

    # 3. approval tier ---------------------------------------------------------------
    st, body = api.call("GET", "/v1/approvals-config")
    if st == 200:
        cfg = body["config"]
        cfg["enabled"] = True
        cfg["require_for_tools"] = sorted(set(cfg.get("require_for_tools") or []) | set(APPROVAL_TOOLS))
        st, body = api.call("PUT", "/v1/approvals-config", {"config": cfg})
        print("→ Approval tier: goodwill credits and privileged access now wait for a person" if st == 200
              else f"  ! could not update approvals ({st}): {body.get('detail')}")

    # 4. RAG applications ------------------------------------------------------------
    st, kb = api.call("GET", "/v1/knowledge")
    docs = (kb.get("documents") or []) if st == 200 else []
    for spec in RAG_APPS:
        mine = sorted((d for d in docs if str(d.get("title", "")).startswith(spec["title_prefix"])),
                      key=lambda d: str(d.get("created_at") or d.get("ingested_at") or d.get("title")))
        doc_id = mine[-1].get("document_id") if mine else None
        app = rag_app_definition(spec, doc_id)
        print(f"→ Registering RAG application '{spec['app_id']}'")
        st, body = api.call("POST", "/v1/rag/apps", {"app": app, "issue_key": False})
        verb = "registered"
        if st == 409:
            st, body = api.call("PUT", f"/v1/rag/apps/{spec['app_id']}", {"app": app})
            verb = "updated"
        if st == 200:
            if doc_id:
                print(f"  {verb}, scoped to {spec['title_prefix']} document {doc_id}")
            else:
                print(f"  {verb} (disabled until the backend publishes today's {spec['title_prefix']} to the Knowledge Base;\n"
                      "  the backend enables it and scopes it to that document on its next load)")
        elif st in (404, 405):
            print("  ! this AOM build has no RAG Applications API - update AOM to see OneChat there")
            break
        else:
            print(f"  ! RAG application registration failed ({st}): {body.get('detail')}")

    # 5. .env + reload -----------------------------------------------------------------
    set_env(updates)
    print(f"→ Wrote {', '.join(updates)} to {os.path.abspath(ENV_PATH)}")
    if updates.get("AOM_AGENT_API_KEY"):
        print(f"\n  Agent API key (shown once by AOM, now in .env): {updates['AOM_AGENT_API_KEY'][:10]}…")
    print("\nNext: docker compose up -d --build backend   (rebuilds and recreates the backend with the new .env;\n"
          "      it publishes the Knowledge Base to AOM and scopes the RAG applications to today's documents)")


if __name__ == "__main__":
    main()
