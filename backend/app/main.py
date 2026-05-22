from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings


class UTF8JSONResponse(JSONResponse):
    """JSON response that declares charset=utf-8 in Content-Type.

    FastAPI's default JSONResponse already encodes the body as UTF-8 but labels
    it `application/json` with no charset. Strict clients (notably Windows
    PowerShell 5.1's Invoke-RestMethod) then fall back to Latin-1 and mojibake
    any non-ASCII text — e.g. Vietnamese hotel copy comes back as "BÃ¡nh mÃ¬".
    Declaring the charset fixes every client at once.
    """

    media_type = "application/json; charset=utf-8"
from app.mcp.router import router as mcp_router
from app.routers import (
    accounts,
    ad_research,
    ai,
    approvals,
    auth,
    booking_matches,
    budget,
    campaigns,
    changelog,
    country,
    creative,
    creative_intelligence,
    export,
    figma,
    funnel_recommendations,
    google_campaigns,
    google_recommendations,
    internal_tasks,
    landing_pages,
    launch,
    meta_recommendations,
    notifications,
    public_landing,
    rules,
    settings as settings_router,
    sync,
    tactics,
    transcriptions,
    users,
    winning_ads,
)

app = FastAPI(
    title="Ads Automation Platform",
    description="Internal marketing automation for MEANDER Group",
    version="1.0.0",
    default_response_class=UTF8JSONResponse,
)

# CORS
origins = ["http://localhost:3000", "http://localhost:3001"]
if settings.APP_ENV == "production":
    origins = [settings.FRONTEND_URL]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Permissive CORS for machine endpoints ────────────────────
#
# The Figma plugin runs in a null-origin sandbox, so its fetches carry
# `Origin: null` — which the credentialed CORSMiddleware above (scoped to the
# frontend domain) rejects. The /api/figma/plugin/* endpoints authenticate
# with X-API-Key (no cookies), so `Access-Control-Allow-Origin: *` is safe
# here — there are no credentials to leak. This middleware is registered AFTER
# CORSMiddleware so it sits OUTERMOST and can answer the preflight before
# CORSMiddleware sees it.

_PLUGIN_CORS_PREFIX = "/api/figma/plugin"
_PLUGIN_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "X-API-Key, Content-Type",
    "Access-Control-Max-Age": "86400",
}


@app.middleware("http")
async def plugin_cors_middleware(request: Request, call_next):
    is_plugin = request.url.path.startswith(_PLUGIN_CORS_PREFIX)
    if is_plugin and request.method == "OPTIONS":
        # Answer the preflight directly with permissive CORS.
        return Response(status_code=200, headers=_PLUGIN_CORS_HEADERS)
    response = await call_next(request)
    if is_plugin:
        for k, v in _PLUGIN_CORS_HEADERS.items():
            response.headers[k] = v
    return response


# Routers
app.include_router(accounts.router, prefix="/api", tags=["accounts"])
app.include_router(campaigns.router, prefix="/api", tags=["campaigns"])
app.include_router(rules.router, prefix="/api", tags=["rules"])
app.include_router(tactics.router, prefix="/api", tags=["tactics"])
app.include_router(creative.router, prefix="/api", tags=["creative"])
app.include_router(creative_intelligence.router, prefix="/api", tags=["creative-intelligence"])
app.include_router(figma.router, prefix="/api", tags=["figma"])
app.include_router(ai.router, prefix="/api", tags=["ai"])
app.include_router(sync.router, prefix="/api", tags=["sync"])
app.include_router(budget.router, prefix="/api", tags=["budget"])
app.include_router(country.router, prefix="/api", tags=["country"])
app.include_router(export.router, prefix="/api", tags=["export"])
app.include_router(funnel_recommendations.router, prefix="/api", tags=["funnel-recommendations"])
app.include_router(ad_research.router, prefix="/api", tags=["spy-ads"])
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(users.router, prefix="/api", tags=["users"])
app.include_router(approvals.router, prefix="/api", tags=["approvals"])
app.include_router(launch.router, prefix="/api", tags=["launch"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(google_campaigns.router, prefix="/api", tags=["google-ads"])
app.include_router(google_recommendations.router, prefix="/api", tags=["google-recommendations"])
app.include_router(meta_recommendations.router, prefix="/api", tags=["meta-recommendations"])
app.include_router(transcriptions.router, prefix="/api", tags=["transcriptions"])
app.include_router(booking_matches.router, prefix="/api", tags=["booking-matches"])
app.include_router(internal_tasks.router, prefix="/api", tags=["internal-tasks"])
app.include_router(settings_router.router, prefix="/api", tags=["settings"])
app.include_router(landing_pages.router, prefix="/api", tags=["landing-pages"])
app.include_router(public_landing.router, prefix="/api", tags=["public-landing"])
app.include_router(changelog.router, prefix="/api", tags=["changelog"])
app.include_router(winning_ads.router, prefix="/api", tags=["winning-ads"])

# MCP server — no /api prefix; OAuth and MCP paths must live at server root
app.include_router(mcp_router)


def _mcp_base(request: Request) -> str:
    if settings.MCP_BASE_URL:
        return settings.MCP_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


@app.get("/.well-known/oauth-authorization-server", tags=["mcp"])
def oauth_authorization_server_metadata(request: Request):
    base = _mcp_base(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@app.get("/.well-known/oauth-protected-resource", tags=["mcp"])
def oauth_protected_resource(request: Request):
    base = _mcp_base(request)
    return {"resource": base, "authorization_servers": [base]}


@app.get("/health")
def health_check():
    # Include the git SHA when the host (Zeabur/CI) sets one, so we can verify
    # which commit is actually serving without needing access to deploy logs.
    import os
    sha = (
        os.getenv("ZEABUR_GIT_COMMIT_SHA")
        or os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("VERCEL_GIT_COMMIT_SHA")
        or os.getenv("GIT_SHA")
        or "unknown"
    )
    return {
        "success": True,
        "data": {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_sha": sha,
        },
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
