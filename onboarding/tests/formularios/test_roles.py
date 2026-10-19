"""Formulario de roles."""

from django.test import TestCase

from onboarding.forms import (
    RolForm,
)


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
