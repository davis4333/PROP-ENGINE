# ADR 0011 — Admin auth is a demo-only placeholder

**Status:** Decided (placeholder, not production-ready)

## Decision

`GET /api/admin/*` endpoints require a shared-secret header
(`X-Admin-Secret`, checked against `ADMIN_SHARED_SECRET`) for this build
only. This is explicitly **not** production authentication — the handbook
marks initial authentication as an unresolved product decision (anonymous
public / private admin vs. full accounts from day one). This placeholder
exists solely so the admin endpoints aren't wide open during local
development and demos, and must be replaced before any real deployment.
