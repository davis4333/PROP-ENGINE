FROM node:20-slim

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm run build

# API_BASE_URL is read by next.config.ts's rewrites() at server start (not
# baked into the client bundle) -- pass it as a runtime environment
# variable (docker-compose's `environment:`, a Replit Secret, etc.), not a
# build arg. See next.config.ts and lib/api.ts for why the Admin page's
# browser-side calls go through this same origin instead of needing their
# own separately-exposed port/env var.
EXPOSE 3000
CMD ["pnpm", "run", "start"]
