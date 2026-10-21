import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parents[3]


def _importar_settings(**entorno):
    """Importa config.settings en un proceso aparte con ese entorno (las variables
    seteadas, aun vacías, pisan lo que cargaría un .env local)."""
    env = {**os.environ, **entorno}
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=BASE_DIR, env=env, capture_output=True, text=True,
    )


class SinMysqlNoHayFallbackASqliteTests(SimpleTestCase):
    """Un despliegue al que le falta la configuración de MySQL no puede arrancar con un SQLite suelto
    (guardaría los datos en un archivo del contenedor y los perdería al reiniciar)."""

    PRODUCCION = {"DJANGO_SECRET_KEY": "una-clave-cualquiera", "DJANGO_DEBUG": "false", "DJANGO_ALLOW_SQLITE": ""}

    def test_en_produccion_sin_mysql_no_arranca(self):
        resultado = _importar_settings(**self.PRODUCCION, MYSQL_DB="")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("MYSQL_DB", resultado.stderr)

    def test_en_produccion_con_mysql_arranca(self):
        resultado = _importar_settings(**self.PRODUCCION, MYSQL_DB="napsis")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_en_desarrollo_se_usa_sqlite(self):
        resultado = _importar_settings(**{**self.PRODUCCION, "DJANGO_DEBUG": "true"}, MYSQL_DB="")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_el_ci_y_el_build_lo_permiten_expresamente(self):
        resultado = _importar_settings(**{**self.PRODUCCION, "DJANGO_ALLOW_SQLITE": "true"}, MYSQL_DB="")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_el_dockerfile_y_el_ci_declaran_la_excepcion(self):
        self.assertIn("DJANGO_ALLOW_SQLITE=true", (BASE_DIR / "Dockerfile").read_text(encoding="utf-8"))
        self.assertIn("DJANGO_ALLOW_SQLITE", (BASE_DIR / ".github" / "workflows" / "docker.yml").read_text(encoding="utf-8"))


class SecretKeyObligatoriaTests(SimpleTestCase):
    """Sin esto la app arrancaba con una clave escrita en el repo (público): cualquiera
    podría falsificar sesiones. En producción tiene que fallar fuerte al arrancar."""

    def test_sin_clave_y_sin_debug_no_arranca(self):
        resultado = _importar_settings(DJANGO_SECRET_KEY="", DJANGO_DEBUG="false")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", resultado.stderr)

    def test_con_clave_arranca(self):
        resultado = _importar_settings(DJANGO_SECRET_KEY="una-clave-cualquiera", DJANGO_DEBUG="false", MYSQL_DB="napsis")
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
            cwd=BASE_DIR, env={**os.environ, "DJANGO_ALLOW_SQLITE": "true", "DJANGO_SECRET_KEY": "x", "DJANGO_DEBUG": "false"},
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
        env = {**os.environ, "DJANGO_ALLOW_SQLITE": "true", "DJANGO_SECRET_KEY": "una-clave-cualquiera", "DJANGO_DEBUG": "false", **entorno}
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


