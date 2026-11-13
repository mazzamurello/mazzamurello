#!/bin/sh
# The initialization of the database contract (specs/contracts/database.md),
# run once by PostgreSQL's image when the data volume is empty (ADR-0054).
set -eu
: "${SIBILLO_OWNER_PASSWORD:?SIBILLO_OWNER_PASSWORD is required: run init first}"
: "${SIBILLO_APP_PASSWORD:?SIBILLO_APP_PASSWORD is required: run init first}"
psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set owner_password="$SIBILLO_OWNER_PASSWORD" --set app_password="$SIBILLO_APP_PASSWORD" <<'SQL'
CREATE ROLE sibillo_owner LOGIN PASSWORD :'owner_password'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE sibillo_app LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE DATABASE sibillo OWNER sibillo_owner;
REVOKE ALL ON DATABASE sibillo FROM PUBLIC;
GRANT CONNECT ON DATABASE sibillo TO sibillo_app;
SQL
