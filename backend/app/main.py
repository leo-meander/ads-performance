from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
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
    export,
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
    transcriptions,
    users,
)

app = FastAPI(
    title="Ads Automation Platform",
    description="Internal marketing automation for MEANDER Group",
    version="1.0.0",
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

# Routers
app.include_router(accounts.router, prefix="/api", tags=["accounts"])
app.include_router(campaigns.router, prefix="/api", tags=["campaigns"])
app.include_router(rules.router, prefix="/api", tags=["rules"])
app.include_router(creative.router, prefix="/api", tags=["creative"])
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


@app.get("/health")
def health_check():
    return {
        "success": True,
        "data": {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()},
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
