#!/bin/sh
# Kurtosis snooper launcher calls: ./json_rpc_snoop -b=BIND -p=PORT UPSTREAM_URL
# This wrapper drops the binary name and normalises -b=val / -p=val for argparse.

shift  # drop ./json_rpc_snoop

BIND="0.0.0.0"
PORT="8561"
UPSTREAM=""

while [ $# -gt 0 ]; do
    case "$1" in
        -b=*) BIND="${1#-b=}" ;;
        -p=*) PORT="${1#-p=}" ;;
        -b)   BIND="$2"; shift ;;
        -p)   PORT="$2"; shift ;;
        *)    UPSTREAM="$1" ;;
    esac
    shift
done

exec python3 /proxy.py -b "$BIND" -p "$PORT" "$UPSTREAM"
