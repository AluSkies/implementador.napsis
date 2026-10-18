
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


class DestinatariosConImplementadorAsignadoTests(TestCase):
    """Los mails van al equipo (lista fija) y, además, al implementador asignado."""

    def setUp(self):
        from django.contrib.auth.models import User

        self.ana = User.objects.create_user(username="ana", password="x", email="ana@napsislatam.com")
        cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=cliente, implementador_asignado=self.ana)

    @override_settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsislatam.com"])
    def test_le_llega_al_equipo_y_al_asignado(self):
        notificar_revision_solicitada(self.implementacion)
        self.assertCountEqual(mail.outbox[0].to, ["equipo@napsislatam.com", "ana@napsislatam.com"])

    @override_settings(IMPLEMENTATION_TEAM_EMAILS=[])
    def test_si_no_hay_lista_fija_igual_le_llega_al_asignado(self):
        notificar_revision_solicitada(self.implementacion)
        self.assertEqual(mail.outbox[0].to, ["ana@napsislatam.com"])

    @override_settings(IMPLEMENTATION_TEAM_EMAILS=["ana@napsislatam.com", "equipo@napsislatam.com"])
    def test_no_repite_un_destinatario_que_ya_esta_en_la_lista(self):
        notificar_revision_solicitada(self.implementacion)
        self.assertEqual(sorted(mail.outbox[0].to), ["ana@napsislatam.com", "equipo@napsislatam.com"])

    @override_settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsislatam.com"])
    def test_un_asignado_sin_mail_no_rompe(self):
        self.ana.email = ""
        self.ana.save()
        notificar_revision_solicitada(self.implementacion)
        self.assertEqual(mail.outbox[0].to, ["equipo@napsislatam.com"])

    @override_settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsislatam.com"])
    def test_el_resumen_usa_la_razon_social_si_existe_y_nombra_al_implementador(self):
        from notifications.services import _resumen_dict

        cliente = self.implementacion.cliente
        cliente.razon_social = "Empresa de Prueba S.A."
        cliente.save()
        resumen = _resumen_dict(self.implementacion)
        self.assertEqual(resumen["razon_social"], "Empresa de Prueba S.A.")
        self.assertEqual(resumen["implementador"], "ana")
