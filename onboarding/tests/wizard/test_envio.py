"""Revisión, envío y fecha de implementación."""

import tempfile
from unittest.mock import patch

from django.test import override_settings

from clients.models import (
    Implementacion,
)
from onboarding.tests.base import BaseWizard, _url


class Paso9EnvioTests(BaseWizard):
    def _enviar(self):
        return self.client.post(_url(self.implementacion, 10), {"accion": "enviar"})

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_con_pendientes_no_se_envia_y_se_los_muestra(self):
        respuesta = self._enviar()
        self.assertEqual(respuesta.status_code, 200)
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)
        self.assertContains(respuesta, "razón social y el CUIT")
        self.assertContains(respuesta, "nómina")

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_saltar_de_paso_por_la_url_no_evita_las_validaciones(self):
        """Los pasos no son secuenciales: ir directo al 9 no debe permitir enviar a medias."""
        self.agregar_empleado()
        self.assertIsNone(self.implementacion.enviado)
        self._enviar()
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_completo_se_envia_pero_no_queda_cumplida(self):
        self.completar_todo()
        respuesta = self._enviar()
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)
        # Que el cliente envíe no significa que Napsis ya implementó: sigue pendiente.
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_PENDIENTE)
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_COMPLETADO_CLIENTE)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_si_falla_el_mail_el_cliente_igual_queda_enviado(self):
        self.completar_todo()
        with patch("onboarding.acciones.notificaciones.notificar_implementacion_completa", side_effect=OSError("SMTP caído")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                respuesta = self._enviar()
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Paso9FechaDeImplementacionTests(BaseWizard):
    """El cliente puede pedir fecha de implementación (opcional), pero no antes del mínimo de
    días hábiles. El equipo puede poner cualquier fecha desde el panel."""

    def setUp(self):
        super().setUp()
        self.completar_todo()
        from onboarding import services

        self.minima = services.fecha_minima_para_cliente()

    def _enviar_con_fecha(self, fecha):
        return self.client.post(
            _url(self.implementacion, 10), {"accion": "enviar", "fecha_salida_productivo": fecha.isoformat() if fecha else ""},
        )

    def test_es_opcional(self):
        self.assertEqual(self._enviar_con_fecha(None).status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.fecha_salida_productivo)
        self.assertIsNotNone(self.implementacion.enviado)

    def test_antes_del_minimo_se_rechaza_y_no_se_envia(self):
        from datetime import timedelta

        respuesta = self._enviar_con_fecha(self.minima - timedelta(days=1))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, f"{self.minima:%d/%m/%Y}")
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)
        self.assertIsNone(self.implementacion.fecha_salida_productivo)

    def test_pedir_manana_o_hoy_tambien_se_rechaza(self):
        from datetime import timedelta

        from django.utils import timezone

        for dias in (0, 1):
            with self.subTest(dias=dias):
                respuesta = self._enviar_con_fecha(timezone.localdate() + timedelta(days=dias))
                self.assertEqual(respuesta.status_code, 200)

    def test_desde_el_minimo_se_acepta_y_queda_en_el_historial(self):
        self._enviar_con_fecha(self.minima)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.fecha_salida_productivo, self.minima)
        self.assertIsNotNone(self.implementacion.enviado)
        version = self.implementacion.versiones.get(seccion="fecha_implementacion")
        self.assertEqual(version.editado_por, "Cliente")

    def test_la_fecha_que_puso_el_equipo_se_acepta_aunque_sea_anterior_al_minimo(self):
        from datetime import timedelta

        fecha_del_equipo = self.minima - timedelta(days=5)
        self.implementacion.fecha_salida_productivo = fecha_del_equipo
        self.implementacion.save()
        self.assertEqual(self._enviar_con_fecha(fecha_del_equipo).status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.fecha_salida_productivo, fecha_del_equipo)

    def test_viene_precargada_con_la_fecha_ya_definida(self):
        self.implementacion.fecha_salida_productivo = self.minima
        self.implementacion.save()
        self.assertContains(self.client.get(_url(self.implementacion, 10)), self.minima.isoformat())

    def test_el_campo_avisa_cual_es_la_fecha_minima(self):
        self.assertContains(self.client.get(_url(self.implementacion, 10)), f'min="{self.minima.isoformat()}"')
