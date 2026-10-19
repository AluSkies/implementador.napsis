"""El envío del cliente y el resultado de las acciones."""

from datetime import date
from unittest.mock import patch

from django.contrib import messages
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, Implementacion
from employees.models import Empleado
from onboarding import acciones

URL = "https://portal.napsis.example/"


def _eventos(accion):
    return EventoImplementacion.objects.filter(accion=accion)


class EnvioDelClienteTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa A", razon_social="Empresa A S.A.", cuits="30500010912")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente, mail_contacto="contacto@a.com")
        Empleado.objects.create(implementacion=self.implementacion, cuil="20111111112", nombre="J", apellido="P")
        self.cliente_actor = Actor.cliente("cli")

    def enviar(self, **extra):
        return acciones.enviar_relevamiento(self.cliente_actor, self.implementacion, date(2026, 12, 1), base_url=URL, **extra)

    def test_registra_el_envio_con_la_fecha_pedida(self):
        self.enviar()
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)
        self.assertEqual(self.implementacion.fecha_salida_productivo, date(2026, 12, 1))
        evento = _eventos("envio.confirmado").get()
        self.assertEqual((evento.datos["fecha_salida_productivo"], evento.datos["empleados"], evento.post_envio),
                         ("2026-12-01", 1, False))
        self.assertTrue(_eventos("implementacion.fecha_cambiada").exists())

    def test_avisa_al_equipo_y_confirma_al_cliente(self):
        with self.settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsis.com"]):
            self.enviar()
        destinatarios = {m.to[0] for m in mail.outbox}
        self.assertEqual(destinatarios, {"equipo@napsis.com", "contacto@a.com"})
        resumen = next(m for m in mail.outbox if m.to == ["equipo@napsis.com"])
        self.assertIn("https://portal.napsis.example/panel/implementaciones/", resumen.body)
        self.assertEqual({e.datos["tipo"] for e in _eventos("mail.enviado")}, {"equipo_resumen", "cliente_recibido"})

    def test_si_los_mails_fallan_el_envio_queda_igual(self):
        with patch("onboarding.acciones.notificaciones.notificar_implementacion_completa", side_effect=OSError("SMTP")), \
                patch("onboarding.acciones.notificaciones.notificar_cliente_relevamiento_recibido", side_effect=OSError("SMTP")), \
                self.assertLogs("onboarding.acciones", level="ERROR"):
            resultado = self.enviar()
        self.implementacion.refresh_from_db()
        self.assertTrue(resultado.ok)
        self.assertIsNotNone(self.implementacion.enviado)
        self.assertEqual(_eventos("mail.fallido").count(), 2)

    def test_pedir_que_lo_contacten(self):
        self.implementacion.enviado = timezone.now()
        self.implementacion.save()
        with self.settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsis.com"]):
            resultado = acciones.pedir_revision(self.cliente_actor, self.implementacion, "Llamen por favor", base_url=URL)
        self.implementacion.refresh_from_db()
        self.assertTrue(self.implementacion.revision_solicitada)
        self.assertEqual(_eventos("revision.solicitada").get().datos, {"mensaje": "Llamen por favor"})
        self.assertIn("Le avisamos al equipo", resultado.avisos[0].texto)
        self.assertEqual(mail.outbox[0].to, ["equipo@napsis.com"])

    def test_registrar_lo_que_no_se_pudo_completar(self):
        acciones.registrar_validacion_fallida(self.cliente_actor, self.implementacion, 1, {"cuits": ["inválido"]})
        evento = _eventos("validacion.fallida").get()
        self.assertEqual((evento.datos["paso"], evento.datos["errores"]), (1, {"cuits": ["inválido"]}))


class ResultadoTests(TestCase):
    def test_mostrar_usa_el_sistema_de_mensajes(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        pedido = RequestFactory().get("/")
        pedido.session = {}
        pedido._messages = FallbackStorage(pedido)
        acciones.Resultado(avisos=[acciones.Aviso(messages.WARNING, "ojo")]).mostrar(pedido)
        self.assertEqual([str(m) for m in pedido._messages], ["ojo"])
