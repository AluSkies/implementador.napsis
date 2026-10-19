"""Catálogo de tipos de liquidación."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from catalog.models import TipoLicencia, TipoLiquidacion


class CatalogoDeLiquidacionesTests(TestCase):
    def test_el_seed_carga_los_diez_tipos_en_el_orden_del_wizard_de_napsis(self):
        call_command("seed_catalogos", stdout=StringIO())
        self.assertEqual(
            list(TipoLiquidacion.objects.values_list("nombre", flat=True)),
            ["Liquidación Normal", "Aguinaldo", "Anticipos", "Formulario 1357", "Ajustes", "Liquidación Final",
             "Primera Quincena", "Segunda Quincena", "Gratificación - Bono", "Formulario 1357 Anual"],
        )
        self.assertEqual(TipoLiquidacion.objects.get(nombre="Aguinaldo").codigo, "aguinaldo")

    def test_no_pisa_lo_corregido_en_el_admin(self):
        call_command("seed_catalogos", stdout=StringIO())
        TipoLiquidacion.objects.filter(codigo="anticipos").update(nombre="Anticipos de sueldo")
        call_command("seed_catalogos", stdout=StringIO())
        call_command("seed_catalogos", "--completar", stdout=StringIO())
        self.assertEqual(TipoLiquidacion.objects.count(), 10)
        self.assertEqual(TipoLiquidacion.objects.get(codigo="anticipos").nombre, "Anticipos de sueldo")

    def test_vacaciones_queda_marcada_como_automatica(self):
        call_command("seed_catalogos", stdout=StringIO())
        self.assertEqual(
            list(TipoLicencia.objects.filter(automatica=True).values_list("nombre", flat=True)), ["Vacaciones"],
        )
