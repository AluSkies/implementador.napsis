"""
Django settings for the Portal de Implementación Napsis project.
"""

import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

dotenv.load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
# `manage.py test`: algunas cosas se relajan solo ahí (hasher rápido, sin HTTPS forzado, etc.).
EJECUTANDO_TESTS = sys.argv[1:2] == ["test"]

# La clave firma las sesiones y los tokens: en producción es obligatoria. Antes caía a
# una clave escrita acá (y el repo es público), con lo cual cualquiera podría falsificar
# sesiones. Solo en desarrollo (DEBUG) y al correr los tests se tolera una de relleno.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or EJECUTANDO_TESTS:
        SECRET_KEY = "django-insecure-solo-desarrollo-y-tests"
    else:
        raise ImproperlyConfigured(
            "Falta la variable de entorno DJANGO_SECRET_KEY (obligatoria con DJANGO_DEBUG=false). "
            "Generá una con: python -c \"import secrets; print(secrets.token_urlsafe(50))\""
        )

ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [h for h in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if h]

# El proxy reverso termina TLS y reenvía la petición a Django por HTTP plano,
# indicando el esquema original en este header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- HTTPS obligatorio --------------------------------------------------------
# En producción la app exige HTTPS por sí misma, sin depender de que el proxy lo haga bien:
# redirige http -> https, marca las cookies de sesión y CSRF como Secure (nunca viajan en
# claro) y le dice al navegador que use siempre https (HSTS). Requiere que el proxy mande
# X-Forwarded-Proto (si no, la app cree que todo llega por http y entra en un bucle de
# redirecciones). DJANGO_FORCE_HTTPS=false lo apaga, solo para probar un arranque por http.
# HSTS arranca en 1 hora; cuando todo ande, subir SECURE_HSTS_SECONDS a 31536000 (1 año).
# Sin includeSubDomains: el dominio puede compartir zona con otros sitios.
# Vacío cuenta como "sin definir" (la plantilla del .env trae las variables en blanco): usa el default.
FORCE_HTTPS = (os.environ.get("DJANGO_FORCE_HTTPS") or ("false" if DEBUG else "true")).lower() == "true"
if FORCE_HTTPS and not EJECUTANDO_TESTS:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS") or 3600)
    SECURE_REDIRECT_EXEMPT = [r"^salud/$"]  # el chequeo de salud no debería redirigir


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "clients",
    "catalog",
    "onboarding",
    "employees",
    "notifications",
    "dashboard",
    "automatizacion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "automatizacion.correlacion.CorrelacionMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",  # siempre al final
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
# En producción se define MYSQL_DB (MySQL es el motor de Napsis) y se usa esa base.
# Sin esa variable cae a SQLite, que es lo que se usa en desarrollo y en los tests.
if os.environ.get("MYSQL_DB"):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ["MYSQL_DB"],
        "USER": os.environ.get("MYSQL_USER", "napsis"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
        "HOST": os.environ.get("MYSQL_HOST", "localhost"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }


# --- Límite de intentos de login (django-axes) --------------------------------
# Cubre /login/ y /admin/login/. 5 fallos seguidos con el mismo usuario desde la misma
# IP bloquean ESE par por 30 minutos; un ingreso correcto reinicia la cuenta. Se cuenta
# por (IP, usuario) y no por usuario solo para que alguien no pueda dejar afuera a un
# cliente ajeno mandando intentos con su nombre desde otra IP.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=30)
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "lockout.html"
AXES_CLIENT_IP_CALLABLE = "clients.security.ip_del_cliente"
# Cuántos proxies reverso propios hay delante de la app (ver clients/security.py). En
# producción siempre hay al menos uno; en desarrollo se corre sin proxy.
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0" if DEBUG else "1"))


# Al correr los tests se usa un hasher rápido. El de producción (PBKDF2, más de un millón de
# iteraciones) es lento A PROPÓSITO para frenar la fuerza bruta, pero cada test crea usuarios
# y se loguea: con él cada test tardaba ~2 s solo en hashear contraseñas.
if EJECUTANDO_TESTS:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Vigencia del link para crear o recuperar la contraseña (también el de la invitación).
PASSWORD_RESET_TIMEOUT = 7 * 24 * 60 * 60

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

if EJECUTANDO_TESTS:
    # El storage con manifest exige haber corrido collectstatic: en un checkout limpio (CI) los
    # tests fallaban con "Missing staticfiles manifest entry". Para los tests alcanza el común.
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# Caché compartida entre los workers de gunicorn (archivos en una carpeta temporal): la usan
# el límite de pedidos de recuperar contraseña y el filtro de las alertas de error. En los
# tests, en memoria. No guarda nada que importe: si se borra, solo se reinician los contadores.
if EJECUTANDO_TESTS:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": str(Path(tempfile.gettempdir()) / "napsis-cache"),
        }
    }

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "login"
LOGOUT_REDIRECT_URL = "login"


