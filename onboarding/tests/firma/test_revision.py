"""El equipo valida u observa la firma."""

import tempfile

from django.core import mail
from django.test import override_settings

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import UbicacionFirma
from onboarding import acciones, services
from onboarding.tests.base import GEOMETRIA, BaseWizard

CLIENTE = Actor.cliente("cliente_a")
ANA = Actor.implementador("ana")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RevisionDelEquipoTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.implementacion.mail_contacto = "cliente@empresa.com"
        self.implementacion.save()
        self.completar_todo()
        self.firma = self.implementacion.firma
        self.firma.estado = UbicacionFirma.ESTADO_PROPUESTA
        self.firma.save()
        acciones.enviar_relevamiento(CLIENTE, self.implementacion, None)
        self.implementacion.refresh_from_db()
        mail.outbox.clear()

    def test_validar_la_deja_validada_con_quien_y_cuando(self):
        resultado = acciones.validar_firma(ANA, self.implementacion)
        self.assertTrue(resultado.ok)
        firma = self.implementacion.firma
        self.assertEqual((firma.estado, firma.validada_por), ("validada", "ana"))
        self.assertIsNotNone(firma.validada_en)
        self.assertTrue(EventoImplementacion.objects.filter(accion="firma.validada", actor_ref="ana").exists())

    def test_sin_firma_no_hay_nada_que_validar(self):
        self.implementacion.firmas.all().delete()
        resultado = acciones.validar_firma(ANA, self.implementacion)
        self.assertEqual(resultado.avisos[0].texto, "Todavía no hay una firma cargada para validar.")

    def test_no_se_aprueba_para_configurar_con_la_firma_sin_validar(self):
        resultado = acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertIsNone(self.implementacion.validada_en)
        self.assertIn("Falta validar la firma del recibo.", resultado.avisos[0].texto)

    def test_con_la_firma_validada_si_se_aprueba(self):
        acciones.validar_firma(ANA, self.implementacion)
        self.assertTrue(acciones.aprobar_para_configurar(ANA, self.implementacion).ok)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.validada_en)

    def test_observarla_registra_motivos_la_devuelve_y_avisa_al_cliente(self):
        acciones.observar_firma(ANA, self.implementacion, ["ilegible", "superpone_texto", "inventado"], "Se pisa con el CUIL.")
        self.implementacion.refresh_from_db()
        firma = self.implementacion.firma
        self.assertEqual((firma.estado, firma.motivos, firma.comentario), ("observada", ["ilegible", "superpone_texto"], "Se pisa con el CUIL."))
        self.assertIsNone(self.implementacion.enviado)
        ronda = self.implementacion.rondas.get()
        self.assertEqual(ronda.numero, 1)
        self.assertIn("la firma no se lee bien", ronda.observaciones["firma"])
        self.assertIn("Se pisa con el CUIL.", ronda.observaciones["firma"])
        evento = EventoImplementacion.objects.get(accion="firma.observada")
        self.assertEqual(evento.datos["motivos"], ["ilegible", "superpone_texto"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Se pisa con el CUIL.", mail.outbox[0].body)

    def test_hay_que_elegir_al_menos_un_motivo_del_catalogo(self):
        for motivos in ([], ["inventado"]):
            with self.subTest(motivos=motivos):
                resultado = acciones.observar_firma(ANA, self.implementacion, motivos)
                self.assertEqual(resultado.avisos[0].texto, "Elegí al menos un motivo de la lista.")
        self.assertEqual(self.implementacion.rondas.count(), 0)
        self.assertEqual(self.implementacion.firma.estado, "propuesta")

    def test_el_cliente_responde_y_la_firma_vuelve_a_ser_propuesta(self):
        acciones.observar_firma(ANA, self.implementacion, ["ilegible"])
        services.guardar_firma(self.implementacion, CLIENTE, pagina="primera", geometria=GEOMETRIA)
        self.assertEqual(self.implementacion.firma.estado, "propuesta")
        self.assertEqual(self.implementacion.firma.motivos, [])

    def test_los_motivos_son_un_catalogo_cerrado_con_codigos_estables(self):
        self.assertEqual(
            [codigo for codigo, _ in UbicacionFirma.MOTIVOS],
            ["ilegible", "baja_calidad", "tamano_excesivo", "superpone_texto", "no_replicable", "otro"],
        )
