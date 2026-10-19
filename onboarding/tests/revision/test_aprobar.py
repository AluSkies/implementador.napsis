"""Validar la documentación para configurar."""

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Implementacion
from onboarding import acciones
from onboarding.tests.base import EnviadaBase

ANA = Actor.implementador("ana")


class AprobarTests(EnviadaBase):
    def test_deja_la_fecha_y_el_evento(self):
        resultado = acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertTrue(resultado.ok)
        self.assertIsNotNone(self.implementacion.validada_en)
        evento = EventoImplementacion.objects.get(accion="estado.validada")
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("implementador", "ana"))

    def test_no_se_valida_lo_que_el_cliente_no_envio(self):
        self.implementacion.enviado = None
        self.implementacion.save()
        resultado = acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertIsNone(self.implementacion.validada_en)
        self.assertEqual(len(resultado.avisos), 1)
        self.assertFalse(EventoImplementacion.objects.filter(accion="estado.validada").exists())

    def test_no_se_valida_dos_veces(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertEqual(EventoImplementacion.objects.filter(accion="estado.validada").count(), 1)

    def test_si_despues_del_envio_falta_algo_no_se_valida(self):
        self.implementacion.empleados.all().delete()
        resultado = acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertIsNone(self.implementacion.validada_en)
        self.assertIn("No se puede validar", resultado.avisos[0].texto)

    def test_reabrir_borra_la_validacion(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        acciones.reabrir(ANA, self.implementacion)
        self.assertIsNone(self.implementacion.validada_en)
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_A_COMPLETAR)
