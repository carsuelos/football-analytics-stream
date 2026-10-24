# The dashboard: a static build served by nginx, which also proxies /api to
# the engine so the browser sees one origin. Build context: dashboard/.
FROM node:26-slim AS build
WORKDIR /app
RUN npm install --global --no-fund --no-audit pnpm@12.9.1
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.29-alpine
# The official image fills ${ENGINE_URL} into the template at start-up, and
# ${NGINX_LOCAL_RESOLVERS} with the nameservers in /etc/resolv.conf.
ENV ENGINE_URL=http://engine:8000 NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
