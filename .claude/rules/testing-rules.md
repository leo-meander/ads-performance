---
globs: ["backend/tests/**"]
---

# Testing Rules

- Run pytest after every service file creation
- Mock all external API calls (Meta, Google, TikTok) in tests
- Test rule engine with edge cases: zero spend, zero conversions, NULL metrics
- Test sync engine: verify upsert logic (existing campaign updated, new campaign inserted)
- All test files prefixed with test_
