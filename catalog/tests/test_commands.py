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

    def test_no_pisa_lo_que_se_corrigio_en_el_admin(self):
        """Se corre en cada arranque: un nombre corregido no puede quedar duplicado ni lo borrado reaparecer."""
        call_command("seed_catalogos", stdout=StringIO())
        TipoLicencia.objects.filter(nombre="Vacaciones").delete()
        TipoNovedad.objects.filter(nombre="Prestamo").update(nombre="Préstamo")

        call_command("seed_catalogos", stdout=StringIO())

        self.assertFalse(TipoLicencia.objects.filter(nombre="Vacaciones").exists())
        self.assertTrue(TipoNovedad.objects.filter(nombre="Préstamo").exists())
        self.assertEqual(TipoNovedad.objects.count(), 10)

    def test_completar_agrega_lo_que_falte(self):
        call_command("seed_catalogos", stdout=StringIO())
        TipoLicencia.objects.filter(nombre="Vacaciones").delete()

        call_command("seed_catalogos", "--completar", stdout=StringIO())

        self.assertTrue(TipoLicencia.objects.filter(nombre="Vacaciones").exists())
