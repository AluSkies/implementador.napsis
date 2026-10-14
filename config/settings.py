"""
Django settings for the Portal de Implementación Napsis project.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

dotenv.load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"

# La clave firma las sesiones y los tokens: en producción es obligatoria. Antes caía a
# una clave escrita acá (y el repo es público), con lo cual cualquiera podría falsificar
# sesiones. Solo en desarrollo (DEBUG) y al correr los tests se tolera una de relleno.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or sys.argv[1:2] == ["test"]:
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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
if sys.argv[1:2] == ["test"]:
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

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "login"
LOGOUT_REDIRECT_URL = "login"


# Email
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "portal@napsislatam.com")

# Equipo de implementación que recibe la notificación al enviar un formulario
IMPLEMENTATION_TEAM_EMAILS = [
    e for e in os.environ.get("IMPLEMENTATION_TEAM_EMAILS", "").split(",") if e
]

# Google Apps Script Web App URL que appendea una fila al Sheet de seguimiento.
GOOGLE_SHEETS_WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "")

# Base pública del portal, usada para armar los links únicos de implementación.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://localhost:8000")

MAX_UPLOAD_SIZE_BYTES = 15 * 1024 * 1024  # 15MB por adjunto

# Por default, con DEBUG=False Django manda los errores 500 a mail_admins
# (que no configuramos) en vez de a la consola — quedan "mudos" en los logs
# de `docker logs`/journalctl. Esto asegura que el traceback real se vea ahí.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
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
