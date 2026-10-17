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

# Base de datos: sin MYSQL_*, Django caería en silencio a un SQLite DENTRO del
# contenedor y los datos se perderían en cada reinicio.
for var in MYSQL_DB MYSQL_USER MYSQL_PASSWORD MYSQL_HOST; do
    eval "valor=\${$var:-}"
    [ -n "$valor" ] || faltan="$faltan $var"
done

if [ -n "$faltan" ]; then
    echo "ERROR: faltan variables de entorno obligatorias:$faltan" >&2
    echo "Ver .env.docker.example (y deploy/DOCKER.md) para la lista completa." >&2
    exit 1
fi

# Valores de ejemplo: el .env.docker.example trae textos de relleno. Si alguien lo copia y se
# olvida de cambiar alguno, la app arrancaría "bien" pero con una clave o una contraseña
# que cualquiera puede leer en el repo. Mejor que no arranque.
ejemplos=""
case "$DJANGO_SECRET_KEY" in
    *generar-una-clave*|*cambiar*|django-insecure-*|solo-para-el-build) ejemplos="$ejemplos DJANGO_SECRET_KEY" ;;
esac
[ "${#DJANGO_SECRET_KEY}" -ge 40 ] || ejemplos="$ejemplos DJANGO_SECRET_KEY(muy corta: mínimo 40 caracteres)"
[ "$MYSQL_PASSWORD" != "cambiar" ] || ejemplos="$ejemplos MYSQL_PASSWORD"
[ "${DJANGO_SUPERUSER_PASSWORD:-}" != "cambiar" ] || ejemplos="$ejemplos DJANGO_SUPERUSER_PASSWORD"
if [ -n "$ejemplos" ]; then
    echo "ERROR: estas variables siguen con el valor de ejemplo (o son demasiado débiles):$ejemplos" >&2
    echo "Cambialas por valores propios en .env.docker (ver deploy/DOCKER.md)." >&2
    exit 1
fi

if [ "${DJANGO_DEBUG:-false}" = "true" ]; then
    echo "ADVERTENCIA: DJANGO_DEBUG=true; no usar así en producción." >&2
fi

# --- Correo ---------------------------------------------------------------
# No es obligatorio para arrancar, pero sin SMTP no salen invitaciones ni avisos y es fácil
# no darse cuenta: lo avisamos fuerte en el log de arranque.
case "${DJANGO_EMAIL_BACKEND:-}" in
    *smtp*)
        [ -n "${EMAIL_HOST:-}" ] || echo "ADVERTENCIA: DJANGO_EMAIL_BACKEND usa SMTP pero EMAIL_HOST está vacío; los mails van a fallar. Ver deploy/CORREO.md." >&2
        ;;
    *)
        echo "ADVERTENCIA: sin SMTP configurado (.env.mail); los mails NO se envían, solo se imprimen en el log. Ver deploy/CORREO.md." >&2
        ;;
esac

# --- Base de datos ----------------------------------------------------------
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py migrate --no-input
    python manage.py seed_catalogos
    python manage.py seed_modulos
    python manage.py ensure_superuser
fi

exec "$@"
