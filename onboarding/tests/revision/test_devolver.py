"""Devolver al cliente y rondas de revisión."""

from django.core import mail
from django.urls import reverse

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Implementacion
from onboarding import acciones
from onboarding.tests.base import EnviadaBase, _url

ANA = Actor.implementador("ana")
CLIENTE = Actor.cliente("cliente_a")


class DevolverTests(EnviadaBase):
    def test_abre_la_ronda_y_la_saca_del_envio(self):
        resultado = self.devolver(observaciones={"nomina": "Falta el personal de la sucursal Rosario."})
        self.assertTrue(resultado.ok)
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_A_COMPLETAR)
        self.assertEqual(self.implementacion.marca_de_devolucion, "Devuelta, ronda 1")
        ronda = self.implementacion.rondas.get()
        self.assertEqual((ronda.numero, ronda.devuelta_por), (1, "ana"))
        self.assertEqual(ronda.observaciones, {"nomina": "Falta el personal de la sucursal Rosario."})

    def test_tambien_se_puede_devolver_una_ya_validada(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.devolver()
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.validada_en)

    def test_sin_motivo_no_se_devuelve(self):
        resultado = self.devolver(motivo="   ")
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)
        self.assertEqual(self.implementacion.rondas.count(), 0)
        self.assertEqual(len(resultado.avisos), 1)

    def test_lo_que_no_se_envio_no_se_devuelve(self):
        self.devolver()
        self.devolver(motivo="otra vez")  # ya está en manos del cliente
        self.assertEqual(self.implementacion.rondas.count(), 1)

    def test_descarta_observaciones_vacias_o_de_pasos_que_no_existen(self):
        self.devolver(observaciones={"nomina": "  ", "roles": "Falta el liquidador.", "inventado": "x"})
        self.assertEqual(self.implementacion.rondas.get().observaciones, {"roles": "Falta el liquidador."})

    def test_deja_el_evento_con_el_motivo(self):
        self.devolver()
        evento = EventoImplementacion.objects.get(accion="ronda.devuelta")
        self.assertEqual(evento.datos["ronda"], 1)
        self.assertEqual(evento.datos["motivo"], "Faltan los legajos del personal nuevo.")
        self.assertTrue(evento.post_envio)

    def test_le_avisa_al_cliente_por_mail(self):
        self.devolver(observaciones={"roles": "Falta el liquidador."})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["cliente@empresa.com"])
        self.assertIn("Faltan los legajos del personal nuevo.", mail.outbox[0].body)
        self.assertIn("Falta el liquidador.", mail.outbox[0].body)
        self.assertIn(self.implementacion.token, mail.outbox[0].body)

    def test_si_el_mail_falla_queda_devuelta_igual(self):
        from unittest import mock

        with mock.patch("onboarding.acciones.notificaciones.notificar_cliente_devuelta", side_effect=OSError), \
                self.assertLogs("onboarding.acciones", level="ERROR"):
            resultado = self.devolver()
        self.assertEqual(self.implementacion.rondas.count(), 1)
        self.assertEqual(resultado.avisos[-1].texto, "Quedó devuelta, pero no se pudo avisarle al cliente por mail.")
        self.assertTrue(EventoImplementacion.objects.filter(accion="mail.fallido").exists())


class RespuestaDelClienteTests(EnviadaBase):
    def test_al_volver_a_enviar_se_cierra_la_ronda(self):
        self.devolver()
        acciones.enviar_relevamiento(CLIENTE, self.implementacion, None)
        self.implementacion.refresh_from_db()
        ronda = self.implementacion.rondas.get()
        self.assertEqual(ronda.respondida_en, self.implementacion.enviado)
        self.assertEqual(self.implementacion.marca_de_devolucion, "")
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_COMPLETADO_CLIENTE)
        envio = EventoImplementacion.objects.filter(accion="envio.confirmado").last()
        self.assertEqual(envio.datos["ronda"], 1)

    def test_una_segunda_devolucion_es_la_ronda_2(self):
        self.devolver()
        acciones.enviar_relevamiento(CLIENTE, self.implementacion, None)
        self.devolver(motivo="Falta el modelo de recibo firmado.")
        self.assertEqual(self.implementacion.marca_de_devolucion, "Devuelta, ronda 2")
        self.assertEqual(list(self.implementacion.rondas.values_list("numero", flat=True)), [1, 2])

    def test_el_cliente_puede_editar_de_nuevo_y_ve_lo_que_le_pidieron(self):
        self.devolver(observaciones={"roles": "Falta el liquidador."})
        pagina = self.client.get(_url(self.implementacion, 5))  # roles
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "ronda 1")
        self.assertContains(pagina, "Faltan los legajos del personal nuevo.")
        self.assertContains(pagina, "Falta el liquidador.")

    def test_la_observacion_de_otro_paso_no_se_muestra(self):
        self.devolver(observaciones={"roles": "Falta el liquidador."})
        self.assertNotContains(self.client.get(_url(self.implementacion, 1)), "Falta el liquidador.")

    def test_sin_devolucion_no_hay_cartel(self):
        self.implementacion.enviado = None
        self.implementacion.save()
        self.assertNotContains(self.client.get(_url(self.implementacion, 1)), "te devolvió el relevamiento")

    def test_mis_implementaciones_muestra_la_marca(self):
        self.devolver()
        self.assertContains(self.client.get(reverse("onboarding:mis_implementaciones")), "Devuelta, ronda 1")