class HttpsObligatorioTests(SimpleTestCase):
    """Fuera de los tests y del modo desarrollo, la app exige HTTPS por sí misma."""

    def _leer(self, **entorno):
        env = {**os.environ, "DJANGO_ALLOW_SQLITE": "true", "DJANGO_SECRET_KEY": "una-clave-cualquiera", **entorno}
        codigo = (
            "import config.settings as s; print('|'.join(map(str, ["
            "s.SECURE_SSL_REDIRECT if hasattr(s, 'SECURE_SSL_REDIRECT') else False, "
            "getattr(s, 'SESSION_COOKIE_SECURE', False), getattr(s, 'CSRF_COOKIE_SECURE', False), "
            "getattr(s, 'SECURE_HSTS_SECONDS', 0), getattr(s, 'SECURE_HSTS_INCLUDE_SUBDOMAINS', False)])))"
        )
        salida = subprocess.run([sys.executable, "-c", codigo], cwd=BASE_DIR, env=env, capture_output=True, text=True)
        self.assertEqual(salida.returncode, 0, salida.stderr)
        return salida.stdout.strip().split("|")

    def test_en_produccion_redirige_a_https_marca_las_cookies_y_activa_hsts(self):
        self.assertEqual(
            self._leer(DJANGO_DEBUG="false", DJANGO_FORCE_HTTPS="", SECURE_HSTS_SECONDS=""),
            ["True", "True", "True", "3600", "False"],
        )

    def test_el_hsts_se_puede_subir_por_variable(self):
        self.assertEqual(self._leer(DJANGO_DEBUG="false", SECURE_HSTS_SECONDS="31536000")[3], "31536000")

    def test_en_desarrollo_no_se_fuerza(self):
        self.assertEqual(
            self._leer(DJANGO_DEBUG="true", DJANGO_FORCE_HTTPS="", SECURE_HSTS_SECONDS=""),
            ["False", "False", "False", "0", "False"],
        )

    def test_se_puede_apagar_explicitamente_para_probar_por_http(self):
        self.assertEqual(self._leer(DJANGO_DEBUG="false", DJANGO_FORCE_HTTPS="false")[0], "False")

    def test_el_chequeo_de_salud_queda_exento_del_redirect(self):
        from django.conf import settings

        env = {**os.environ, "DJANGO_ALLOW_SQLITE": "true", "DJANGO_SECRET_KEY": "una-clave-cualquiera", "DJANGO_DEBUG": "false"}
        salida = subprocess.run(
            [sys.executable, "-c", "import config.settings as s; print(s.SECURE_REDIRECT_EXEMPT)"],
            cwd=BASE_DIR, env=env, capture_output=True, text=True,
        )
        self.assertIn("salud", salida.stdout)
        self.assertIsNotNone(settings.SECURE_PROXY_SSL_HEADER)  # el proxy avisa el esquema original


class EntrypointRechazaValoresDeEjemploTests(SimpleTestCase):
    """El .env.docker.example trae textos de relleno: si se copian sin cambiar, el contenedor no arranca."""

    BUENO = {
        "DJANGO_SECRET_KEY": "k" * 50, "DJANGO_ALLOWED_HOSTS": "portal.example.com",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://portal.example.com", "SITE_BASE_URL": "https://portal.example.com",
        "MYSQL_DB": "napsis", "MYSQL_USER": "napsis", "MYSQL_PASSWORD": "una-clave-de-base-real", "MYSQL_HOST": "db",
        "DJANGO_SUPERUSER_PASSWORD": "una-clave-larga-9XqT",
    }

    def correr(self, **cambios):
        sh = shutil.which("sh")
        if not sh:
            self.skipTest("No hay un shell POSIX disponible para probar el entrypoint.")
        entorno = {**os.environ, **self.BUENO, **cambios}
        return subprocess.run(
            [sh, "docker/entrypoint.sh", "true"], cwd=BASE_DIR, env=entorno, capture_output=True, text=True,
        )

    def rechaza(self, **cambios):
        resultado = self.correr(**cambios)
        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("valor de ejemplo", resultado.stderr)
        return resultado.stderr

    def test_rechaza_la_clave_de_ejemplo(self):
        self.assertIn("DJANGO_SECRET_KEY", self.rechaza(DJANGO_SECRET_KEY="generar-una-clave-larga-y-aleatoria" + "x" * 10))

    def test_rechaza_una_clave_con_la_palabra_cambiar(self):
        self.assertIn("DJANGO_SECRET_KEY", self.rechaza(DJANGO_SECRET_KEY="cambiar-" + "x" * 50))

    def test_rechaza_la_clave_de_desarrollo_de_django(self):
        self.assertIn("DJANGO_SECRET_KEY", self.rechaza(DJANGO_SECRET_KEY="django-insecure-" + "x" * 50))

    def test_rechaza_una_clave_corta(self):
        self.assertIn("muy corta", self.rechaza(DJANGO_SECRET_KEY="corta"))

    def test_rechaza_las_contrasenas_de_ejemplo(self):
        self.assertIn("MYSQL_PASSWORD", self.rechaza(MYSQL_PASSWORD="cambiar"))
        self.assertIn("DJANGO_SUPERUSER_PASSWORD", self.rechaza(DJANGO_SUPERUSER_PASSWORD="cambiar"))

    def test_sigue_exigiendo_las_obligatorias(self):
        resultado = self.correr(DJANGO_ALLOWED_HOSTS="")
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("DJANGO_ALLOWED_HOSTS", resultado.stderr)


