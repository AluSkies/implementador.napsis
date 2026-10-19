"""Versiones y huella de la configuración congelada."""

import json
import tempfile

from django.test import override_settings

from automatizacion.actores import Actor
from automatizacion.congelada import contenido_de, hash_de
from automatizacion.models import ConfiguracionCongelada
from onboarding import acciones, services
from onboarding.tests.base import EnviadaBase

ANA = Actor.implementador("ana")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VersionesTests(EnviadaBase):
    def aprobar(self):
        self.assertTrue(acciones.aprobar_para_configurar(ANA, self.implementacion).ok)
        return self.implementacion.congeladas.order_by("-version").first()

    def test_volver_a_aprobar_lo_mismo_da_otra_version_con_la_misma_huella(self):
        primera = self.aprobar()
        services.guardar_liquidaciones(self.implementacion, [], ANA)  # revoca la validación
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], ANA)
        segunda = self.aprobar()
        self.assertEqual((segunda.version, segunda.hash), (2, primera.hash))
        self.assertEqual(self.implementacion.congeladas.count(), 2)
        self.assertTrue(segunda.archivos[0]["ruta"].startswith(f"congeladas/{self.implementacion.uuid}/v2/"))

    def test_si_cambia_lo_aprobado_cambia_la_huella(self):
        primera = self.aprobar()
        self.implementacion.cliente.razon_social = "Nombre Nuevo S.A."
        self.implementacion.cliente.save()
        services.guardar_liquidaciones(self.implementacion, [], ANA)
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], ANA)
        self.assertNotEqual(self.aprobar().hash, primera.hash)

    def test_la_version_anterior_queda_intacta(self):
        primera = self.aprobar()
        contenido = json.loads(json.dumps(primera.contenido))
        services.guardar_liquidaciones(self.implementacion, [], ANA)
        self.implementacion.cliente.razon_social = "Otra"
        self.implementacion.cliente.save()
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], ANA)
        self.aprobar()
        self.assertEqual(ConfiguracionCongelada.objects.get(pk=primera.pk).contenido, contenido)

    def test_la_huella_depende_del_contenido_y_de_los_archivos_pero_no_de_las_rutas(self):
        contenido = {"a": 1}
        uno = [{"campo": "logo", "sha256": "aa", "ruta": "x/1"}]
        otro = [{"campo": "logo", "sha256": "aa", "ruta": "y/2"}]
        self.assertEqual(hash_de(contenido, uno), hash_de(contenido, otro))
        self.assertNotEqual(hash_de(contenido, uno), hash_de({"a": 2}, uno))
        self.assertNotEqual(hash_de(contenido, uno), hash_de(contenido, [{"campo": "logo", "sha256": "bb"}]))

    def test_el_orden_del_contenido_es_estable(self):
        self.agregar_empleado("20888888881", "A", "A")
        self.assertEqual(json.dumps(contenido_de(self.implementacion), sort_keys=True),
                         json.dumps(contenido_de(self.implementacion), sort_keys=True))
