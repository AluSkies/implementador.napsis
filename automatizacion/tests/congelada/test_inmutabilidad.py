"""La configuración congelada no se modifica ni se borra."""

import tempfile
from pathlib import Path

from django.test import override_settings

from automatizacion.actores import Actor
from automatizacion.models import (
    ConfiguracionCongelada,
    CongeladaInmutable,
    EventoImplementacion,
)
from onboarding import acciones
from onboarding.tests.base import EnviadaBase

ANA = Actor.implementador("ana")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class InmutabilidadTests(EnviadaBase):
    def setUp(self):
        super().setUp()
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.congelada = self.implementacion.congeladas.get()

    def test_no_se_modifica(self):
        self.congelada.contenido = {}
        with self.assertRaises(CongeladaInmutable):
            self.congelada.save()
        with self.assertRaises(CongeladaInmutable):
            ConfiguracionCongelada.objects.update(hash="x")
        with self.assertRaises(CongeladaInmutable):
            ConfiguracionCongelada.objects.bulk_update([self.congelada], ["hash"])

    def test_no_se_borra(self):
        with self.assertRaises(CongeladaInmutable):
            self.congelada.delete()
        with self.assertRaises(CongeladaInmutable):
            ConfiguracionCongelada.objects.all().delete()

    def test_sobrevive_a_la_implementacion(self):
        uuid = self.implementacion.uuid
        self.implementacion.delete()
        self.assertEqual(ConfiguracionCongelada.objects.get(implementacion_uuid=uuid).version, 1)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SinCongelarTests(EnviadaBase):
    def test_si_falta_algo_no_se_valida_ni_se_congela(self):
        self.implementacion.empleados.all().delete()
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertFalse(self.implementacion.congeladas.exists())

    def test_si_un_archivo_no_se_puede_leer_no_se_valida_y_no_queda_nada_a_medias(self):
        Path(self.implementacion.modelo_recibo.path).unlink()
        resultado = acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertIn("modelo_recibo", resultado.avisos[0].texto)
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.validada_en)
        self.assertFalse(self.implementacion.congeladas.exists())
        self.assertFalse(EventoImplementacion.objects.filter(accion="estado.validada").exists())

    def test_devolver_o_reabrir_no_borra_lo_ya_congelado(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        acciones.devolver_al_cliente(ANA, self.implementacion, "Revisá algo")
        acciones.reabrir(ANA, self.implementacion)
        self.assertEqual(self.implementacion.congeladas.count(), 1)
