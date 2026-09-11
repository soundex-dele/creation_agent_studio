#!/bin/sh
set -eu

case "$APP_DB_USER" in
  ''|*[!A-Za-z0-9_]*) echo "APP_DB_USER contains unsupported characters" >&2; exit 1 ;;
esac
case "$APP_DB_NAME" in
  ''|*[!A-Za-z0-9_]*) echo "APP_DB_NAME contains unsupported characters" >&2; exit 1 ;;
esac

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set=app_user="$APP_DB_USER" \
  --set=app_password="$APP_DB_PASSWORD" \
  --set=app_database="$APP_DB_NAME" <<'EOSQL'
CREATE ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_password';
CREATE DATABASE :"app_database" OWNER :"app_user";
EOSQL
