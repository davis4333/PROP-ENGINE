import type { NextConfig } from "next";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Proxies the browser's client-side Admin-page requests (which can't
  // use API_BASE_URL directly -- it's server-only, never sent to the
  // browser) to the engine through this same origin. This means only one
  // port ever needs to be publicly exposed (this one) -- important for
  // single-port hosts like Replit, and avoids CORS entirely everywhere
  // else too. Server Components (Today/Ledger) still call the engine
  // directly via API_BASE_URL; this rewrite only serves the browser.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiBaseUrl}/api/:path*` }];
  },
};

export default nextConfig;
