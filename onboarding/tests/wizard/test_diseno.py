"""El diseño del wizard: pasos en el panel lateral, aclaraciones en un «?» y lo opcional en un desplegable."""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from onboarding.tests.base import BaseWizard, _url


class PanelDePasosTests(BaseWizard):
    modulos = ["Recibo Digital", "Legajos"]

    def barra(self, paso):
        return self.client.get(_url(self.implementacion, paso)).context["pasos_barra"]

    def test_marca_el_actual_los_hechos_y_los_pendientes(self):
        self.implementacion.paso_actual = 4
        self.implementacion.save()
        estados = {p["numero"]: p["estado"] for p in self.barra(4)}
        self.assertEqual((estados[1], estados[2], estados[4], estados[5]), ("hecho", "hecho", "actual", "pendiente"))

    def test_solo_se_puede_volver_a_lo_que_ya_se_alcanzo(self):
        self.implementacion.paso_actual = 4
        self.implementacion.save()
        enlaces = {p["numero"]: bool(p["url"]) for p in self.barra(4)}
        self.assertTrue(enlaces[1] and enlaces[2] and enlaces[4])
        self.assertFalse(enlaces[5])

    def test_ir_para_atras_no_pierde_lo_alcanzado(self):
        self.implementacion.paso_actual = 6
        self.implementacion.save()
        estados = {p["numero"]: p["estado"] for p in self.barra(2)}
        self.assertEqual((estados[2], estados[5]), ("actual", "hecho"))

    def test_los_pasos_que_no_aplican_no_aparecen(self):
        numeros = [p["numero"] for p in self.barra(1)]
        self.assertNotIn(3, numeros)  # Sucursales: solo con Fichada

    def test_la_pagina_dibuja_el_panel(self):
        pagina = self.client.get(_url(self.implementacion, 1)).content.decode()
        self.assertIn("wizard-lateral", pagina)
        self.assertIn('aria-current="step"', pagina)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PasoDeConfiguracionDisenoTests(BaseWizard):
    def pagina(self):
        return self.client.get(_url(self.implementacion, 6)).content.decode()

    def test_las_aclaraciones_van_en_un_signo_de_pregunta(self):
        pagina = self.pagina()
        self.assertIn('class="ayuda"', pagina)
        self.assertIn("Digital requiere token físico ENCODE", pagina)
        self.assertNotIn('<p class="helptext"', pagina)

    def test_banner_y_logo_van_en_un_desplegable_opcional(self):
        pagina = self.pagina()
        desplegable = pagina.split('<details class="desplegable"')[1].split("</details>")[0]
        self.assertIn("(OPCIONAL)", desplegable)
        self.assertIn('name="banner"', desplegable)
        self.assertIn('name="logo"', desplegable)
        self.assertNotIn('name="modelo_recibo"', desplegable)

    def test_el_desplegable_arranca_cerrado_salvo_que_haya_un_error_en_sus_campos(self):
        self.assertNotRegex(self.pagina(), r'<details class="desplegable"[^>]*\bopen\b')
        respuesta = self.client.post(_url(self.implementacion, 6), {
            "tipo_firma": "digital", "segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [self.liquidacion.pk],
            "modelo_recibo": SimpleUploadedFile("m.pdf", b"%PDF-1.4"),
            "banner": SimpleUploadedFile("b.png", b"no es una imagen", content_type="image/png"),
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertRegex(respuesta.content.decode(), r'<details class="desplegable"[^>]*\bopen\b')


class PasoDeRolesDisenoTests(BaseWizard):
    def test_cada_persona_tiene_su_boton_quitar_y_la_casilla_queda_oculta(self):
        pagina = self.client.get(_url(self.implementacion, 5)).content.decode()
        self.assertEqual(pagina.count("data-persona-quitar"), 6)
        casillas = pagina.split("data-quitar-casilla")[1:]
        self.assertEqual(len(casillas), 6)
        self.assertTrue(all(c.lstrip().startswith("hidden") for c in casillas))


class SeleccionarTodasTests(BaseWizard):
    """Los checklists ofrecen «Seleccionar todas» (el botón lo arma static/seleccionar_todas.js)."""

    modulos = ["Recibo Digital", "Legajos", "Novedades"]

    def pagina(self, paso):
        return self.client.get(_url(self.implementacion, paso)).content.decode()

    def test_liquidaciones_de_la_configuracion(self):
        self.assertIn('data-seleccionable="todas"', self.pagina(6))

    def test_documentos_sin_limite(self):
        self.assertIn('data-seleccionable="todos"', self.pagina(9))

    def test_documentos_con_limite_no_ofrecen_marcar_todos(self):
        self.implementacion.max_documentos = 3
        self.implementacion.save()
        self.assertNotIn("data-seleccionable", self.pagina(9))

    def test_licencias_y_novedades_cada_una_con_el_suyo(self):
        self.assertEqual(self.pagina(8).count('data-seleccionable="todas"'), 2)

    def test_modulos(self):
        self.assertIn('data-seleccionable="todos"', self.pagina(2))

    def test_la_pagina_carga_el_script(self):
        self.assertIn("seleccionar_todas.js", self.pagina(2))
