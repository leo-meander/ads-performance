# Lessons Learned

_Updated as issues are discovered and resolved._

## Phase 5
- **Parse at sync, not query**: TA/funnel_stage/country must be stored on the row at upsert time. Computing at query time is too slow for dashboard aggregations.
- **Unknown is not an error**: If the parser can't extract a value, save 'Unknown' and log a warning. Never block sync for a parse failure.
- **Budget allocations are immutable**: INSERT new rows with incremented version — never UPDATE. This gives full audit trail.
- **API keys: hash only**: Store SHA-256 hash, return plaintext once. Key prefix (first 8 chars) for identification.
- **Platform separation**: Never share logic across platform client files. Metrics normalize at the dashboard level, not the data level.
