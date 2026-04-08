---
globs: ["backend/app/routers/**", "backend/app/main.py"]
---

# API Conventions

- Every endpoint returns: { success: bool, data: any, error: str|null, timestamp: ISO8601 }
- Use FastAPI Depends() for database session injection
- All endpoints wrapped in try/except — return 500 with error message on failure
- Pagination: use limit/offset params (default limit=50, max=200)
- Date filters: use date_from / date_to query params (ISO8601 format)
- Platform filtering: platform query param on all campaign/metrics endpoints
- DELETE is always soft delete (is_active = False), never hard delete
- Streaming endpoints (AI chat): use FastAPI StreamingResponse with text/event-stream
