#!/bin/sh
# ARMOR-SIMULATOR - the virtual bench: several simulated nodes delivering to a server in real time, round after round, until it is stopped.
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
#
# Everything it does is set by environment variables (the compose file of ARMOR-DEVOPS passes them from .env). The ingest token comes from ARMOR_INGEST_TOKEN or from
# the file named by ARMOR_SIM_TOKEN_FILE; it is never put on a command line. ARMOR_SIM_DRY_RUN=1 prints the commands it would run and runs none.
set -eu

fail() { echo "armor-bench: $1" >&2; exit 2; }
whole() { case "$2" in ''|*[!0-9]*) fail "$1 must be a whole number, not '$2'" ;; esac; }

NODES="${ARMOR_SIM_NODES:-3}"
PREFIX="${ARMOR_SIM_NODE_PREFIX:-bench}"
SCENARIO="${ARMOR_SIM_SCENARIO:-patrol}"
LIGHT="${ARMOR_SIM_LIGHT:-cycle}"
INTERVAL_MS="${ARMOR_SIM_INTERVAL_MS:-1000}"
ROUND_SAMPLES="${ARMOR_SIM_ROUND_SAMPLES:-60}"
ROUNDS="${ARMOR_SIM_ROUNDS:-0}"
SEED="${ARMOR_SIM_SEED:-1}"
URL="${ARMOR_SIM_SERVER_URL:-http://server:8080}"
FAULT="${ARMOR_SIM_FAULT:-none}"
RETRY_S="${ARMOR_SIM_RETRY_S:-5}"

whole ARMOR_SIM_NODES "$NODES"
whole ARMOR_SIM_INTERVAL_MS "$INTERVAL_MS"
whole ARMOR_SIM_ROUND_SAMPLES "$ROUND_SAMPLES"
whole ARMOR_SIM_ROUNDS "$ROUNDS"
whole ARMOR_SIM_SEED "$SEED"
whole ARMOR_SIM_RETRY_S "$RETRY_S"
[ "$NODES" -ge 1 ] && [ "$NODES" -le 8 ] || fail "ARMOR_SIM_NODES must be from 1 to 8"
[ "$ROUND_SAMPLES" -ge 1 ] && [ "$ROUND_SAMPLES" -le 10000 ] || fail "ARMOR_SIM_ROUND_SAMPLES must be from 1 to 10000"
case "$PREFIX" in ''|*[!a-z0-9-]*) fail "ARMOR_SIM_NODE_PREFIX may only hold a-z, 0-9 and -" ;; esac
[ "${#PREFIX}" -le 40 ] || fail "ARMOR_SIM_NODE_PREFIX is too long"
case "$URL" in http://*|https://*) ;; *) fail "ARMOR_SIM_SERVER_URL must be an http or https address" ;; esac

if [ -n "${ARMOR_SIM_TOKEN_FILE:-}" ]; then
  TOKEN_ARGS="--ingest-token-file $ARMOR_SIM_TOKEN_FILE"
elif [ -n "${ARMOR_INGEST_TOKEN:-}" ]; then
  TOKEN_ARGS=""
else
  fail "no ingest token: set ARMOR_INGEST_TOKEN or ARMOR_SIM_TOKEN_FILE"
fi

EXTRA=""
# A server that runs with ARMOR_INGEST_STRICT=1 wants the token derived for each node.
[ "${ARMOR_INGEST_STRICT:-}" = "1" ] && EXTRA="$EXTRA --per-node-token"
[ "${ARMOR_SIM_SOLAR:-}" = "1" ] && EXTRA="$EXTRA --solar"
[ "${ARMOR_SIM_ELECTRICAL:-}" = "1" ] && EXTRA="$EXTRA --electrical"
# A fault that breaks the contract on purpose needs the explicit permission of the owner.
[ "${ARMOR_SIM_ALLOW_INVALID:-}" = "1" ] && EXTRA="$EXTRA --allow-invalid"

run_node() {
  # shellcheck disable=SC2086
  set -- armor-simulator --node-id "$PREFIX-$1" --seed "$(( SEED + $1 ))" --scenario "$SCENARIO" --light "$LIGHT" --count "$ROUND_SAMPLES" \
    --interval-ms "$INTERVAL_MS" --start-ms now --fault "$FAULT" --server-url "$URL" $TOKEN_ARGS $EXTRA
  if [ "${ARMOR_SIM_DRY_RUN:-}" = "1" ]; then echo "$*"; return 0; fi
  "$@"
}

round=0
while :; do
  round=$(( round + 1 ))
  pids=""
  failed=0
  n=1
  while [ "$n" -le "$NODES" ]; do
    run_node "$n" &
    pids="$pids $!"
    n=$(( n + 1 ))
  done
  for pid in $pids; do wait "$pid" || failed=1; done
  [ "${ARMOR_SIM_DRY_RUN:-}" = "1" ] && [ "$round" -ge 1 ] && break
  if [ "$ROUNDS" -ne 0 ] && [ "$round" -ge "$ROUNDS" ]; then break; fi
  # The server may be restarting: say so, wait and go on with the next round instead of leaving the bench dead.
  [ "$failed" -eq 0 ] || { echo "armor-bench: a round failed (the server may be restarting); trying again in ${RETRY_S}s" >&2; sleep "$RETRY_S"; }
done
echo "armor-bench: done after $round round(s)"
