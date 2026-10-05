# The judgekeeper website on Railway: the static site scripts/build_pages.py builds, served
# by Caddy. Built from the repository root: the Railway service has its Dockerfile path set to this file.
FROM python:3.12-slim AS build
WORKDIR /src
COPY scripts/build_pages.py scripts/build_pages.py
COPY website website
COPY docs/examples docs/examples
RUN python scripts/build_pages.py website docs/examples /site

FROM caddy:2-alpine
COPY deploy/railway/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /site /srv
