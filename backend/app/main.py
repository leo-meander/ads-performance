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
    country,
    creative,
    export,
    google_campaigns,
    google_recommendations,
    launch,
    meta_recommendations,
    notifications,
    rules,
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


@app.get("/health")
def health_check():
    return {
        "success": True,
        "data": {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()},
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
