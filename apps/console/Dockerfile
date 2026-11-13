FROM node:22-alpine AS build

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/console/package.json apps/console/package.json

RUN pnpm install --frozen-lockfile --filter @cairn/console

COPY apps/console apps/console

RUN pnpm --filter @cairn/console run build

FROM nginx:1.29-alpine

RUN apk update && apk upgrade --no-cache

COPY apps/console/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/console/dist /usr/share/nginx/html

EXPOSE 8080
