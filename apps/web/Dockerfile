FROM node:22.23.1-alpine AS base
WORKDIR /app
RUN apk add --no-cache libc6-compat openssl \
  && corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json ./
COPY apps/web/package.json apps/web/package.json
COPY third_party/foliate-js third_party/foliate-js
RUN test -f third_party/foliate-js/package.json \
  && test -f third_party/foliate-js/view.js \
  || (echo "foliate-js submodule is not initialized; run: git submodule update --init --recursive" >&2; exit 1)
RUN pnpm install --frozen-lockfile --filter @shuku/web...

COPY . .
RUN pnpm --filter @shuku/web build

WORKDIR /app/apps/web

EXPOSE 3000
CMD ["pnpm", "start"]
