"""Formulario de tipos de liquidación."""

from django.test import TestCase

from catalog.models import TipoLiquidacion
from clients.models import Cliente, Implementacion, ImplementacionLiquidacion
from onboarding.forms import LiquidacionesForm


class FormularioTests(TestCase):
    def setUp(self):
        self.normal = TipoLiquidacion.objects.create(nombre="Liquidación Normal")
        self.aguinaldo = TipoLiquidacion.objects.create(nombre="Aguinaldo")

    def test_hay_que_elegir_al_menos_uno(self):
        formulario = LiquidacionesForm({})
        self.assertFalse(formulario.is_valid())
        self.assertIn("al menos un tipo de liquidación", formulario.errors["tipos_liquidacion"][0])

    def test_acepta_uno_o_varios(self):
        self.assertTrue(LiquidacionesForm({"tipos_liquidacion": [self.normal.pk, self.aguinaldo.pk]}).is_valid())

    def test_parte_de_lo_ya_elegido(self):
        implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
        ImplementacionLiquidacion.objects.create(implementacion=implementacion, tipo_liquidacion=self.aguinaldo, activo=True)
        ImplementacionLiquidacion.objects.create(implementacion=implementacion, tipo_liquidacion=self.normal, activo=False)
        formulario = LiquidacionesForm(implementacion=implementacion)
        self.assertEqual(formulario.fields["tipos_liquidacion"].initial, [self.aguinaldo.pk])
