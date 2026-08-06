"""api/main.py's `_security_headers` middleware (Phase 8) -- applies to
every response regardless of route, so the plain `client` fixture (no
lifespan needed) is sufficient."""

from __future__ import annotations


def test_security_headers_present_on_every_response(client):
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_security_headers_present_on_a_404_too(client):
    # A middleware that only fires on the happy path would be a real gap
    # -- these headers matter most on responses an attacker actually
    # triggers.
    response = client.get("/not-a-real-route")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
