from django.test import TestCase
from django.utils import timezone

from clients.models import (
    Cliente,
    Implementacion,
    ImplementacionLicencia,
    ImplementacionNovedad,
    ImplementacionTipoDocumento,
    PersonaRol,
    Sucursal,
)


class EstadoVisualTests(TestCase):
    """estado_visual es un derivado de estado + enviado, no un campo propio —
    estos tests fijan las 4 combinaciones para que un cambio en la propiedad
    no rompa silenciosamente el filtro del panel (filtro_visual usa las mismas
    combinaciones vía Q())."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")

    def _crear(self, **kwargs):
        return Implementacion.objects.create(cliente=self.cliente, **kwargs)

    def test_pendiente_sin_enviar_es_a_completar(self):
        imp = self._crear()
        self.assertEqual(imp.estado_visual, Implementacion.VISUAL_A_COMPLETAR)

    def test_pendiente_enviado_es_completado_cliente(self):
        imp = self._crear(enviado=timezone.now())
        self.assertEqual(imp.estado_visual, Implementacion.VISUAL_COMPLETADO_CLIENTE)

    def test_cumplida_es_completo_sin_importar_enviado(self):
        imp = self._crear(estado=Implementacion.ESTADO_CUMPLIDA, enviado=timezone.now())
        self.assertEqual(imp.estado_visual, Implementacion.VISUAL_COMPLETO)

    def test_cancelada_es_cancelada_sin_importar_enviado(self):
        imp = self._crear(estado=Implementacion.ESTADO_CANCELADA, enviado=timezone.now())
        self.assertEqual(imp.estado_visual, Implementacion.VISUAL_CANCELADA)

    def test_filtro_visual_encuentra_lo_mismo_que_la_propiedad(self):
        """Regresión: filtro_visual() es la versión "a nivel DB" de estado_visual —
        si alguna vez se desincronizan, el panel filtra mal sin que nada más lo note."""
        a_completar = self._crear()
        completado_cliente = self._crear(enviado=timezone.now())
        completo = self._crear(estado=Implementacion.ESTADO_CUMPLIDA)
        cancelada = self._crear(estado=Implementacion.ESTADO_CANCELADA)

        for imp, clave in [
            (a_completar, Implementacion.VISUAL_A_COMPLETAR),
            (completado_cliente, Implementacion.VISUAL_COMPLETADO_CLIENTE),
            (completo, Implementacion.VISUAL_COMPLETO),
            (cancelada, Implementacion.VISUAL_CANCELADA),
        ]:
            encontrados = Implementacion.objects.filter(Implementacion.filtro_visual(clave))
            self.assertIn(imp, encontrados, f"{clave} no encontró a su propia implementación")
            for otra_clave in Implementacion.VISUAL_LABELS:
                if otra_clave != clave:
                    otros = Implementacion.objects.filter(Implementacion.filtro_visual(otra_clave))
                    self.assertNotIn(imp, otros, f"{clave} apareció también bajo {otra_clave}")


class TransicionesDeEstadoTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def test_anular_marca_cancelada_y_fecha(self):
        self.implementacion.anular()
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CANCELADA)
        self.assertIsNotNone(self.implementacion.cancelada_en)

    def test_marcar_cumplida_marca_cumplida_y_fecha(self):
        self.implementacion.marcar_cumplida()
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)
        self.assertIsNotNone(self.implementacion.cumplida_en)

    def test_pedir_revision_guarda_mensaje_y_limpia_atencion_previa(self):
        self.implementacion.revision_atendida_en = timezone.now()
        self.implementacion.save(update_fields=["revision_atendida_en"])

        self.implementacion.pedir_revision("Necesito ayuda con la firma digital")
        self.implementacion.refresh_from_db()

        self.assertTrue(self.implementacion.revision_solicitada)
        self.assertEqual(self.implementacion.revision_mensaje, "Necesito ayuda con la firma digital")
        self.assertIsNotNone(self.implementacion.revision_solicitada_en)
        self.assertIsNone(self.implementacion.revision_atendida_en)

    def test_marcar_revision_atendida_setea_fecha(self):
        self.implementacion.pedir_revision("Algo")
        self.implementacion.marcar_revision_atendida()
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.revision_atendida_en)


class ModelosMovidosDesdeOnboardingTests(TestCase):
    """PersonaRol/Sucursal/ImplementacionLicencia/Novedad/TipoDocumento viven todos
    en clients (ImplementacionLicencia/Novedad/TipoDocumento se movieron acá desde
    onboarding). Este test es la red de seguridad de esa migración: si alguna vez
    se revierte a medias, esto falla en vez de romper recién en producción."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def test_los_cinco_modelos_pertenecen_a_clients(self):
        for modelo in (PersonaRol, Sucursal, ImplementacionLicencia, ImplementacionNovedad, ImplementacionTipoDocumento):
            self.assertEqual(modelo._meta.app_label, "clients")

    def test_persona_rol_se_puede_crear_y_relacionar(self):
        rol = PersonaRol.objects.create(
            implementacion=self.implementacion, rol=PersonaRol.ROL_LIQUIDADOR,
            apellido_nombre="Pérez, Juan", cuil="20111111112",
        )
        self.assertIn(rol, self.implementacion.roles.all())

    def test_sucursal_se_puede_crear_y_relacionar(self):
        sucursal = Sucursal.objects.create(implementacion=self.implementacion, nombre="Casa Central")
        self.assertIn(sucursal, self.implementacion.sucursales.all())
