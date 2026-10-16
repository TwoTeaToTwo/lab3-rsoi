#!/usr/bin/env bash
set -euo pipefail

: "${BONUS_DB_PASSWORD:?BONUS_DB_PASSWORD must be set}"
export PGUSER="${PGUSER:-${POSTGRES_USER:-postgres}}"
export PGDATABASE="${PGDATABASE:-postgres}"

# Shared by first-volume initialization and the one-shot Compose init service.
# Do not recreate existing databases or change existing roles' passwords.
psql -v ON_ERROR_STOP=1 -v bonus_password="$BONUS_DB_PASSWORD" \
  -f /docker-entrypoint-initdb.d/scripts/bonus.sql

: "${TICKET_DB_PASSWORD:?TICKET_DB_PASSWORD must be set}"
psql -v ON_ERROR_STOP=1 -v ticket_password="$TICKET_DB_PASSWORD" \
  -f /docker-entrypoint-initdb.d/scripts/ticket.sql

: "${FLIGHT_DB_PASSWORD:?FLIGHT_DB_PASSWORD must be set}"
psql -v ON_ERROR_STOP=1 -v flight_password="$FLIGHT_DB_PASSWORD" \
  -f /docker-entrypoint-initdb.d/scripts/flight.sql
