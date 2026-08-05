# ADR 0011 — Admin auth is a demo-only placeholder

**Status:** Decided (placeholder, not production-ready). This ADR's own
stated trigger — "must be replaced before any real deployment" — has now
been met: the admin routes are genuinely publicly reachable on a live
Reserved VM Deployment (see ADR 0015). Hardened, not replaced, after a
live security review (`hmac.compare_digest` instead of `!=`; a basic
failed-attempt lockout, since there was previously no rate limiting at
all) — see `CURRENT_STATE_AUDIT.md`'s Provisional section. The decision
this ADR records (placeholder, not real auth) is unchanged; real
authentication is still unbuilt.

## Decision

`GET /api/admin/*` endpoints require a shared-secret header
(`X-Admin-Secret`, checked against `ADMIN_SHARED_SECRET`) for this build
only. This is explicitly **not** production authentication — the handbook
marks initial authentication as an unresolved product decision (anonymous
public / private admin vs. full accounts from day one). This placeholder
exists solely so the admin endpoints aren't wide open during local
development and demos, and must be replaced before any real deployment.
