import type { NextConfig } from "next";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    "*.replit.dev",
    "*.spock.replit.dev",
  ],
  // Proxies the browser's client-side Admin-page requests (which can't
  // use API_BASE_URL directly -- it's server-only, never sent to the
  // browser) to the engine through this same origin. This means only one
  // port ever needs to be publicly exposed (this one) -- important for
  // single-port hosts like Replit, and avoids CORS entirely everywhere
  // else too. Server Components (Today/Ledger) still call the engine
  // directly via API_BASE_URL; this rewrite only serves the browser.
  // `/health` is proxied too, not just `/api/:path*` -- the Admin page's
  // client-side dev-mode-bypass probe (lib/api.ts's fetchHealth()) calls
  // it directly; without this it 404s against Next.js's own (nonexistent)
  // `/health` route in the real single-origin deployment topology, always
  // falling back to requiring a password even when the engine reports
  // auth isn't needed. Found by actually running both dev servers rather
  // than trusting the unit tests, which mock fetch and can't catch a
  // proxy config gap like this.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiBaseUrl}/api/:path*` },
      { source: "/health", destination: `${apiBaseUrl}/health` },
    ];
  },
  // Phase 8 security hardening -- this Next.js app, not the FastAPI
  // engine, is the one actually publicly reachable in the deployed
  // topology (the engine binds 127.0.0.1-only in Replit deployment mode;
  // see scripts/replit_start.sh), so response headers belong here.
  // Deliberately no Content-Security-Policy: Next.js's own inline
  // hydration script + this app's CSS Modules would need either
  // 'unsafe-inline'/nonces or a real CSP audit to add safely, and a
  // broken CSP silently blanking the page is worse than no CSP -- left
  // as a follow-up, not guessed at here.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // Admin/Today/Ledger must never be framed by another site --
          // no legitimate reason for this app to be embedded, and this
          // is real, zero-cost clickjacking protection.
          { key: "X-Frame-Options", value: "DENY" },
          // Stops a browser from trying to "helpfully" reinterpret a
          // response's declared Content-Type (e.g. treating a JSON
          // response as executable script).
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Don't leak this site's full URLs (which could include query
          // params) to a third-party link a user clicks from here.
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
