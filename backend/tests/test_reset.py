"""The demo reset (app/demo_reset.py) in memory mode: after a return, a
checkout and a chat, a persona is back to the export - requests gone, orders
and cart restored, context and chat cleared, the feed re-ranked.

    cd backend && pytest -q tests/test_reset.py
"""
from test_demo_flows import MAYA, ask, login, pull, push


def test_reset_restores_the_persona(client):
    client.post("/api/demo/reset", json={})            # whatever earlier tests did
    h, uid = login(client, *MAYA)
    ask(client, h, "What's in my cart?")
    r = push(client, h, uid, "checkout_cart", {"apply_offer": True})
    assert r["status"] == "confirmed", r
    r = push(client, h, uid, "start_return", {"order_id": "LF-880517", "sku": "CHR-LUM-BLK", "reason": "Too firm"})
    assert r["status"] == "confirmed", r
    docs = pull(client, h)
    assert docs[("profiles", f"profile::{uid}")]["cart"] is None
    assert any(c == "requests" for c, _ in docs) and ("chat", f"chat::{uid}") in docs
    assert uid in client.get("/api/demo/reset").json()["default_users"]

    res = client.post("/api/demo/reset", json={}).json()
    assert res["state"] == "done"
    me = next(g for g in res["users"] if g["user_id"] == uid)
    assert me["profile"] == "reloaded" and me["requests"] >= 2 and "chat" in me["docs"]
    assert res["summary"]["profiles_reloaded"] >= 3        # the three personas at least
    assert res["inventory_restored"]

    docs = pull(client, h)
    p = docs[("profiles", f"profile::{uid}")]
    assert p["rev"] == 0 and p["returns"] == [] and len(p["orders"]) == 3
    assert [i["sku"] for i in p["cart"]["items"]] == ["MON-VST-27", "MON-ARM-DUO"]
    assert not any(c == "requests" for c, _ in docs)
    assert ("chat", f"chat::{uid}") not in docs and ("context_cache", f"ctx::{uid}::cart") not in docs
    assert ("activity", f"activity::{uid}") not in docs
    kinds = [c["kind"] for c in docs[("feed", f"feed::{uid}")]["cards"]]       # re-ranked from the restored profile
    assert "cart" in kinds and "return" in kinds
    assert client.get("/api/status").json()["metrics"]["assistant_turns"] == 0
