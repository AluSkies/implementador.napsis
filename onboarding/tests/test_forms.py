from django.test import TestCase

from onboarding.forms import (
    CAMPOS_CONFIGURACION,
    CAMPOS_DATOS_CONTACTO,
    ConfiguracionForm,
    EmpresaForm,
    ImplementacionDatosForm,
    RolForm,
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


class RolFormTests(TestCase):
    def test_requiere_rol_si_se_cargo_un_nombre(self):
        form = RolForm({"rol": "", "apellido_nombre": "Pérez, Juan", "cuil": "", "mail": ""})
        self.assertFalse(form.is_valid())

    def test_fila_completamente_vacia_es_valida_se_ignora_despues(self):
        """Así es como el formset trata las filas "extra" sin tocar (empty_permitted=True) —
        sin esto, el ChoiceField "rol" (required) rechazaría cualquier fila en blanco."""
        form = RolForm(
            {"rol": "", "apellido_nombre": "", "cuil": "", "mail": ""},
            empty_permitted=True, use_required_attribute=False,
        )
        self.assertTrue(form.is_valid())

    def test_fila_con_rol_y_nombre_es_valida(self):
        form = RolForm({"rol": "apoderado", "apellido_nombre": "Pérez, Juan", "cuil": "", "mail": ""})
        self.assertTrue(form.is_valid())