class LogDeErroresTests(SimpleTestCase):
    """Los errores 500 quedan guardados en un archivo; el aviso por mail está apagado por defecto."""

    def _correr(self, codigo, **entorno):
        with tempfile.TemporaryDirectory() as carpeta:
            env = {**os.environ, "DJANGO_ALLOW_SQLITE": "true", "DJANGO_SECRET_KEY": "una-clave-cualquiera", "DJANGO_DEBUG": "false",
                   "DJANGO_SETTINGS_MODULE": "config.settings", "LOG_DIR": carpeta, **entorno}
            salida = subprocess.run([sys.executable, "-c", codigo], cwd=BASE_DIR, env=env, capture_output=True, text=True)
            archivo = Path(carpeta) / "errores.log"
            return salida, archivo.read_text(encoding="utf-8") if archivo.exists() else None

    REGISTRAR_ERROR = (
        "import django, logging; django.setup()\n"
        "try:\n    1 / 0\nexcept ZeroDivisionError:\n"
        "    logging.getLogger('django.request').error('Internal Server Error: /panel/', exc_info=True)\n"
        "    logging.getLogger('onboarding.views').exception('No se pudo avisar al equipo')\n"
        "logging.getLogger('django.request').warning('Not Found: /x')\n"
        "logging.getLogger('onboarding.views').info('algo normal')\n"
    )

    def test_un_error_500_queda_en_el_archivo_con_fecha_y_traceback(self):
        salida, contenido = self._correr(self.REGISTRAR_ERROR)
        self.assertEqual(salida.returncode, 0, salida.stderr)
        self.assertIn("ERROR [-] django.request: Internal Server Error: /panel/", contenido)
        self.assertIn("ZeroDivisionError", contenido)
        self.assertRegex(contenido, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_tambien_guarda_lo_que_el_codigo_registra_como_error(self):
        _salida, contenido = self._correr(self.REGISTRAR_ERROR)
        self.assertIn("ERROR [-] onboarding.views: No se pudo avisar al equipo", contenido)

    def test_no_guarda_avisos_ni_informacion_normal(self):
        _salida, contenido = self._correr(self.REGISTRAR_ERROR)
        self.assertNotIn("Not Found", contenido)
        self.assertNotIn("algo normal", contenido)

    def test_no_crea_el_archivo_si_no_hay_errores(self):
        _salida, contenido = self._correr("import django; django.setup()")
        self.assertIsNone(contenido)

    def test_si_no_se_puede_crear_la_carpeta_la_app_arranca_igual_solo_con_consola(self):
        salida, _ = self._correr(
            "import django, logging; django.setup(); logging.getLogger('x').error('hola'); print('arrancó')",
            LOG_DIR=str(BASE_DIR / "manage.py" / "no-se-puede"),  # un archivo no es una carpeta
        )
        self.assertEqual(salida.returncode, 0, salida.stderr)
        self.assertIn("arrancó", salida.stdout)

    def test_el_aviso_por_mail_esta_apagado_por_defecto(self):
        salida, _ = self._correr(
            "import django; django.setup(); from django.conf import settings; print(settings.ERROR_ALERT_EMAILS)",
            ERROR_ALERT_EMAILS="", IMPLEMENTATION_TEAM_EMAILS="equipo@napsislatam.com",
        )
        self.assertEqual(salida.stdout.strip(), "[]")

    def test_se_activa_definiendo_los_destinatarios(self):
        salida, _ = self._correr(
            "import django; django.setup(); from django.conf import settings; print(settings.ERROR_ALERT_EMAILS)",
            ERROR_ALERT_EMAILS="yo@napsislatam.com, otro@napsislatam.com",
        )
        self.assertEqual(salida.stdout.strip(), "['yo@napsislatam.com', 'otro@napsislatam.com']")
