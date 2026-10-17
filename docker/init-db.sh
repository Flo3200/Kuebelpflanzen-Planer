#!/usr/bin/env bash
# Runs once when the database volume is created: roles and database (see docs/DECISIONS.md, D2).
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE kp_owner LOGIN PASSWORD '${KP_OWNER_PASSWORD}' NOSUPERUSER BYPASSRLS;
CREATE ROLE kp_app LOGIN PASSWORD '${KP_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE kuebelplaner OWNER kp_owner;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname kuebelplaner <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO kp_owner;
GRANT USAGE ON SCHEMA public TO kp_app;
SQL
