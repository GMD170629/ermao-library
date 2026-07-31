FROM node:22.23.1-alpine AS base
WORKDIR /app
RUN apk add --no-cache libc6-compat openssl \
  && corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --filter @shuku/web...

COPY . .
RUN pnpm --filter @shuku/web build

WORKDIR /app/apps/web

EXPOSE 3000
CMD ["pnpm", "start"]
