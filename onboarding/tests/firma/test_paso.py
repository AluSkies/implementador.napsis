"""Paso de la firma en el wizard."""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from onboarding import acciones, services
from onboarding.tests.base import (
    GEOMETRIA,
    BaseWizard,
    _url,
    datos_de_formulario,
    imagen,
)

ANA = Actor.implementador("ana")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PasoDelWizardTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.implementacion.modelo_recibo.save("m.pdf", SimpleUploadedFile("m.pdf", b"%PDF-1.4"))

    def post(self, archivo="nueva", **cambios):
        datos = datos_de_formulario(**cambios)
        if archivo == "nueva":
            datos["imagen"] = imagen(300, 100, "firma.png")
        return self.client.post(_url(self.implementacion, services.PASO_FIRMA), datos)

    def test_sin_modelo_de_recibo_manda_a_subirlo(self):
        self.implementacion.modelo_recibo.delete()
        respuesta = self.client.get(_url(self.implementacion, services.PASO_FIRMA))
        self.assertContains(respuesta, "Subir el modelo de recibo")
        self.assertNotContains(respuesta, "firma-escenario")

    def test_muestra_el_editor_con_el_recibo_y_los_campos_de_respaldo(self):
        pagina = self.client.get(_url(self.implementacion, services.PASO_FIRMA))
        self.assertContains(pagina, "firma-escenario")
        self.assertContains(pagina, f'data-modelo="{self.implementacion.modelo_recibo.url}"')
        self.assertContains(pagina, 'name="empresa_x"')
        self.assertContains(pagina, "Ajustar con números")

    def test_guardar_bien_deja_la_firma_y_sigue_al_proximo_paso(self):
        respuesta = self.post()
        self.assertRedirects(respuesta, _url(self.implementacion, services.PASO_REVISION), fetch_redirect_response=False)
        firma = self.implementacion.firma
        self.assertEqual((firma.pagina, firma.geometria), ("ultima", GEOMETRIA))

    def test_una_imagen_chica_no_se_guarda_y_queda_registrado_por_que(self):
        respuesta = self.post(archivo=None, imagen=imagen(50, 20, "firma.png"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIsNone(self.implementacion.firma)
        evento = EventoImplementacion.objects.get(accion="validacion.fallida")
        self.assertEqual(evento.datos["paso"], services.PASO_FIRMA)
        self.assertIn("imagen", evento.datos["errores"])

    def test_si_ya_hay_firma_se_puede_guardar_sin_subir_otra_imagen(self):
        self.post()
        self.assertEqual(self.post(archivo=None, pagina="primera").status_code, 302)
        self.assertEqual(self.implementacion.firma.pagina, "primera")

    def test_el_cliente_ve_lo_que_le_observaron_en_este_paso(self):
        self.post()
        self.completar_todo()
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        acciones.observar_firma(ANA, self.implementacion, ["ilegible"], "Subila de nuevo.")
        pagina = self.client.get(_url(self.implementacion, services.PASO_FIRMA))
        self.assertContains(pagina, "Hay que ajustar la firma del recibo")
        self.assertContains(pagina, "Subila de nuevo.")

    def test_el_cartel_no_repite_el_mismo_texto_en_el_motivo_y_en_el_paso(self):
        self.post()
        self.completar_todo()
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        acciones.observar_firma(ANA, self.implementacion, ["ilegible"], "Subila de nuevo.")
        pagina = self.client.get(_url(self.implementacion, services.PASO_FIRMA)).content.decode()
        self.assertEqual(pagina.count("Subila de nuevo."), 1)
        self.assertNotIn("En este paso:", pagina)

    def test_cuando_la_observacion_del_paso_es_distinta_del_motivo_se_muestran_las_dos(self):
        self.post()
        self.completar_todo()
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        acciones.devolver_al_cliente(ANA, self.implementacion, "Revisá varias cosas.", {"firma": "Esta firma tapa el sueldo."})
        pagina = self.client.get(_url(self.implementacion, services.PASO_FIRMA))
        self.assertContains(pagina, "Revisá varias cosas.")
        self.assertContains(pagina, "En este paso:")
        self.assertContains(pagina, "Esta firma tapa el sueldo.")

    def test_el_envio_con_la_firma_faltante_se_rechaza(self):
        self.completar_todo()
        self.implementacion.firmas.all().delete()
        self.client.post(_url(self.implementacion, services.PASO_REVISION), {"accion": "enviar"})
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)
