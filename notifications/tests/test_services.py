from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from clients.models import Cliente, Implementacion
from notifications.services import notificar_implementacion_completa, notificar_revision_solicitada


class NotificarImplementacionCompletaTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba", cuits="30-12345678-9")
        self.implementacion = Implementacion.objects.create(
            cliente=self.cliente, mail_contacto="cliente@example.com",
        )

    @override_settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsislatam.com"])
    def test_envia_mail_al_equipo_cuando_hay_destinatarios_configurados(self):
        with self.assertLogs("notifications.services", level="INFO"):  # webhook sin configurar: loggea y sigue
            notificar_implementacion_completa(self.implementacion)

        self.assertEqual(len(mail.outbox), 1)
        enviado = mail.outbox[0]
        self.assertIn("Empresa de Prueba", enviado.subject)
        self.assertEqual(enviado.to, ["equipo@napsislatam.com"])

    @override_settings(IMPLEMENTATION_TEAM_EMAILS=[])
    def test_no_envia_nada_si_no_hay_destinatarios_configurados(self):
        with self.assertLogs("notifications.services", level="WARNING"):
            notificar_implementacion_completa(self.implementacion)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsislatam.com"], GOOGLE_SHEETS_WEBHOOK_URL="")
    def test_no_llama_al_webhook_si_no_esta_configurado(self):
        with patch("notifications.services.requests.post") as post_mock:
            with self.assertLogs("notifications.services", level="INFO"):
                notificar_implementacion_completa(self.implementacion)
        post_mock.assert_not_called()

    @override_settings(
        IMPLEMENTATION_TEAM_EMAILS=["equipo@napsislatam.com"],
        GOOGLE_SHEETS_WEBHOOK_URL="https://script.google.com/macros/s/fake/exec",
    )
    def test_llama_al_webhook_con_el_resumen_cuando_esta_configurado(self):
        with patch("notifications.services.requests.post") as post_mock:
            notificar_implementacion_completa(self.implementacion)

        post_mock.assert_called_once()
        _args, kwargs = post_mock.call_args
        self.assertEqual(kwargs["json"]["razon_social"], "Empresa de Prueba")

    @override_settings(
        IMPLEMENTATION_TEAM_EMAILS=["equipo@napsislatam.com"],
        GOOGLE_SHEETS_WEBHOOK_URL="https://script.google.com/macros/s/fake/exec",
    )
    def test_una_falla_de_red_en_el_webhook_no_rompe_el_flujo(self):
        """El mail al equipo ya se mandó cuando se intenta el webhook — un timeout
        de Google Sheets no debería tirar un 500 en la vista que llama a esto."""
        import requests

        with patch("notifications.services.requests.post", side_effect=requests.ConnectionError("timeout")):
            with self.assertLogs("notifications.services", level="ERROR"):
                try:
                    notificar_implementacion_completa(self.implementacion)
                except requests.RequestException:
                    self.fail("una falla del webhook no debería propagarse")

        self.assertEqual(len(mail.outbox), 1)


class NotificarRevisionSolicitadaTests(TestCase):
    @override_settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsislatam.com"])
    def test_envia_mail_con_el_mensaje_del_cliente(self):
        cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        implementacion = Implementacion.objects.create(
            cliente=cliente, revision_mensaje="Necesito ayuda con la firma digital",
        )

        notificar_revision_solicitada(implementacion)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Empresa de Prueba", mail.outbox[0].subject)
