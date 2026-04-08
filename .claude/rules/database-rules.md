---
globs: ["backend/app/models/**", "backend/alembic/**"]
---

# Database Rules

- All tables: id (UUID default gen_random_uuid()), created_at, updated_at
- Use Alembic for ALL schema changes — never modify tables directly in Zeabur
- Foreign keys must specify ON DELETE behavior (CASCADE or SET NULL)
- Index all FK columns and all columns used in WHERE filters
- updated_at must use server_default + onupdate trigger
- action_logs table is IMMUTABLE — no UPDATE or DELETE ever
- Store raw API responses in JSONB raw_data columns for forward compatibility
