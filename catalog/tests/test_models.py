from django.test import TestCase

from catalog.models import CampoDocumento, TipoDocumento, TipoLicencia, TipoNovedad
from clients.models import Cliente, Implementacion, Modulo


class BaseDeTestSinCatalogoSembradoTests(TestCase):
    """El catálogo real (16 licencias, 10 novedades, etc.) se carga con
    `manage.py seed_catalogos`/`seed_modulos`, NO con una migración — si
    volviera a vivir en una migración, este test empieza a fallar porque
    `manage.py test` arma la base de test corriendo todas las migraciones."""

    def test_no_hay_licencias_novedades_documentos_ni_modulos_sembrados(self):
        self.assertEqual(TipoLicencia.objects.count(), 0)
        self.assertEqual(TipoNovedad.objects.count(), 0)
        self.assertEqual(TipoDocumento.objects.filter(implementacion=None).count(), 0)
        self.assertEqual(Modulo.objects.count(), 0)


class OrdenamientoDeCatalogosTests(TestCase):
    """Los catálogos se muestran siempre en el orden fijo relevado en los Excel
    originales (campo `orden`), no alfabético — si Meta.ordering se rompe, el
    checklist del wizard se reordena solo sin que nadie lo haya tocado."""

    def test_tipo_licencia_se_ordena_por_campo_orden(self):
        # Ya hay catálogo global seedeado por una migración de datos — se filtra
        # a solo estos dos para no depender de su contenido ni de su orden.
        TipoLicencia.objects.create(nombre="Z Licencia de Prueba", orden=902)
        TipoLicencia.objects.create(nombre="A Licencia de Prueba", orden=901)
        nombres = list(
            TipoLicencia.objects.filter(nombre__endswith="Licencia de Prueba").values_list("nombre", flat=True)
        )
        self.assertEqual(nombres, ["A Licencia de Prueba", "Z Licencia de Prueba"])

    def test_tipo_novedad_se_ordena_por_campo_orden(self):
        TipoNovedad.objects.create(nombre="Z Novedad de Prueba", orden=902)
        TipoNovedad.objects.create(nombre="A Novedad de Prueba", orden=901)
        nombres = list(
            TipoNovedad.objects.filter(nombre__endswith="Novedad de Prueba").values_list("nombre", flat=True)
        )
        self.assertEqual(nombres, ["A Novedad de Prueba", "Z Novedad de Prueba"])


class TipoDocumentoCustomTests(TestCase):
    """implementacion=None es catálogo global; seteado es un tipo 'Otros' propio de
    una sola implementación — mezclar esto es la forma en que un cliente vería (o
    no) documentos de otro cliente."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def test_tipo_global_no_tiene_implementacion(self):
        tipo = TipoDocumento.objects.create(nombre="Documento de Prueba")
        self.assertIsNone(tipo.implementacion)
        self.assertFalse(tipo.es_custom)

    def test_tipo_custom_queda_asociado_a_una_sola_implementacion(self):
        tipo = TipoDocumento.objects.create(
            nombre="Certificado de matrimonio", implementacion=self.implementacion, es_custom=True,
        )
        self.assertIn(tipo, self.implementacion.tipos_documento_custom.all())

    def test_str_incluye_el_documento_y_el_campo(self):
        tipo = TipoDocumento.objects.create(nombre="Documento de Prueba")
        campo = CampoDocumento.objects.create(tipo_documento=tipo, nombre="Número")
        self.assertEqual(str(campo), "Documento de Prueba · Número")
