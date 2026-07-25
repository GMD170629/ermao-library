#!/bin/bash
set -eu

: "${TRIM_PKGVAR:?TRIM_PKGVAR is not configured}"
: "${TRIM_APPDEST:?TRIM_APPDEST is not configured}"

mkdir -p \
  "$TRIM_PKGVAR/postgres" \
  "$TRIM_PKGVAR/storage/v2/covers" \
  "$TRIM_PKGVAR/storage/v2/conversions" \
  "$TRIM_PKGVAR/storage/v2/temp" \
  "$TRIM_PKGVAR/storage/v2/backups" \
  "$TRIM_PKGVAR/storage/v2/control" \
  "$TRIM_PKGVAR/storage/v2/logs" \
  "$TRIM_PKGVAR/storage/v2/secrets"

database_mode="${wizard_database_mode:-embedded}"
compose_env="$TRIM_APPDEST/docker/.env"
umask 077

case "$database_mode" in
  embedded)
    password_file="$TRIM_PKGVAR/storage/v2/secrets/postgres-password"
    if [[ ! -s "$password_file" ]]; then
      openssl rand -hex 32 > "$password_file"
    fi
    postgres_password="$(tr -d '\r\n' < "$password_file")"
    {
      printf 'POSTGRES_REPLICAS=1\n'
      printf 'POSTGRES_PASSWORD=%s\n' "$postgres_password"
      printf 'DATABASE_URL=postgresql+psycopg://shuku:%s@postgres:5432/shuku_v2\n' "$postgres_password"
    } > "$compose_env"
    ;;
  external)
    external_url="${wizard_external_database_url:-}"
    if [[ ! "$external_url" =~ ^postgresql(\+psycopg)?:// ]]; then
      echo "External DATABASE_URL must use PostgreSQL." >&2
      exit 1
    fi
    {
      printf 'POSTGRES_REPLICAS=0\n'
      printf 'POSTGRES_PASSWORD=external-database-unused\n'
      printf 'DATABASE_URL=%s\n' "$external_url"
    } > "$compose_env"
    ;;
  *)
    echo "Unsupported database mode: $database_mode" >&2
    exit 1
    ;;
esac

chmod 600 "$compose_env"
