"""Paso de configuración y adjuntos."""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from onboarding.forms import ConfiguracionForm
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


class CantidadDeCapitasTests(BaseWizard):
    """Si el cliente no indica las cápitas, valen la suma de su nómina."""

    def formulario(self, **datos):
        base = {"tipo_firma": "digital", "segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [self.liquidacion.pk]}
        archivos = {"modelo_recibo": SimpleUploadedFile("m.pdf", b"%PDF-1.4")}
        return ConfiguracionForm({**base, **datos}, archivos, instance=self.implementacion)

    def cargar_nomina(self, cantidad):
        for i in range(cantidad):
            self.agregar_empleado(f"2000000000{i}"[:11], f"N{i}", f"A{i}")

    def test_viene_precargada_con_la_cantidad_de_empleados_de_la_nomina(self):
        self.cargar_nomina(3)
        formulario = ConfiguracionForm(instance=self.implementacion)
        self.assertEqual(formulario.initial["cantidad_capitas"], 3)
        self.assertIn("(3)", formulario.fields["cantidad_capitas"].help_text)

    def test_si_se_deja_vacia_se_guarda_la_suma_de_la_nomina(self):
        self.cargar_nomina(4)
        formulario = self.formulario(cantidad_capitas="")
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.cleaned_data["cantidad_capitas"], 4)

    def test_si_el_cliente_indica_otra_cantidad_se_respeta(self):
        self.cargar_nomina(4)
        formulario = self.formulario(cantidad_capitas="40")
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.cleaned_data["cantidad_capitas"], 40)

    def test_sin_nomina_cargada_queda_vacia(self):
        formulario = self.formulario(cantidad_capitas="")
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertIsNone(formulario.cleaned_data["cantidad_capitas"])
        self.assertIn("una vez cargada", formulario.fields["cantidad_capitas"].help_text)

    def test_un_valor_ya_guardado_no_se_pisa_con_la_nomina(self):
        self.cargar_nomina(3)
        self.implementacion.cantidad_capitas = 25
        self.implementacion.save()
        self.assertEqual(ConfiguracionForm(instance=self.implementacion).initial["cantidad_capitas"], 25)

    def test_la_pantalla_la_muestra_precargada(self):
        self.cargar_nomina(3)
        pagina = self.client.get(_url(self.implementacion, 6)).content.decode()
        self.assertIn('name="cantidad_capitas" value="3"', pagina)
