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
