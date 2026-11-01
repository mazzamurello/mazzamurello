#!/bin/sh
# The initialization of the database contract (specs/contracts/database.md),
# run once by PostgreSQL's image when the data volume is empty (ADR-0054).
set -eu
: "${MZM_OWNER_PASSWORD:?MZM_OWNER_PASSWORD is required: run init first}"
: "${MZM_APP_PASSWORD:?MZM_APP_PASSWORD is required: run init first}"
psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set owner_password="$MZM_OWNER_PASSWORD" --set app_password="$MZM_APP_PASSWORD" <<'SQL'
CREATE ROLE mzm_owner LOGIN PASSWORD :'owner_password'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE mzm_app LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE DATABASE mazzamurello OWNER mzm_owner;
REVOKE ALL ON DATABASE mazzamurello FROM PUBLIC;
GRANT CONNECT ON DATABASE mazzamurello TO mzm_app;
SQL
