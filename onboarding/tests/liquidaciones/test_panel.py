"""Tipos de liquidación en la ficha y en el resumen."""

from django.core import mail
from django.urls import reverse

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from catalog.models import TipoLiquidacion
from clients.models import Cliente, Implementacion
from dashboard.tests.base import BasePanel
from onboarding import services

ANA = Actor.implementador("ana")


class PanelYResumenTests(BasePanel):
    def setUp(self):
        super().setUp()
        self.normal = TipoLiquidacion.objects.create(nombre="Liquidación Normal")
        self.aguinaldo = TipoLiquidacion.objects.create(nombre="Aguinaldo", orden=1)
        self.implementacion = Implementacion.objects.create(
            cliente=Cliente.objects.create(nombre="Empresa A"), mail_contacto="c@a.com",
        )
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_se_editan_desde_la_ficha(self):
        respuesta = self.client.post(self.url, {"accion": "actualizar_liquidaciones", "tipos_liquidacion": [self.aguinaldo.pk]})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            list(self.implementacion.liquidaciones.filter(activo=True).values_list("tipo_liquidacion__nombre", flat=True)),
            ["Aguinaldo"],
        )
        evento = EventoImplementacion.objects.get(seccion="liquidaciones")
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("supervisor", "ana"))

    def test_sin_elegir_ninguno_vuelve_con_el_error(self):
        respuesta = self.client.post(self.url, {"accion": "actualizar_liquidaciones"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Elegí al menos un tipo de liquidación")

    def test_la_ficha_muestra_los_elegidos(self):
        services.guardar_liquidaciones(self.implementacion, [self.normal, self.aguinaldo], ANA)
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Tipos de liquidación")
        self.assertContains(pagina, "Liquidación Normal, Aguinaldo")

    def test_el_mail_al_equipo_los_incluye(self):
        from notifications.services import notificar_implementacion_completa

        services.guardar_liquidaciones(self.implementacion, [self.aguinaldo], ANA)
        with self.settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsis.com"]):
            notificar_implementacion_completa(self.implementacion)
        self.assertIn("Tipos de liquidación: Aguinaldo", mail.outbox[0].body)
