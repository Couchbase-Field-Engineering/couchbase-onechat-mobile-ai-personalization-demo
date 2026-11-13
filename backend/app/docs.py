"""Document ids, channel names and small shared helpers."""
from __future__ import annotations

import datetime as dt

from . import config

STATE = {"export_date": None}  # set by the loader


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> dt.date:
    """The demo's notion of 'today' - see config.DEMO_TODAY."""
    if config.DEMO_TODAY:
        return dt.date.fromisoformat(config.DEMO_TODAY)
    if STATE.get("export_date"):
        return dt.date.fromisoformat(STATE["export_date"])
    return dt.date.today()


def days_until(iso: str | None) -> int | None:
    if not iso:
        return None
    return (dt.date.fromisoformat(iso[:10]) - today()).days


def days_since(iso: str | None) -> int | None:
    d = days_until(iso)
    return None if d is None else -d


def nice_date(iso: str | None) -> str:
    """2026-11-15 -> 'Sun, Nov 15' (how the assistant says dates)."""
    if not iso:
        return ""
    d = dt.date.fromisoformat(iso[:10])
    return f"{d:%a}, {d:%b} {d.day}"


def user_channel(user_id: str) -> str:
    return f"user:{user_id}"


# Everyone signed in gets `catalog` (stores, products, the Help Center FAQ).
# Only team members get `employees` (the Team Handbook, IT and benefits
# reference data): Sync Gateway never replicates those documents to a
# customer's or prospect's phone.
CATALOG_CHANNEL = "catalog"
EMPLOYEE_CHANNEL = "employees"


def channels_for(audience: str, user_id: str) -> list[str]:
    out = [user_channel(user_id), CATALOG_CHANNEL]
    if audience == "employee":
        out.append(EMPLOYEE_CHANNEL)
    return out


def profile_id(u):
    return f"profile::{u}"


def feed_id(u):
    return f"feed::{u}"


def activity_id(u):
    return f"activity::{u}"


def chat_id(u):
    return f"chat::{u}"


def ctx_id(u, intent):
    return f"ctx::{u}::{intent}"


CATALOG_ID = "catalog::v1"
HANDBOOK_ID = "handbook::v1"
INVENTORY_ID = "inv::v1"


def money(x: float) -> str:
    return f"${x:,.0f}" if float(x).is_integer() else f"${x:,.2f}"
