"""Paso de configuración y adjuntos."""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from onboarding.tests.base import BaseWizard, _url


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ConfiguracionRespetaLosBloqueosTests(BaseWizard):
    """Lo que el implementador dejó fijo no se puede cambiar desde el wizard, ni siquiera
    editando el formulario a mano."""

    def _post(self, **extra):
        datos = {
            "tipo_firma": "electronica", "nomenclatura_pdf": "mi_formato.pdf",
            "segmentacion_liquidador": "POR SUCURSAL", "tipos_liquidacion": [self.liquidacion.pk],
            "modelo_recibo": SimpleUploadedFile("m.pdf", b"%PDF-1.4"),
            **extra,
        }
        return self.client.post(reverse("onboarding:wizard_step", kwargs={"token": self.implementacion.token, "step": 6}), datos)

    def bloquear(self):
        self.implementacion.tipo_firma, self.implementacion.tipo_firma_editable = "digital", False
        self.implementacion.nomenclatura_pdf, self.implementacion.nomenclatura_editable = "recibo_{legajo}.pdf", False
        self.implementacion.segmentacion_liquidador, self.implementacion.segmentacion_editable = "AREA UNICA", False
        self.implementacion.save()

    def test_sin_bloqueos_el_cliente_decide_todo(self):
        self.assertEqual(self._post().status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.tipo_firma, "electronica")
        self.assertEqual(self.implementacion.nomenclatura_pdf, "mi_formato.pdf")
        self.assertEqual(self.implementacion.segmentacion_liquidador, "POR SUCURSAL")

    def test_lo_bloqueado_ignora_lo_que_mande_el_cliente(self):
        self.bloquear()
        self.assertEqual(self._post().status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.tipo_firma, "digital")
        self.assertEqual(self.implementacion.nomenclatura_pdf, "recibo_{legajo}.pdf")
        self.assertEqual(self.implementacion.segmentacion_liquidador, "AREA UNICA")

    def test_lo_bloqueado_se_muestra_deshabilitado_con_el_valor_fijo(self):
        self.bloquear()
        respuesta = self.client.get(reverse("onboarding:wizard_step", kwargs={"token": self.implementacion.token, "step": 6}))
        formulario = respuesta.context["form"]
        for campo in ("tipo_firma", "nomenclatura_pdf", "segmentacion_liquidador"):
            self.assertTrue(formulario.fields[campo].disabled, campo)
        self.assertContains(respuesta, "recibo_{legajo}.pdf")
        self.assertContains(respuesta, "Lo definió Napsis")

    def test_bloquear_solo_una_no_afecta_a_las_demas(self):
        self.implementacion.tipo_firma, self.implementacion.tipo_firma_editable = "digital", False
        self.implementacion.save()
        self._post()
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.tipo_firma, "digital")
        self.assertEqual(self.implementacion.nomenclatura_pdf, "mi_formato.pdf")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PasoConfiguracionModeloDeReciboTests(BaseWizard):
    def _post(self, archivo=None):
        datos = {"tipo_firma": "digital", "segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [self.liquidacion.pk]}
        if archivo:
            datos["modelo_recibo"] = archivo
        return self.client.post(_url(self.implementacion, 6), datos)

    def test_el_modelo_de_recibo_es_obligatorio(self):
        respuesta = self._post()
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].errors["modelo_recibo"])

    def test_tiene_que_ser_un_pdf(self):
        respuesta = self._post(SimpleUploadedFile("recibo.docx", b"x"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].errors["modelo_recibo"])

    def test_con_un_pdf_guarda_y_avanza(self):
        respuesta = self._post(SimpleUploadedFile("recibo.pdf", b"%PDF-1.4"))
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertTrue(self.implementacion.modelo_recibo)

    def test_si_ya_hay_modelo_no_hace_falta_subirlo_de_nuevo(self):
        self.implementacion.modelo_recibo.save("viejo.pdf", SimpleUploadedFile("viejo.pdf", b"%PDF-1.4"))
        respuesta = self._post()
        self.assertEqual(respuesta.status_code, 302)
