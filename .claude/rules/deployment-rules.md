---
globs: ["Dockerfile", "docker-compose*.yml", "zeabur.json", ".env*", "backend/app/config.py"]
---

# Deployment Rules

- Never commit .env — use .env.example as template
- All env vars loaded through config.py (Pydantic BaseSettings) — never os.getenv() inline
- Zeabur private networking: use service names as hostnames (e.g. redis, postgresql)
- GET /health must always return 200 with { status: 'ok', timestamp: ISO8601 }
- CORS: restrict to frontend domain in production (not *)
- Celery broker URL: redis://redis:6379/0 (uses Zeabur private network)
- PostgreSQL: use POSTGRES_CONNECTION_STRING env var injected by Zeabur
