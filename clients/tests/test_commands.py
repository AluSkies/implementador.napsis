from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from clients.models import Modulo


class SeedModulosCommandTests(TestCase):
    def test_carga_el_catalogo_de_modulos(self):
        call_command("seed_modulos", stdout=StringIO())
        nombres = set(Modulo.objects.values_list("nombre", flat=True))
        self.assertEqual(nombres, {"Recibo Digital", "Comunicación", "Fichada", "Legajos", "Novedades"})

    def test_correrlo_dos_veces_no_duplica_nada(self):
        call_command("seed_modulos", stdout=StringIO())
        call_command("seed_modulos", stdout=StringIO())
        self.assertEqual(Modulo.objects.count(), 5)
