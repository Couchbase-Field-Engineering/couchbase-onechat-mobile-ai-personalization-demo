"""Runtime configuration, all from environment variables (see .env.example)."""
import os


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# --- storage -----------------------------------------------------------------
# "couchbase" for the full stack, "memory" for a no-dependency local run.
STORE_DRIVER = os.getenv("STORE_DRIVER", "memory")
COUCHBASE_CONN = os.getenv("COUCHBASE_CONN", "couchbase://couchbase")
COUCHBASE_USERNAME = os.getenv("COUCHBASE_USERNAME", "Administrator")
COUCHBASE_PASSWORD = os.getenv("COUCHBASE_PASSWORD", "password123")
COUCHBASE_BUCKET = os.getenv("COUCHBASE_BUCKET", "onechat")
COUCHBASE_SCOPE = os.getenv("COUCHBASE_SCOPE", "oc")

# --- the nightly export -----------------------------------------------------------
# People come from Larkfield's systems of record (datagen/README.md):
#  1. the nightly export, landing as exportTime=YYYYMMDD/ partitions here;
EXPORT_DIR = os.getenv("EXPORT_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data", "onechat-export"))
# How often the backend checks the landing folder for a newer partition.
EXPORT_POLL_SECONDS = int(os.getenv("EXPORT_POLL_SECONDS", "600"))
#  2. a live lookup against the system of record (CDP/CRM for customers and
#     prospects, HRIS for team members) when the assistant builds context.
#     Blank URL = mock mode (answers from the exported profile with a realistic
#     latency).
SOR_PROFILE_API_URL = os.getenv("SOR_PROFILE_API_URL", "").rstrip("/")
SOR_API_TOKEN = os.getenv("SOR_API_TOKEN", "")
SOR_TIMEOUT_SECONDS = float(os.getenv("SOR_TIMEOUT_SECONDS", "8"))
SOR_MOCK_LATENCY_MS = tuple(int(x) for x in os.getenv("SOR_MOCK_LATENCY_MS", "120,350").split(","))
# The Help Center and Team Handbook are authored in a CMS. Blank = the bundled
# entries in knowledge.py.
CMS_KB_ENDPOINT = os.getenv("CMS_KB_ENDPOINT", "").rstrip("/")
CMS_TOKEN = os.getenv("CMS_TOKEN", "")
# Memory driver only: keep at most this many people (personas always kept).
MEMORY_MAX_PROFILES = int(os.getenv("MEMORY_MAX_PROFILES", "6000"))
# "Today" for the demo. Empty = the export_date of the loaded export, so the
# story (delivery in 2 days, enrollment closes in 24) stays the same whenever it's run.
DEMO_TODAY = os.getenv("DEMO_TODAY", "")

# --- Knowledge Base publishing -------------------------------------------------
KB_ENABLED = _bool("KB_ENABLED", True)
KB_PROFILE_LIMIT = int(os.getenv("KB_PROFILE_LIMIT", "150"))
KB_ALLOWED_ROLES = [r.strip() for r in os.getenv("KB_ALLOWED_ROLES", "support_agent,admin").split(",") if r.strip()]

# --- Couchbase Agent Operations Manager ------------------------------------------
AOM_URL = os.getenv("AOM_URL", "").rstrip("/")
AOM_AGENT_API_KEY = os.getenv("AOM_AGENT_API_KEY", "")
# Second agent identity: the Returns Agent (returns_agent.py). Issued by
# register_with_aom.py / aom_bootstrap.py alongside the assistant; blank = returns
# run as the assistant.
AOM_RETURNS_AGENT_API_KEY = os.getenv("AOM_RETURNS_AGENT_API_KEY", "")
AOM_ADMIN_USERNAME = os.getenv("AOM_ADMIN_USERNAME", "admin")
AOM_ADMIN_PASSWORD = os.getenv("AOM_ADMIN_PASSWORD", "")
AOM_VERIFY_TLS = _bool("AOM_VERIFY_TLS", False)
# Register with AOM on startup (MCP server, agent identity, approval tier, RAG
# app) instead of running scripts/register_with_aom.py - see aom_bootstrap.py.
# Needs AOM_URL and AOM_ADMIN_PASSWORD; used by the Helm chart.
AOM_AUTO_REGISTER = _bool("AOM_AUTO_REGISTER", False)
# The AOM dashboard as a browser reaches it - linked from the story page.
AOM_DASHBOARD_URL = os.getenv("AOM_DASHBOARD_URL", "")
AOM_TIMEOUT_SECONDS = float(os.getenv("AOM_TIMEOUT_SECONDS", "20"))
AOM_LLM_PROVIDER = os.getenv("AOM_LLM_PROVIDER", "") or None
AOM_LLM_MODEL = os.getenv("AOM_LLM_MODEL", "") or None
AOM_MCP_SERVER_ID = os.getenv("AOM_MCP_SERVER_ID", "onechat-services")
# The URL AOM (in its own compose stack) uses to reach this backend's MCP server.
AOM_MCP_PUBLIC_URL = os.getenv("AOM_MCP_PUBLIC_URL", "http://host.docker.internal:8202/oc/mcp")
# OneChat is registered in AOM as two RAG Applications, one per knowledge
# audience: the customer-facing app is scoped to the Help Center document, the
# workplace app to the Team Handbook. A customer's question can therefore
# never retrieve an HR policy. AOM attributes cache activity to an app by
# namespace prefix `rag:<app_id>:`, so every namespace the assistant uses (its
# own context cache and LLM calls as well as the app's /query endpoint)
# carries that prefix and shows up on AOM's RAG Applications page.
RAG_APP_ID = os.getenv("RAG_APP_ID", "onechat-assistant")
RAG_APP_ID_WORKPLACE = os.getenv("RAG_APP_ID_WORKPLACE", "onechat-workplace")
RAG_APP_ENABLED = os.getenv("RAG_APP_ENABLED", "true").lower() == "true"


def llm_namespace(app_id: str, personal: bool) -> str:
    return f"rag:{app_id}:{'personal' if personal else 'playbook'}"


def context_namespace(app_id: str) -> str:
    return f"rag:{app_id}:user-context"


# --- Context cache -----------------------------------------------------------------
CONTEXT_CACHE_TTL_SECONDS = int(os.getenv("CONTEXT_CACHE_TTL_SECONDS", str(6 * 3600)))

# --- Sync Gateway (for Couchbase Lite replication) -----------------------------------
SG_ADMIN_URL = os.getenv("SG_ADMIN_URL", "").rstrip("/")  # e.g. http://sync-gateway:4985
SG_ADMIN_USERNAME = os.getenv("SG_ADMIN_USERNAME", "Administrator")
SG_ADMIN_PASSWORD = os.getenv("SG_ADMIN_PASSWORD", "password123")
SG_DB = os.getenv("SG_DB", "onechat")
# What the phone dials. Defaults to blank: the app falls back to EXPO_PUBLIC_SG_URL.
SG_PUBLIC_URL = os.getenv("SG_PUBLIC_URL", "")
SG_SESSION_TTL_SECONDS = int(os.getenv("SG_SESSION_TTL_SECONDS", str(24 * 3600)))

# --- app --------------------------------------------------------------------------------
APP_SECRET = os.getenv("APP_SECRET", "onechat-demo-dev-secret-change-me")
# The app renews its token on every launch (/api/auth/refresh), so this is idle time.
APP_TOKEN_TTL_SECONDS = int(os.getenv("APP_TOKEN_TTL_SECONDS", str(30 * 24 * 3600)))
REQUEST_POLL_SECONDS = float(os.getenv("REQUEST_POLL_SECONDS", "2"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
