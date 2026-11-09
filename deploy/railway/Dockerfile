# The judgekeeper website on Railway: the static site scripts/build_pages.py builds, served
# by Caddy. Built from the repository root: the Railway service has its Dockerfile path set to this file.
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS build
WORKDIR /src
COPY scripts/build_pages.py scripts/build_pages.py
COPY scripts/site_frame.py scripts/site_frame.py
COPY website website
COPY docs/examples docs/examples
RUN python scripts/build_pages.py website docs/examples /site

FROM caddy:2-alpine@sha256:78bd35025c7ba85961dd149ae670315129954e77abe2383ac47c89106b35ade9
COPY deploy/railway/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /site /srv
