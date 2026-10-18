"""Elección de tipos de liquidación en el wizard."""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from catalog.models import TipoLiquidacion
from onboarding import services
from onboarding.tests.base import BaseWizard, _url

CLIENTE = Actor.cliente("cliente_a")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PasoDeConfiguracionTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.aguinaldo = TipoLiquidacion.objects.create(nombre="Aguinaldo", orden=1)

    def post(self, *tipos):
        return self.client.post(_url(self.implementacion, 6), {
            "tipo_firma": "digital", "segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [t.pk for t in tipos],
            "modelo_recibo": SimpleUploadedFile("m.pdf", b"%PDF-1.4"),
        })

    def test_muestra_los_tipos_en_orden(self):
        pagina = self.client.get(_url(self.implementacion, 6)).content.decode()
        self.assertLess(pagina.index("Liquidación Normal"), pagina.index("Aguinaldo"))

    def test_sin_elegir_ninguno_no_avanza(self):
        respuesta = self.post()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Elegí al menos un tipo de liquidación")

    def test_guarda_los_elegidos_y_deja_los_demas_inactivos(self):
        self.assertEqual(self.post(self.aguinaldo).status_code, 302)
        activos = self.implementacion.liquidaciones.filter(activo=True).values_list("tipo_liquidacion__nombre", flat=True)
        self.assertEqual(list(activos), ["Aguinaldo"])
        self.assertFalse(self.implementacion.liquidaciones.get(tipo_liquidacion=self.liquidacion).activo)

    def test_queda_en_el_historial_y_como_evento(self):
        self.post(self.aguinaldo, self.liquidacion)
        evento = EventoImplementacion.objects.get(accion="paso.guardado", seccion="liquidaciones")
        self.assertEqual(evento.actor_tipo, "cliente")
        self.assertEqual(evento.datos["cambios"]["Aguinaldo"], {"antes": None, "despues": True})
        self.assertTrue(self.implementacion.versiones.filter(seccion="liquidaciones").exists())

    def test_cambiar_la_eleccion_registra_el_antes_y_el_despues(self):
        self.post(self.aguinaldo, self.liquidacion)
        self.post(self.aguinaldo)
        ultimo = EventoImplementacion.objects.filter(seccion="liquidaciones").last()
        self.assertEqual(ultimo.datos["cambios"], {"Liquidación Normal": {"antes": True, "despues": False}})


class ControlDeFaltantesTests(BaseWizard):
    def test_con_recibo_digital_pide_elegir_un_tipo(self):
        mensajes = [(p["paso"], p["mensaje"]) for p in services.pendientes_de_envio(self.implementacion)]
        self.assertIn((6, "Elegir al menos un tipo de liquidación."), mensajes)

    def test_deja_de_pedirlo_cuando_hay_uno(self):
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], CLIENTE)
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertNotIn("Elegir al menos un tipo de liquidación.", mensajes)

    def test_sin_recibo_digital_no_se_pide(self):
        self.implementacion.modulos.update(activo=False)
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertNotIn("Elegir al menos un tipo de liquidación.", mensajes)

    def test_si_se_desactivan_todos_vuelve_a_pedirlo(self):
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], CLIENTE)
        services.guardar_liquidaciones(self.implementacion, [], CLIENTE)
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertIn("Elegir al menos un tipo de liquidación.", mensajes)
