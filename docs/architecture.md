# Architecture & Design Decisions

## Platform Separation
Each ad platform has fundamentally different creative structures:
- **Meta**: Campaign → Ad Set → Ad (copy + material + CTA)
- **Google PMax**: Campaign → Asset Group (images[] + headlines[] + descriptions[])
- **Google Search**: Campaign → Ad Group → RSA (headlines[15] + descriptions[4])
- **TikTok**: Campaign → Ad Group → Ad (video + copy + CTA)

We formalize platform separation as an architectural principle:
- Each platform has its own client file (meta_client.py, google_client.py, tiktok_client.py)
- Never import one platform's logic into another
- Dashboard metrics are normalized, platform-specific metrics go in raw_data

## Parsing at Sync Time
Campaign/adset names encode metadata (TA, funnel stage, country).
We parse these at sync time and store as columns — never computed at query time.
This keeps dashboard queries fast and makes parsed data available for AI inputs.

## Budget Immutability
budget_allocations rows are NEVER updated — always INSERT with incremented version.
This provides full audit trail of allocation changes over time.

## API Key Security
API keys for the export endpoint:
- Generated as random 32-byte hex strings
- Only SHA-256 hash stored in database
- Plaintext returned once at creation, never again
- Key prefix (first 8 chars) stored for identification

## Technology Choices
- **PostgreSQL UUID** with String(36) fallback for SQLite dev compatibility
- **JSONB** for raw_data, conditions, metrics_snapshot (schema flexibility)
- **Celery + Redis** for background sync every 15 minutes
- **FastAPI StreamingResponse** for AI chat (text/event-stream)
- **Recharts** for dashboard visualizations
- **shadcn/ui** for consistent component library

## Risks & Mitigations
| Risk | Mitigation |
|------|-----------|
| Naming convention changes break parser | Re-parse endpoint + Unknown handling |
| Budget overspend not caught | Pace calculation runs on every dashboard load |
| API key leaked | SHA-256 hash only in DB, rate limiting, easy deactivation |
| Platform API rate limits | Exponential backoff in all client files |
