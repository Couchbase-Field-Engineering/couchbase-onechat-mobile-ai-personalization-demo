"""The AOM-governed path, against tests/fake_aom.py (same routes and shapes as
the real AOM): KB publishing, document-scoped retrieval, two RAG applications
that keep customer and workplace knowledge apart, LLM cache across users,
tool calls over real MCP, the human-approval tier and the Returns Agent.
"""
import os
import subprocess
import sys
import time
import uuid

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
AOM, API = "http://127.0.0.1:18094", "http://127.0.0.1:18204"
MAYA, DANIEL, SOFIA = ("5510101", "Chen"), ("5520202", "Okafor"), ("5530303", "Alvarez")
KEY = {"Authorization": "Bearer fake-agent-key"}


def wait(url, tries=80):
    for _ in range(tries):
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{url} never came up")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    dump = tmp_path_factory.mktemp("dump")
    subprocess.run([sys.executable, os.path.join(ROOT, "datagen", "generate_mock_export.py"), "--export-date",
                    "2026-11-13", "--target-mb", "2", "--out", str(dump)], check=True, capture_output=True)
    env = {**os.environ, "STORE_DRIVER": "memory", "EXPORT_DIR": str(dump), "SOR_MOCK_LATENCY_MS": "1,2", "AOM_URL": AOM,
           "AOM_AGENT_API_KEY": "fake-agent-key", "AOM_RETURNS_AGENT_API_KEY": "fake-agent-key", "AOM_ADMIN_PASSWORD": "x",
           "KB_PROFILE_LIMIT": "10", "SG_ADMIN_URL": "", "REQUEST_POLL_SECONDS": "0.3", "FAKE_MCP_URL": f"{API}/oc/mcp"}
    uv = [sys.executable, "-m", "uvicorn"]
    procs = [subprocess.Popen(uv + ["tests.fake_aom:app", "--port", "18094"], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    wait(f"{AOM}/api/health")
    procs.append(subprocess.Popen(uv + ["app.main:app", "--port", "18204"], cwd=BACKEND, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(f"{API}/api/health")
    for _ in range(60):
        st = httpx.get(f"{API}/api/status").json()
        if (st["load"].get("kb") or {}).get("state") == "published":
            break
        time.sleep(0.25)
    yield
    for p in procs:
        p.terminate()


def login(account, last):
    r = httpx.post(f"{API}/api/auth/login", json={"account_id": account, "last_name": last})
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user_id"]


def ask(h, q):
    return httpx.post(f"{API}/api/chat", headers=h, json={"message": q}, timeout=30).json()


def state():
    return httpx.get(f"{AOM}/test/state").json()


def push(h, uid, tool, args, until=("confirmed", "failed", "submitted")):
    rid = f"req::{uid}::{uuid.uuid4().hex[:8]}"
    httpx.post(f"{API}/api/sync/push", headers=h, json={"docs": [{"collection": "requests", "id": rid, "doc": {
        "type": "request", "user_id": uid, "tool": tool, "title": tool, "args": args, "created_at": "2026-11-13T15:00:00Z"}}]})

    def req():
        docs = httpx.get(f"{API}/api/sync/pull", headers=h).json()["docs"]
        return next(d["doc"] for d in docs if d["id"] == rid)

    for _ in range(40):
        if req()["status"] in until:
            break
        time.sleep(0.2)
    return req(), req


def test_kb_published_and_scoped(stack):
    titles = list(state()["docs"].values())
    assert any(t.startswith("Larkfield Help Center") for t in titles)
    assert any(t.startswith("Larkfield Team Handbook") for t in titles)
    assert any("C00000101" in t for t in titles)
    h, _ = login(*MAYA)
    a = ask(h, "Where is my order?")
    assert a["context"]["kb_mode"] == "aom" and a["governed"]
    searched = [c[1] for c in state()["calls"] if c[0] == "kb_search"]
    assert all(d is not None for d in searched), "every KB search must be scoped to one document"


def test_two_rag_applications_keep_knowledge_apart(stack):
    st = state()
    helpcenter = [d for d, t in st["docs"].items() if t.startswith("Larkfield Help Center")]
    handbook = [d for d, t in st["docs"].items() if t.startswith("Larkfield Team Handbook")]
    cust, work = st["rag_apps"]["onechat-assistant"], st["rag_apps"]["onechat-workplace"]
    assert cust["enabled"] and cust["document_ids"] == helpcenter
    assert work["enabled"] and work["document_ids"] == handbook
    assert set(cust["allowed_roles"]) == {"support_agent", "admin"}

    hm, _ = login(*MAYA)
    q = "What is your return policy?"
    a, b = ask(hm, q), ask(hm, q)
    assert a["context"]["source"] == "aom-rag" and a["llm"]["rag_app"] == "onechat-assistant"
    assert b["context"]["status"] == "hit" and b["llm"]["status"] == "hit_exact"
    assert "30 days" in a["reply"] and a["sources"]

    hs, _ = login(*SOFIA)
    w = ask(hs, "How do I reset my password?")
    assert w["context"]["rag_app"] == "onechat-workplace" and "authenticator" in w["reply"]
    # a team member's customer-style question still goes to the customer app
    assert ask(hs, "What are your store hours?")["context"]["rag_app"] == "onechat-assistant"

    before = len([c for c in state()["calls"] if c[0] in ("rag_query", "kb_search", "llm")])
    r = ask(hm, "How do I reset my VPN password?")
    assert r["restricted"] and "team members" in r["reply"]
    assert len([c for c in state()["calls"] if c[0] in ("rag_query", "kb_search", "llm")]) == before, "the gate retrieves nothing"

    rag = [c for c in state()["calls"] if c[0] == "rag_query"]
    assert all(set(c[3]) <= set(helpcenter) for c in rag if c[1] == "onechat-assistant")
    assert all(set(c[3]) <= set(handbook) for c in rag if c[1] == "onechat-workplace")


def test_llm_cache_shared_for_shared_questions_only(stack):
    h1, _ = login(*MAYA)
    h2, _ = login(*DANIEL)
    a = ask(h1, "How long does delivery take?")
    b = ask(h2, "How long does delivery take?")
    assert a["personal"] is False and b["llm"]["status"] == "hit_exact"
    p1 = ask(h1, "Can you recommend a desk for me?")
    p2 = ask(h2, "Can you recommend a desk for me?")
    assert p1["llm"]["namespace"] == "rag:onechat-assistant:personal" and p2["llm"]["status"] == "miss"


def test_personal_context_cached_in_aom_per_app(stack):
    h, uid = login(*MAYA)
    q = "What's in my cart?"
    first, second = ask(h, q), ask(h, q)
    assert first["context"]["status"] in ("miss", "hit")
    assert second["context"]["status"] == "hit" and second["context"]["source"] == "aom"
    sets = [c for c in state()["calls"] if c[0] == "ctx_set" and c[2].startswith(f"{uid}:cart:")]
    assert sets and sets[0][1] == "rag:onechat-assistant:user-context" and sets[0][3] is not None
    hs, sid = login(*SOFIA)
    ask(hs, "How many vacation days do I have?")
    sets = [c for c in state()["calls"] if c[0] == "ctx_set" and c[2].startswith(f"{sid}:hr:")]
    assert sets and sets[0][1] == "rag:onechat-workplace:user-context"


def test_goodwill_credit_waits_for_a_human_and_runs_as_the_returns_agent(stack):
    h, uid = login(*MAYA)
    a = ask(h, "My keyboard arrived with a broken key and I'm really disappointed")
    act = next(x for x in a["actions"] if x.get("tool") == "issue_goodwill_credit")
    assert a["intent"] == "service_recovery" and act["args"]["order_id"] == "LF-874233"
    doc, req = push(h, uid, "issue_goodwill_credit", act["args"], until=("awaiting_approval", "failed"))
    assert doc["status"] == "awaiting_approval" and doc["governed"], doc
    httpx.post(f"{AOM}/test/approve/{doc['approval_id']}")
    for _ in range(30):
        if req()["status"] == "confirmed":
            break
        time.sleep(0.2)
    doc = req()
    assert doc["status"] == "confirmed" and doc["agent"] == "onechat-returns-agent" and doc["remembered"] is True


def test_privileged_access_waits_for_a_human(stack):
    h, uid = login(*SOFIA)
    doc, _ = push(h, uid, "complete_onboarding_task", {"task_id": "security-training"})
    assert doc["status"] == "confirmed", doc
    a = ask(h, "I need access to the Sales Analytics workspace for my weekly reports")
    act = a["actions"][0]
    assert act["tool"] == "request_privileged_access" and act["args"]["system"] == "analytics"
    doc, req = push(h, uid, act["tool"], act["args"], until=("awaiting_approval", "failed"))
    assert doc["status"] == "awaiting_approval", doc
    httpx.post(f"{AOM}/test/approve/{doc['approval_id']}")
    for _ in range(30):
        if req()["status"] == "confirmed":
            break
        time.sleep(0.2)
    assert req()["status"] == "confirmed" and req()["agent"] == "onechat-assistant"


def test_confirm_return_runs_the_returns_agent_with_memory(stack):
    """Confirm on the Return screen -> a start_return request -> the Returns
    Agent runs it through AOM and writes to Agent Memory, which the assistant
    then recalls."""
    h, uid = login(*MAYA)
    before = state()["memory"]
    doc, _ = push(h, uid, "start_return", {"order_id": "LF-880517", "sku": "CHR-LUM-BLK", "reason": "Too large for my desk, wrong size",
                                           "resolution": "exchange", "exchange_sku": "CHR-PRC-GRY"})
    assert doc["status"] == "confirmed", doc
    assert doc["governed"] and doc["agent"] == "onechat-returns-agent" and doc["remembered"] is True
    assert state()["memory"] >= before + 2            # the episode and the size preference
    a = ask(h, "Can you recommend a chair for me?")
    assert a["memory_recalled"] >= 1


def test_company_workload_hits_aom_caches(stack):
    """The company-wide workload through the fake AOM: shared questions repeat
    across users (exact LLM hits), personal follow-ups reuse the person's
    context (context hits), and the CLI reports it."""
    body = {"users_per_group": 2, "turns_per_user": 6, "concurrency": 4, "seed": 11}
    r = httpx.post(f"{API}/api/demo/workload", json=body, timeout=30)
    assert r.status_code == 200, r.text
    for _ in range(600):
        run = httpx.get(f"{API}/api/demo/workload").json()
        if run["state"] != "running":
            break
        time.sleep(0.2)
    assert run["state"] == "done", run.get("error")
    t = run["total"]
    assert t["errors"] == 0 and t["turns"] == 12 * 2 * 6
    assert t["llm_exact_hit"] > 0, t           # the same shared question from a second person
    assert t["llm_miss"] > 0                    # the first person paid for it
    assert t["context_hit"] > 0                 # follow-ups in the same intent reuse the person's context
    assert t["rag_app"] > 0                     # shared questions went to a RAG application
    assert len(run["by_group"]) == 12 and set(run["by_area"]) >= {"support", "commerce", "sales", "workplace"}
    # the CLI summarizes the same run
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "run_chatbot_workload.py"),
                          "--backend", API, "--status"], capture_output=True, text=True, check=True).stdout
    assert '"state": "done"' in out


def test_demo_reset_clears_aom_memory_and_caches(stack):
    """After the workload and a chat that wrote a memory, the reset deletes
    the people's AOM memories, purges both apps' namespaces, and the next
    question is a cache miss again."""
    h, uid = login(*MAYA)
    ask(h, "I have a bad back and need real lumbar support.")          # -> AOM Agent Memory
    assert httpx.get(f"{AOM}/v1/memory", params={"user_id": uid}, headers=KEY).json()["count"] >= 1
    ask(h, "What is your return policy?")
    res = httpx.post(f"{API}/api/demo/reset", json={}, timeout=60).json()
    assert res["state"] == "done", res
    me = next(g for g in res["users"] if g["user_id"] == uid)
    assert me["memories"] >= 1 and "memory_error" not in me
    assert httpx.get(f"{AOM}/v1/memory", params={"user_id": uid}, headers=KEY).json()["count"] == 0
    assert "error" not in res["aom_caches"], res["aom_caches"]
    assert sum(v.get("llm_purged", 0) for v in res["aom_caches"].values()) >= 1
    assert any(ns.startswith("rag:onechat-workplace") for ns in res["aom_caches"])
    a = ask(h, "What is your return policy?")
    assert a["llm"]["status"] == "miss"
    # the chair exchanged earlier is back on Maya's order, returnable again
    docs = {d["id"]: d["doc"] for d in httpx.get(f"{API}/api/sync/pull", headers=h).json()["docs"]}
    assert docs[f"profile::{uid}"]["returns"] == [] and docs[f"profile::{uid}"]["rev"] == 0
