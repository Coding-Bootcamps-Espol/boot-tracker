#!/usr/bin/env bash
#
# Despliegue de boot-tracker en el VPS. El mismo script sirve a los dos entornos:
#   producción  →  /opt/boot-tracker/deploy.sh
#   staging     →  /opt/boot-tracker-staging/deploy.sh
# Dueño: deploy:deploy · Permisos: 750
#
# Lo que cambia entre entornos vive en un `deploy.conf` al lado del script (ver
# deploy/deploy.conf.staging.example). Sin ese archivo, los defaults son los de
# producción: así el script de /opt/boot-tracker funciona igual que antes.
#
# Lo invoca GitHub Actions por SSH. La llave está restringida en authorized_keys con
#     command="/opt/boot-tracker/deploy.sh",no-port-forwarding,no-agent-forwarding,no-pty
# (y una segunda llave con command="/opt/boot-tracker-staging/deploy.sh" para staging),
# así que el tag NO llega como argumento: llega en $SSH_ORIGINAL_COMMAND. Por eso se lee
# de ahí y se valida — es entrada remota y no se ejecuta sin verificar.
#
# ⚠️ En este servidor corren OTRAS aplicaciones en producción (attendance_*, cbe_staging_*,
#    dataijam). Todo comando lleva -p y -f explícitos para que nunca pueda alcanzarlas.
#    Prohibido `docker system prune -a` y `docker volume prune`.
#
# Imágenes privadas: el pipeline manda por STDIN dos líneas, usuario y token (el
# GITHUB_TOKEN de la corrida, que vence al terminar el job). Se usan para un
# `docker login` en un DOCKER_CONFIG temporal que se borra al salir: en el servidor
# no queda guardada ninguna credencial de GHCR.
#
# Uso manual (rollback):  <dir>/deploy.sh <sha-de-40-hex>
#   Sin token sólo puede usar imágenes que ya estén en el servidor (se conservan las
#   últimas $RETENER). Para un SHA más viejo, pasarle un token con read:packages:
#     printf '%s\n%s\n' <usuario> <token> | <dir>/deploy.sh <sha>

set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# compose resuelve rutas relativas al directorio actual: si se invoca desde un
# directorio que `deploy` no puede leer (p. ej. /root con sudo), falla con
# "stat .: permission denied".
cd "$DIR"

# --- Configuración por entorno (defaults = producción) ------------------------
PROJECT=boottracker
COMPOSE_FILES="docker-compose.hetzner.yml"
FLOATING_TAG=latest        # tag móvil que publica el CI para esta rama
GIT_REF=main               # rama de la que se baja el compose cuando se pide el tag móvil
FRONTEND_PORT=8080
# Contenedores ajenos que este deploy no debe reiniciar. Se compara su StartedAt.
WATCH="attendance_db cbe_staging_db"
IMAGE_BASE=ghcr.io/coding-bootcamps-espol/boot-tracker
REPO=Coding-Bootcamps-Espol/boot-tracker
# Se conservan las N imágenes más recientes de cada repo de GHCR. Producción y staging
# comparten repos, así que el número cubre a los dos: con 5 quedan al menos dos
# versiones de rollback para prod aunque staging despliegue seguido. `docker rmi` se
# niega a borrar las que están corriendo, en cualquiera de los dos entornos.
RETENER=5

# shellcheck disable=SC1091
[ -f "$DIR/deploy.conf" ] && source "$DIR/deploy.conf"

COMPOSE=(docker compose -p "$PROJECT")
for f in $COMPOSE_FILES; do COMPOSE+=(-f "$DIR/$f"); done

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# --- 1. Tag: de SSH_ORIGINAL_COMMAND (remoto) o de $1 (manual) --------------
TAG="${SSH_ORIGINAL_COMMAND:-${1:-$FLOATING_TAG}}"
TAG="${TAG%%[[:space:]]*}"     # por si llega con argumentos extra

if [[ ! "$TAG" =~ ^[0-9a-f]{40}$ && "$TAG" != "$FLOATING_TAG" ]]; then
    echo "ERROR: tag invalido: '${TAG}'" >&2
    echo "       Se espera un SHA de git (40 hex) o '${FLOATING_TAG}'." >&2
    exit 2
fi
export IMAGE_TAG="$TAG"
log "[$PROJECT] Desplegando tag: $IMAGE_TAG"

# --- 1b. Credencial efímera de GHCR (opcional, por stdin) ---------------------
GHCR_USER=""; GHCR_TOKEN=""
if [ ! -t 0 ]; then
    IFS= read -r -t 5 GHCR_USER || true
    IFS= read -r -t 5 GHCR_TOKEN || true
fi
PULL_FLAGS=()
if [ -n "$GHCR_TOKEN" ]; then
    DOCKER_CONFIG="$(mktemp -d)"; export DOCKER_CONFIG
    trap 'rm -rf "$DOCKER_CONFIG"' EXIT
    printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:-x}" --password-stdin >/dev/null
    log "Login efímero en GHCR OK"
else
    # Sin credencial no se pueden bajar imágenes privadas: se sigue con las que ya
    # están en el servidor. Si el tag no está en caché, el `up` de abajo falla.
    PULL_FLAGS=(--ignore-pull-failures)
    log "Sin token de GHCR: se usan las imágenes que ya están en el servidor"
