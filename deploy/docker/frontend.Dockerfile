# Build the browser bundle in a pinned Node image, then ship only static
# assets and the Nginx runtime to keep the public image small and immutable.
FROM node:22.13.0-bookworm-slim AS build

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /src/app
# Install the pinned package manager directly; the base image's Corepack
# keyring can lag behind pnpm release signatures on long-lived test hosts.
RUN npm install --global "pnpm@11.3.0" --registry="${NPM_REGISTRY}"
COPY app/package.json app/pnpm-lock.yaml app/pnpm-workspace.yaml /src/app/
RUN pnpm install --frozen-lockfile
COPY app /src/app
RUN pnpm run build

FROM nginx:1.29-alpine

# The Nginx config supplies SPA fallback, same-origin API proxying, and SSE
# buffering rules; keeping it in the image makes the whole stack portable.
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/app/dist /usr/share/nginx/html

EXPOSE 80 443

# The test deployment intentionally uses a self-signed IP certificate, so the
# in-container check bypasses trust validation while still proving HTTPS works.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD wget --spider --quiet --no-check-certificate https://127.0.0.1/ || exit 1
