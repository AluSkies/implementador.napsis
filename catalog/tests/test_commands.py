from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from catalog.models import CampoDocumento, TipoDocumento, TipoLicencia, TipoNovedad


class SeedCatalogosCommandTests(TestCase):
    def test_carga_licencias_novedades_y_documentos_con_sus_campos(self):
        call_command("seed_catalogos", stdout=StringIO())

        self.assertEqual(TipoLicencia.objects.count(), 16)
        self.assertEqual(TipoNovedad.objects.count(), 10)
        self.assertEqual(TipoDocumento.objects.filter(implementacion=None).count(), 16)
        self.assertTrue(CampoDocumento.objects.filter(tipo_documento__nombre="DNI").exists())

    def test_correrlo_dos_veces_no_duplica_nada(self):
        call_command("seed_catalogos", stdout=StringIO())
        call_command("seed_catalogos", stdout=StringIO())

        self.assertEqual(TipoLicencia.objects.count(), 16)
        self.assertEqual(TipoNovedad.objects.count(), 10)
        self.assertEqual(TipoDocumento.objects.filter(implementacion=None).count(), 16)
