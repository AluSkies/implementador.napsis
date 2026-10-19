"""Solo se cumple lo que está validado."""

import tempfile

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Implementacion
from onboarding import acciones
from onboarding.tests.base import EnviadaBase

ANA = Actor.implementador("ana")


def _eventos(accion):
    return EventoImplementacion.objects.filter(accion=accion)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CumplirTests(EnviadaBase):
    def test_solo_se_cumple_lo_que_esta_validado(self):
        resultado = acciones.marcar_cumplida(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_PENDIENTE)
        self.assertIn("ya validada", resultado.avisos[0].texto)
        self.assertFalse(_eventos("estado.cumplida").exists())
        self.assertEqual(mail.outbox, [])

    def test_validada_si_se_cumple(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        acciones.marcar_cumplida(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)

    def test_no_se_cumple_lo_que_el_cliente_no_envio(self):
        otra = Implementacion.objects.create(cliente=self.cliente, validada_en=timezone.now())
        acciones.marcar_cumplida(ANA, otra)
        self.assertEqual(otra.estado, Implementacion.ESTADO_PENDIENTE)

    def test_no_se_cumple_una_cancelada(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        acciones.anular(ANA, self.implementacion)
        acciones.marcar_cumplida(ANA, self.implementacion)
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CANCELADA)

    def test_un_pedido_directo_al_panel_tampoco_la_cumple(self):
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        self.client.post(url, {"accion": "marcar_cumplida"})
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_PENDIENTE)

    def test_la_ficha_ofrece_cumplir_solo_si_esta_validada(self):
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        self.assertNotContains(self.client.get(url), "Marcar implementación como cumplida")
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertContains(self.client.get(url), "Marcar implementación como cumplida")
