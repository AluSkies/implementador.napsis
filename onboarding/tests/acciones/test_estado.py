"""Reasignar, reabrir, anular y cumplir desde las acciones."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, Implementacion
from onboarding import acciones

ANA = Actor.implementador("ana")
URL = "https://portal.napsis.example/"


def _eventos(accion):
    return EventoImplementacion.objects.filter(accion=accion)


class EstadoDeLaImplementacionTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa A")
        self.implementacion = Implementacion.objects.create(
            cliente=self.cliente, mail_contacto="contacto@a.com", enviado=timezone.now(), validada_en=timezone.now(),
        )

    def test_reasignar_registra_de_quien_a_quien(self):
        antes = User.objects.create_user("antes", password="x", is_staff=True)
        despues = User.objects.create_user("despues", password="x", is_staff=True, first_name="Des", last_name="Pues")
        self.implementacion.implementador_asignado = antes
        self.implementacion.save()
        resultado = acciones.reasignar(ANA, self.implementacion, despues)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.implementador_asignado, despues)
        self.assertEqual(_eventos("implementacion.reasignada").get().datos, {"desde": "antes", "hacia": "despues"})
        self.assertIn("Des Pues", resultado.avisos[0].texto)

    def test_marcar_cumplida_avisa_al_cliente(self):
        acciones.marcar_cumplida(ANA, self.implementacion, base_url=URL)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)
        self.assertEqual(mail.outbox[0].subject, "Tu implementación está lista")
        self.assertIn("https://portal.napsis.example/login/", mail.outbox[0].body)
        evento = _eventos("estado.cumplida").get()
        self.assertEqual((evento.datos["estado_anterior"], evento.post_envio), ("pendiente", True))

    def test_si_el_mail_falla_queda_cumplida_igual_y_se_avisa(self):
        with patch("onboarding.acciones.notificaciones.notificar_cliente_implementacion_cumplida", side_effect=OSError("SMTP")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                resultado = acciones.marcar_cumplida(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)
        self.assertIn("no se pudo avisarle al cliente", resultado.avisos[0].texto)

    def test_sin_mail_del_cliente_no_hay_aviso_ni_falla(self):
        self.implementacion.mail_contacto = ""
        self.implementacion.save()
        resultado = acciones.marcar_cumplida(ANA, self.implementacion)
        self.assertEqual((resultado.avisos, mail.outbox), ([], []))
        self.assertFalse(_eventos("mail.enviado").exists())

    def test_anular(self):
        acciones.anular(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CANCELADA)
        self.assertEqual(_eventos("estado.cancelada").get().datos, {"estado_anterior": "pendiente"})

    def test_reabrir_deja_constancia_de_como_estaba(self):
        self.implementacion.paso_actual = 7
        self.implementacion.save()
        acciones.reabrir(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual((self.implementacion.paso_actual, self.implementacion.enviado), (1, None))
        antes = _eventos("estado.reabierta").get().datos["antes"]
        self.assertEqual((antes["paso_actual"], antes["estado"]), (7, "pendiente"))
        self.assertIsNotNone(antes["enviado"])

    def test_atender_la_revision(self):
        self.implementacion.pedir_revision("Llamen")
        acciones.atender_revision(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.revision_atendida_en)
        self.assertTrue(_eventos("revision.atendida").exists())