fi

# --- 2. Estado de las OTRAS apps, ANTES ---------------------------------------
# Se usan las bases y no las APIs a proposito: sus equipos redespliegan las APIs a
# mano, asi que el StartedAt de una API da falsos positivos. Una base solo se
# reinicia si algo la toco de verdad.
estado_ajeno() {
    for c in $WATCH; do
        printf '%s=%s\n' "$c" "$(docker inspect "$c" --format '{{.State.StartedAt}}' 2>/dev/null || echo ausente)"
    done
}
OTRAS_ANTES="$(estado_ajeno)"

# --- 3. Sincronizar los compose con el commit que se despliega ----------------
# Los compose viven en git, no en la imagen: sin este paso, un cambio como el de
# CB-316 (agregar el servicio media-permissions) queda mergeado pero nunca llega
# al VPS, porque up -d sólo lee el archivo que ya está en disco. Se bajan del mismo
# SHA que las imagenes para que nunca queden desincronizados. El tag móvil no es un
# ref de git: para ese caso se baja de la rama a la que apunta ($GIT_REF).
COMPOSE_REF="$IMAGE_TAG"
[ "$COMPOSE_REF" = "$FLOATING_TAG" ] && COMPOSE_REF="$GIT_REF"
for f in $COMPOSE_FILES; do
    log "Sincronizando $f (${COMPOSE_REF})..."
    TMP="$(mktemp)"
    if curl -fsSL --max-time 15 "https://raw.githubusercontent.com/${REPO}/${COMPOSE_REF}/${f}" -o "$TMP" && [ -s "$TMP" ]; then
        [ -f "$DIR/$f" ] && cp "$DIR/$f" "$DIR/${f}.bak-$(date +%Y%m%d%H%M%S)"
        mv "$TMP" "$DIR/$f"
        # Se conservan los 3 respaldos más recientes; antes se acumulaban uno por deploy.
        ls -1t "$DIR/${f}".bak-* 2>/dev/null | tail -n +4 | xargs -r rm -f
    else
        log "ERROR: no se pudo bajar $f de GitHub. Se sigue con el que ya está en el servidor."
        rm -f "$TMP"
    fi
done

# --- 4. Traer imagenes ------------------------------------------------------
log "Bajando imagenes de GHCR..."
"${COMPOSE[@]}" pull "${PULL_FLAGS[@]}"

# --- 5. Levantar ------------------------------------------------------------
log "Levantando servicios..."
"${COMPOSE[@]}" up -d --remove-orphans

# --- 6. Esperar a que el frontend responda ----------------------------------
log "Esperando al frontend en 127.0.0.1:${FRONTEND_PORT}..."
ok=0
for i in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:${FRONTEND_PORT}/" 2>/dev/null; then
        ok=1; log "Frontend OK tras ${i}0s"; break
    fi
    sleep 10
done
if [ "$ok" -ne 1 ]; then
    log "ERROR: el frontend no respondio en 5 minutos."
    log "Ultimos logs del backend:"
    "${COMPOSE[@]}" logs --tail 40 backend || true
    log "Para volver atras:  $0 <sha-anterior>"
    exit 1
fi

# --- 7. Limpiar imagenes viejas SOLO de boot-tracker -------------------------
# NO se usa `docker image prune`: sin `-a` solo borra imagenes *dangling* (sin tag),
# y las de boot-tracker SIEMPRE llevan su tag de SHA. Por eso nunca borro nada y el
# disco paso de 16% a 62% en cinco dias.
#
# Tampoco se usa `prune -a --filter label=...`: borraria de golpe todo lo que no
# este corriendo, dejando cero margen de rollback.
#
# La barrera aca es el nombre de repo EXPLICITO en el bucle: ninguna imagen de las
# otras apps del host coincide con esos dos strings. Ademas `docker rmi` se niega a
# borrar una imagen con un contenedor corriendo.
log "Limpiando imagenes viejas (se conservan las $RETENER mas recientes por repo)..."
for repo in "${IMAGE_BASE}-backend" "${IMAGE_BASE}-frontend"; do
    docker images "$repo" --format '{{.CreatedAt}}\t{{.ID}}' \
        | sort -r \
        | tail -n +$((RETENER + 1)) \
        | cut -f2 \
        | xargs -r -n1 docker rmi >/dev/null 2>&1 || true
done

# --- 8. Verificar que las otras apps quedaron intactas -----------------------
OTRAS_DESPUES="$(estado_ajeno)"
if [ "$OTRAS_ANTES" != "$OTRAS_DESPUES" ]; then
    log "⚠️  ATENCION: una base ajena se reinicio durante el despliegue."
    diff <(echo "$OTRAS_ANTES") <(echo "$OTRAS_DESPUES") || true
    log "    Revisar con: journalctl -u docker --since '10 min ago'"
else
    log "Apps ajenas intactas ✅ ($WATCH)"
fi

log "Despliegue completo: $IMAGE_TAG"
"${COMPOSE[@]}" ps --format 'table {{.Name}}\t{{.Status}}'