# Email
# Un valor vacío en el .env (como deja la plantilla) cuenta como "sin definir": usa el default.
EMAIL_BACKEND = os.environ.get("DJANGO_EMAIL_BACKEND") or "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT") or 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "false").lower() == "true"  # puerto 465 (no combinar con TLS)
# Sin timeout, un servidor SMTP que no responde dejaría colgado al worker de gunicorn.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT") or 10)  # vacío en el .env = default
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL") or "portal@napsislatam.com"

# Equipo de implementación que recibe la notificación al enviar un formulario
IMPLEMENTATION_TEAM_EMAILS = [
    e for e in os.environ.get("IMPLEMENTATION_TEAM_EMAILS", "").split(",") if e
]

# Aviso por mail cuando la app tiene un error 500 (ver notifications/alertas.py). APAGADO por
# defecto: por ahora los errores se guardan en el archivo de log (ver LOGGING). Se activa
# definiendo ERROR_ALERT_EMAILS (lista separada por comas); necesita el SMTP de .env.mail.
ERROR_ALERT_EMAILS = [e.strip() for e in os.environ.get("ERROR_ALERT_EMAILS", "").split(",") if e.strip()]

# Google Apps Script Web App URL que appendea una fila al Sheet de seguimiento.
GOOGLE_SHEETS_WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "")

# Base pública del portal, usada para armar los links únicos de implementación.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://localhost:8000")

MAX_UPLOAD_SIZE_BYTES = 15 * 1024 * 1024  # 15MB por adjunto

# Dónde se guarda el log de errores. En Docker es un volumen (napsis_logs) para que sobreviva a
# los redeploys; los logs por consola (`docker compose logs`) se pierden al recrear el contenedor.
LOG_DIR = Path(os.environ.get("LOG_DIR") or BASE_DIR / "logs")
LOG_ARCHIVO_ERRORES = LOG_DIR / "errores.log"
_log_a_archivo = not EJECUTANDO_TESTS
if _log_a_archivo:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:  # sistema de archivos de solo lectura: queda solo la consola
        _log_a_archivo = False

# Por default, con DEBUG=False Django manda los errores 500 a mail_admins
# (que no configuramos) en vez de a la consola: quedan "mudos". Esto asegura que el traceback
# se vea por consola y además quede guardado en errores.log (rota a los 5 MB, conserva 5 archivos).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "correlacion": {"()": "automatizacion.correlacion.CorrelacionFilter"},
    },
    "formatters": {
        "con_fecha": {"format": "%(asctime)s %(levelname)s [%(correlacion)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        # Aviso por mail de un 500 (con tope: uno cada 10 min por tipo de error). Solo hace algo
        # si ERROR_ALERT_EMAILS está definido.
        "alerta_mail": {"class": "notifications.alertas.AlertaErrorHandler", "level": "ERROR"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django.request": {
            "handlers": ["console", "alerta_mail"],
            "level": "ERROR",
            "propagate": False,
        },
        # Solo avisos: los bloqueos por exceso de intentos quedan en el log, pero no
        # cada login normal.
        "axes": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
if _log_a_archivo:
    # Errores de la app: los 500 (django.request) y todo lo que el código registra con
    # logger.exception/error (mails que fallan, etc.). Los avisos y el INFO no se guardan acá.
    LOGGING["handlers"]["errores_archivo"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(LOG_ARCHIVO_ERRORES),
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 5,
        "encoding": "utf-8",
        "delay": True,  # el archivo se crea con el primer error
        "level": "ERROR",
        "formatter": "con_fecha",
        "filters": ["correlacion"],
    }
    LOGGING["root"]["handlers"].append("errores_archivo")
    LOGGING["loggers"]["django.request"]["handlers"].append("errores_archivo")
