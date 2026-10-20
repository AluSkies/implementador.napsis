import os
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from clients.models import Modulo


class SeedModulosCommandTests(TestCase):
    def test_carga_el_catalogo_de_modulos(self):
        call_command("seed_modulos", stdout=StringIO())
        nombres = set(Modulo.objects.values_list("nombre", flat=True))
        self.assertEqual(nombres, {"Recibo Digital", "Comunicación", "Fichada", "Legajos", "Novedades"})

    def test_correrlo_dos_veces_no_duplica_nada(self):
        call_command("seed_modulos", stdout=StringIO())
        call_command("seed_modulos", stdout=StringIO())
        self.assertEqual(Modulo.objects.count(), 5)


class EnsureSuperuserCommandTests(TestCase):
    """Reemplaza a `createsuperuser` interactivo en plataformas sin shell
    (ej. un contenedor) — se corre en cada deploy, así que tiene que ser
    idempotente y no pisar una contraseña ya cambiada desde el admin."""

    def _run(self, **env):
        import os
        previos = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            call_command("ensure_superuser", stdout=StringIO())
        finally:
            for k, v in previos.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_sin_variables_no_hace_nada(self):
        self._run(DJANGO_SUPERUSER_USERNAME="", DJANGO_SUPERUSER_PASSWORD="")
        self.assertEqual(User.objects.count(), 0)

    def test_crea_superusuario_con_las_variables(self):
        self._run(
            DJANGO_SUPERUSER_USERNAME="admin_render",
            DJANGO_SUPERUSER_PASSWORD="una-password-cualquiera",
            DJANGO_SUPERUSER_EMAIL="admin@example.com",
        )
        admin = User.objects.get(username="admin_render")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password("una-password-cualquiera"))

    def test_correrlo_de_nuevo_no_pisa_la_password_ya_cambiada(self):
        self._run(
            DJANGO_SUPERUSER_USERNAME="admin_render",
            DJANGO_SUPERUSER_PASSWORD="password-original",
        )
        admin = User.objects.get(username="admin_render")
        admin.set_password("password-cambiada-a-mano")
        admin.save()

        self._run(
            DJANGO_SUPERUSER_USERNAME="admin_render",
            DJANGO_SUPERUSER_PASSWORD="password-original",
        )

        admin.refresh_from_db()
        self.assertTrue(admin.check_password("password-cambiada-a-mano"))


class AvisoSinAdminTests(TestCase):
    """Un despliegue sin variables de superusuario y sin ningún admin tiene que avisarlo en voz alta."""

    def correr(self):
        salida, error = StringIO(), StringIO()
        previos = {k: os.environ.pop(k, None) for k in ("DJANGO_SUPERUSER_USERNAME", "DJANGO_SUPERUSER_PASSWORD")}
        try:
            call_command("ensure_superuser", stdout=salida, stderr=error)
        finally:
            for k, v in previos.items():
                if v is not None:
                    os.environ[k] = v
        return error.getvalue()

    def test_sin_variables_y_sin_admin_advierte_como_crearlo(self):
        self.assertIn("no hay ninguna cuenta Admin", self.correr())
        self.assertIn("createsuperuser", self.correr())

    def test_si_ya_hay_un_admin_no_advierte(self):
        User.objects.create_superuser("admin", password="Clave-Larga-2026!")
        self.assertEqual(self.correr(), "")
