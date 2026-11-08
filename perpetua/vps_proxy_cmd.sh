#!/bin/bash
# ProxyCommand wrapper: SSH to VPS via the authenticated runtime egress proxy.
# Usage: vps_proxy_cmd.sh <host> <port>
# Credentials are read at runtime from https_proxy/HTTPS_PROXY env (injected
# by the runtime); no secret is stored in this file or on any command line.
# Background: the unauthenticated nc path via 198.19.0.1:3128 stopped reaching
# 192.166.82.123:22 on 2026-11-08 ~20:49 UTC ("proxy read: Broken pipe"),
# while an authenticated CONNECT through hatch-egress-proxy:3128 returns 200.
host="$1"
port="$2"
proxy_url="${https_proxy:-$HTTPS_PROXY}"
auth="${proxy_url#*://}"
auth="${auth%%@*}"
case "$auth" in
    *:*)
        exec socat - "PROXY:hatch-egress-proxy:${host}:${port},proxyport=3128,proxyauth=${auth}"
        ;;
    *)
        exec socat - "PROXY:hatch-egress-proxy:${host}:${port},proxyport=3128"
        ;;
esac
