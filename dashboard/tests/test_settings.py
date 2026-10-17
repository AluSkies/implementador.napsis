import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parents[2]


def _importar_settings(**entorno):
    """Importa config.settings en un proceso aparte con ese entorno (las variables
    seteadas, aun vacías, pisan lo que cargaría un .env local)."""
    env = {**os.environ, **entorno}
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=BASE_DIR, env=env, capture_output=True, text=True,
    )


class SecretKeyObligatoriaTests(SimpleTestCase):
    """Sin esto la app arrancaba con una clave escrita en el repo (público): cualquiera
    podría falsificar sesiones. En producción tiene que fallar fuerte al arrancar."""

    def test_sin_clave_y_sin_debug_no_arranca(self):
        resultado = _importar_settings(DJANGO_SECRET_KEY="", DJANGO_DEBUG="false")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", resultado.stderr)

    def test_con_clave_arranca(self):
        resultado = _importar_settings(DJANGO_SECRET_KEY="una-clave-cualquiera", DJANGO_DEBUG="false")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_en_desarrollo_se_tolera_sin_clave(self):
        resultado = _importar_settings(DJANGO_SECRET_KEY="", DJANGO_DEBUG="true")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)


class HasherRapidoSoloEnTestsTests(SimpleTestCase):
    """El hasher rápido (MD5) acelera los tests, pero fuera de ellos las contraseñas tienen que
    seguir usando el de Django (PBKDF2), que es lento a propósito para frenar la fuerza bruta."""

    def test_fuera_de_los_tests_no_se_usa_el_hasher_rapido(self):
        resultado = subprocess.run(
            [sys.executable, "-c", "import config.settings as s; print(getattr(s, 'PASSWORD_HASHERS', 'por-defecto'))"],
            cwd=BASE_DIR, env={**os.environ, "DJANGO_SECRET_KEY": "x", "DJANGO_DEBUG": "false"},
            capture_output=True, text=True,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(resultado.stdout.strip(), "por-defecto")

    def test_durante_los_tests_si_se_usa(self):
        from django.conf import settings

        self.assertEqual(settings.PASSWORD_HASHERS, ["django.contrib.auth.hashers.MD5PasswordHasher"])


class CorreoTests(SimpleTestCase):
    """El SMTP se configura por entorno (archivo .env.mail en el deploy). Un servidor que no
    responde no puede dejar colgado al worker: siempre hay timeout."""

    def _leer(self, **entorno):
        env = {**os.environ, "DJANGO_SECRET_KEY": "una-clave-cualquiera", "DJANGO_DEBUG": "false", **entorno}
        salida = subprocess.run(
            [sys.executable, "-c",
             "import config.settings as s; print('|'.join(map(str, [s.EMAIL_BACKEND, s.EMAIL_HOST, s.EMAIL_PORT, "
             "s.EMAIL_USE_TLS, s.EMAIL_USE_SSL, s.EMAIL_TIMEOUT, s.DEFAULT_FROM_EMAIL])))"],
            cwd=BASE_DIR, env=env, capture_output=True, text=True,
        )
        self.assertEqual(salida.returncode, 0, salida.stderr)
        return salida.stdout.strip().split("|")

    def test_sin_configurar_usa_consola_y_tiene_timeout(self):
        valores = self._leer(DJANGO_EMAIL_BACKEND="", EMAIL_HOST="", EMAIL_TIMEOUT="", DEFAULT_FROM_EMAIL="")
        self.assertIn("console", valores[0])
        self.assertEqual(valores[5], "10")

    def test_toma_el_smtp_del_entorno(self):
        valores = self._leer(
            DJANGO_EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="smtp.office365.com",
            EMAIL_PORT="587", EMAIL_USE_TLS="true", EMAIL_USE_SSL="false", EMAIL_TIMEOUT="5",
            DEFAULT_FROM_EMAIL="portal@napsislatam.com",
        )
        self.assertEqual(
            valores,
            ["django.core.mail.backends.smtp.EmailBackend", "smtp.office365.com", "587", "True", "False", "5",
             "portal@napsislatam.com"],
        )
