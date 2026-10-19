#!/usr/bin/env bash
#
# Refresca la base de STAGING con un espejo ANONIMIZADO de producción.
# Destino: /opt/boot-tracker-staging/refresh-staging-db.sh · Se corre como root, a mano.
#
#   1. pg_dump de la base de producción (solo lectura sobre prod)
#   2. frena backend y celery de staging
#   3. borra y recrea la base de staging, y restaura el dump
#   4. migrate (staging puede ir por delante de prod) + anonymize_for_staging
#   5. vacía el media de staging (los comprobantes reales nunca se copian)
#   6. levanta todo de nuevo
#
# Producción solo se LEE: el único comando que la toca es el pg_dump. El dump vive
# en un archivo temporal 600 y se borra al terminar, pase lo que pase.
#
# ⚠️ Si anonymize_for_staging falla, la base de staging queda con datos REALES. Por
#    eso el script deja backend/celery apagados en ese caso, y no los levanta hasta
#    que la anonimización termine bien.

set -euo pipefail

PROD_DB_CONTAINER=boottracker-db-1
PROD_ENV=/opt/boot-tracker/.env
STG_DIR=/opt/boot-tracker-staging
STG=(docker compose -p boottracker-staging
     -f "$STG_DIR/docker-compose.hetzner.yml"
     -f "$STG_DIR/docker-compose.staging.yml")

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# Lee una variable de un .env sin ejecutarlo (no hace `source` del .env de prod).
env_get() { grep -E "^$2=" "$1" | tail -1 | cut -d= -f2-; }

PROD_DB_NAME="$(env_get "$PROD_ENV" DB_NAME)"
PROD_DB_USER="$(env_get "$PROD_ENV" DB_USER)"
STG_DB_NAME="$(env_get "$STG_DIR/.env" DB_NAME)"
STG_DB_USER="$(env_get "$STG_DIR/.env" DB_USER)"

if [ -z "$STG_DB_NAME" ] || [ "$STG_DB_NAME" = "$PROD_DB_NAME" ]; then
    echo "ERROR: DB_NAME de staging ('$STG_DB_NAME') vacío o igual al de prod. Abortado." >&2
    exit 1
fi

DUMP="$(mktemp)"; chmod 600 "$DUMP"
trap 'rm -f "$DUMP"' EXIT

log "1/6 Dump de producción ($PROD_DB_NAME)..."
docker exec "$PROD_DB_CONTAINER" pg_dump -U "$PROD_DB_USER" -d "$PROD_DB_NAME" \
    --no-owner --no-privileges --format=custom > "$DUMP"
[ "$(stat -c%s "$DUMP")" -gt 1024 ] || { echo "ERROR: dump sospechosamente chico" >&2; exit 1; }

log "2/6 Frenando backend y celery de staging..."
"${STG[@]}" stop backend celery

log "3/6 Recreando $STG_DB_NAME y restaurando..."
"${STG[@]}" exec -T db dropdb -U "$STG_DB_USER" --if-exists --force "$STG_DB_NAME"
"${STG[@]}" exec -T db createdb -U "$STG_DB_USER" -O "$STG_DB_USER" "$STG_DB_NAME"
"${STG[@]}" exec -T db pg_restore -U "$STG_DB_USER" -d "$STG_DB_NAME" \
    --no-owner --no-privileges --role="$STG_DB_USER" < "$DUMP"

log "4/6 migrate + anonymize_for_staging..."
"${STG[@]}" run --rm --no-deps backend python manage.py migrate --noinput
if ! "${STG[@]}" run --rm --no-deps backend python manage.py anonymize_for_staging; then
    log "ERROR: la anonimización falló. backend y celery quedan APAGADOS a propósito:"
    log "       la base de staging tiene datos reales hasta que esto se corrija."
    exit 1
fi

log "5/6 Vaciando el media de staging..."
"${STG[@]}" run --rm --no-deps --user root --entrypoint sh backend \
    -c 'find /app/media -mindepth 1 -not -path "/app/media/staging*" -delete'

log "6/6 Levantando staging..."
"${STG[@]}" up -d
log "Listo. Staging tiene un espejo anonimizado de producción."
