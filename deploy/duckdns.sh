#!/bin/sh
# Keeps the DuckDNS name pointed at this server (docs/deploy.md, step 7). Runs from cron.
# Reads DUCKDNS_DOMAIN (the part before .duckdns.org) and DUCKDNS_TOKEN from ~/.duckdns.
# An empty ip= tells DuckDNS to use the address the request comes from.
set -eu
. "$HOME/.duckdns"
curl -fsS --max-time 30 \
  "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=" \
  > "$HOME/.duckdns.log"
