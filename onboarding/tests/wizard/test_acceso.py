"""Quién puede entrar al wizard."""

from django.contrib.auth.models import User
from django.urls import reverse

from clients.models import (
    Cliente,
)
from onboarding.tests.base import BaseWizard, _url


class AccesoAlWizardTests(BaseWizard):
    """Un cliente solo puede ver y completar SUS implementaciones: es la regla de
    seguridad central del wizard (no hay contraseñas por link, el link es el token)."""

    def test_anonimo_va_al_login_y_vuelve_al_paso(self):
        self.client.logout()
        respuesta = self.client.get(_url(self.implementacion, 1))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)
        self.assertIn(self.implementacion.token, respuesta.url)

    def test_otro_cliente_recibe_403(self):
        ajeno = User.objects.create_user(username="cliente_b", password="x")
        Cliente.objects.create(nombre="Empresa B", usuario=ajeno)
        self.client.force_login(ajeno)
        self.assertEqual(self.client.get(_url(self.implementacion, 1)).status_code, 403)

    def test_una_cuenta_sin_empresa_recibe_403(self):
        sin_empresa = User.objects.create_user(username="suelto", password="x")
        self.client.force_login(sin_empresa)
        self.assertEqual(self.client.get(_url(self.implementacion, 1)).status_code, 403)

    def test_el_dueno_entra(self):
        self.assertEqual(self.client.get(_url(self.implementacion, 1)).status_code, 200)

    def test_una_implementacion_cancelada_no_se_puede_completar(self):
        self.implementacion.anular()
        respuesta = self.client.get(_url(self.implementacion, 1))
        self.assertTemplateUsed(respuesta, "onboarding/cancelada.html")

    def test_un_paso_que_no_corresponde_a_los_modulos_redirige(self):
        """Sucursales (paso 3) solo existe con el módulo Fichada."""
        respuesta = self.client.get(_url(self.implementacion, 3))
        self.assertEqual(respuesta.status_code, 302)
        self.assertNotIn("/paso/3/", respuesta.url)
