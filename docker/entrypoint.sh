#!/bin/sh
# Valida la configuración, prepara la base y después ejecuta el comando del contenedor.
# Los pasos de base son idempotentes (si ya está todo aplicado no hacen nada).
# Con varias réplicas conviene RUN_MIGRATIONS=0 en todas y correr los pasos de base
# una sola vez como job aparte; con una sola instancia, el default (1) alcanza.
set -e

# --- Variables obligatorias -------------------------------------------------
# Sin estas, o la app no funciona (400/403 en el dominio real) o, peor, arranca
# "bien" pero insegura o guardando los datos donde no corresponde (ver abajo).
faltan=""
for var in DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS DJANGO_CSRF_TRUSTED_ORIGINS SITE_BASE_URL; do
    eval "valor=\${$var:-}"
    [ -n "$valor" ] || faltan="$faltan $var"
done

# Base de datos: sin ninguna, Django caería en silencio a un SQLite DENTRO del
# contenedor y los datos se perderían en cada reinicio.
if [ -n "${MYSQL_DB:-}" ]; then
    for var in MYSQL_USER MYSQL_PASSWORD MYSQL_HOST; do
        eval "valor=\${$var:-}"
        [ -n "$valor" ] || faltan="$faltan $var"
    done
elif [ -z "${DATABASE_URL:-}" ] && [ -z "${POSTGRES_DB:-}" ]; then
    faltan="$faltan MYSQL_DB MYSQL_USER MYSQL_PASSWORD MYSQL_HOST"
fi

if [ -n "$faltan" ]; then
    echo "ERROR: faltan variables de entorno obligatorias:$faltan" >&2
    echo "Ver .env.docker.example (y deploy/DOCKER.md) para la lista completa." >&2
    exit 1
fi

if [ "${DJANGO_DEBUG:-false}" = "true" ]; then
    echo "ADVERTENCIA: DJANGO_DEBUG=true; no usar así en producción." >&2
fi

# --- Base de datos ----------------------------------------------------------
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py migrate --no-input
    python manage.py seed_catalogos
    python manage.py seed_modulos
    python manage.py ensure_superuser
fi

exec "$@"
