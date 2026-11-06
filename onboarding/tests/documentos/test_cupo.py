"""Documentos del legajo: el equipo puede fijar cuántos tipos puede elegir el cliente (0 = sin límite)."""

from catalog.models import CampoDocumento, TipoDocumento
from onboarding.forms import CondicionesForm
from onboarding.tests.base import BaseWizard, _url


class CupoDeDocumentosTests(BaseWizard):
    modulos = ["Recibo Digital", "Legajos"]

    def setUp(self):
        super().setUp()
        self.tipos = []
        for i in range(4):
            tipo = TipoDocumento.objects.create(nombre=f"Documento {i}")
            CampoDocumento.objects.create(tipo_documento=tipo, nombre="Número")
            self.tipos.append(tipo)

    def pagina(self):
        return self.client.get(_url(self.implementacion, 9))

    def post(self, cantidad, otros=""):
        datos = {"otros_documentos": otros}
        datos.update({f"tipo_{t.id}_activo": "on" for t in self.tipos[:cantidad]})
        return self.client.post(_url(self.implementacion, 9), datos)

    def fijar(self, maximo):
        self.implementacion.max_documentos = maximo
        self.implementacion.save()

    def activos(self):
        return self.implementacion.documentos_legajo.filter(activo=True).count()

    def test_sin_maximo_puede_elegir_todos(self):
        self.assertEqual(self.post(4).status_code, 302)
        self.assertEqual(self.activos(), 4)

    def test_con_maximo_la_pagina_lo_informa_al_script(self):
        self.fijar(3)
        self.assertContains(self.pagina(), 'data-maximo="3"')

    def test_dentro_del_maximo_guarda(self):
        self.fijar(3)
        self.assertEqual(self.post(3).status_code, 302)
        self.assertEqual(self.activos(), 3)

    def test_pasarse_del_maximo_no_guarda_y_lo_explica(self):
        self.fijar(2)
        respuesta = self.post(3)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Podés elegir hasta 2 documentos y elegiste 3")
        self.assertEqual(self.activos(), 0)

    def test_los_otros_documentos_cuentan_para_el_maximo(self):
        self.fijar(2)
        respuesta = self.post(2, otros="Certificado de matrimonio: Fecha de emisión, Adjunto")
        self.assertContains(respuesta, "Podés elegir hasta 2 documentos y elegiste 3")

    def test_una_linea_sin_campos_no_cuenta(self):
        self.fijar(2)
        self.assertEqual(self.post(2, otros="Sin campos:\nsolo texto").status_code, 302)


class CondicionDeDocumentosTests(BaseWizard):
    def test_el_formulario_de_condiciones_la_guarda(self):
        form = CondicionesForm({"max_documentos": "5"})
        self.assertTrue(form.is_valid(), form.errors)
        form.aplicar(self.implementacion)
        self.assertEqual(self.implementacion.max_documentos, 5)

    def test_vacio_o_cero_es_sin_limite(self):
        for valor in ("", "0"):
            with self.subTest(valor=valor):
                form = CondicionesForm({"max_documentos": valor})
                self.assertTrue(form.is_valid(), form.errors)
                form.aplicar(self.implementacion)
                self.assertEqual(self.implementacion.max_documentos, 0)

    def test_no_acepta_negativos(self):
        self.assertFalse(CondicionesForm({"max_documentos": "-1"}).is_valid())

    def test_la_ficha_la_muestra_ya_cargada(self):
        self.implementacion.max_documentos = 4
        self.assertEqual(CondicionesForm(implementacion=self.implementacion).initial["max_documentos"], 4)
