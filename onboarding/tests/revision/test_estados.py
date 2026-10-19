"""Estados visibles de la implementación."""

from automatizacion.actores import Actor
from clients.models import Implementacion
from clients.services import filtrar_y_ordenar_implementaciones
from onboarding import acciones
from onboarding.tests.base import EnviadaBase

ANA = Actor.implementador("ana")


class EstadosVisualesTests(EnviadaBase):
    def test_recien_enviada_espera_validacion(self):
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_COMPLETADO_CLIENTE)
        self.assertEqual(self.implementacion.estado_visual_label, "Documentación completa - Pendiente de validación")

    def test_al_validarla_queda_pendiente_de_configurar(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_VALIDADA)
        self.assertEqual(self.implementacion.estado_visual_label, "Validada - Pendiente de configurar")

    def test_el_filtro_distingue_pendiente_de_validacion_y_validada(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        validada = Implementacion.objects.filter(Implementacion.filtro_visual(Implementacion.VISUAL_VALIDADA))
        sin_validar = Implementacion.objects.filter(Implementacion.filtro_visual(Implementacion.VISUAL_COMPLETADO_CLIENTE))
        self.assertEqual(list(validada), [self.implementacion])
        self.assertEqual(list(sin_validar), [])

    def test_el_listado_ordena_los_estados_en_su_orden_natural(self):
        otra = Implementacion.objects.create(cliente=self.cliente)
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        orden = filtrar_y_ordenar_implementaciones(Implementacion.objects.all(), {"ordenar": "estado"})
        self.assertEqual(list(orden), [otra, self.implementacion])
