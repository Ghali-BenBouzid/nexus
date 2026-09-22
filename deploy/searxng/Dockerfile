# SearXNG with our settings baked in.
#
# JSON output is off in SearXNG's defaults and there is no environment variable
# for it: the only way to turn it on is settings.yml. Railway deploys either a
# public image or a repository, and a public image cannot be handed a file from
# our repo, so the file travels inside an image of our own.
#
# Railway: point a service at this repository with the root directory set to
# deploy/searxng, and set SEARXNG_SECRET. It needs no public domain.
FROM searxng/searxng:latest

COPY settings.yml /etc/searxng/settings.yml
