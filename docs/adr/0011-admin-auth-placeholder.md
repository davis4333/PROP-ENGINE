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

Further hardened: `config.py`'s `admin_secret_is_weak()` +
`is_production_environment()`, wired into `api/main.py`'s startup
(`lifespan`), now make a real deployment (Replit's own `REPLIT_DEPLOYMENT`
env var, or `PRODUCTION_MODE=true` elsewhere) **refuse to start at all**
if `ADMIN_SHARED_SECRET` is missing, a known placeholder value (`test`,
`change-me-dev-only`, etc.), or under 16 characters. This closes the gap
where the exact `test` value used for live verification during this
build could otherwise have shipped as the real production secret — see
the deploy runbook / `CURRENT_STATE_AUDIT.md` for the exact rotation
requirement before deploying this check.

## Decision

`GET /api/admin/*` endpoints require a shared-secret header
(`X-Admin-Secret`, checked against `ADMIN_SHARED_SECRET`) for this build
only. This is explicitly **not** production authentication — the handbook
marks initial authentication as an unresolved product decision (anonymous
public / private admin vs. full accounts from day one). This placeholder
exists solely so the admin endpoints aren't wide open during local
development and demos, and must be replaced before any real deployment.
