# The judgekeeper website on Railway: the static site scripts/build_pages.py builds, served
# by Caddy. Built from the repository root: the Railway service has its Dockerfile path set to this file.
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS build
WORKDIR /src
COPY scripts/build_pages.py scripts/build_pages.py
COPY scripts/site_frame.py scripts/site_frame.py
COPY website website
COPY docs/examples docs/examples
RUN python scripts/build_pages.py website docs/examples /site

FROM caddy:2-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
COPY deploy/railway/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /site /srv
