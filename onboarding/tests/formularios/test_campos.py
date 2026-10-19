"""Campos compartidos de los formularios de empresa y contacto."""

from django.test import TestCase

from onboarding.forms import (
    CAMPOS_CONFIGURACION,
    CAMPOS_DATOS_CONTACTO,
    ConfiguracionForm,
    EmpresaForm,
    ImplementacionDatosForm,
)

CAMPOS_EMPRESA = ["razon_social", "cuits"]  # viven en Cliente; se piden junto con los de contacto


class CamposCompartidosTests(TestCase):
    """ImplementacionDatosForm (panel de staff) tiene que ser exactamente la unión
    de EmpresaForm + ConfiguracionForm (los dos pasos del wizard de cliente) — si
    se agrega un campo a uno de los dos y no aparece acá, es la regresión exacta
    que este test existe para atajar."""

    def test_implementacion_datos_form_es_la_union_de_los_otros_dos(self):
        self.assertEqual(
            list(ImplementacionDatosForm().fields.keys()),
            CAMPOS_EMPRESA + CAMPOS_DATOS_CONTACTO + CAMPOS_CONFIGURACION,
        )

    def test_empresa_form_expone_exactamente_sus_campos(self):
        self.assertEqual(list(EmpresaForm().fields.keys()), CAMPOS_EMPRESA + CAMPOS_DATOS_CONTACTO)

    def test_configuracion_form_expone_exactamente_sus_campos(self):
        self.assertEqual(list(ConfiguracionForm().fields.keys()), ["tipos_liquidacion"] + CAMPOS_CONFIGURACION)

    def test_no_hay_campos_repetidos_entre_los_dos_grupos(self):
        self.assertEqual(set(CAMPOS_DATOS_CONTACTO) & set(CAMPOS_CONFIGURACION), set())
