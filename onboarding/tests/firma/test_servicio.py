"""Guardado de la firma, archivos y eventos."""

import hashlib
import tempfile
from pathlib import Path

from django.test import override_settings

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from onboarding import acciones, services
from onboarding.tests.base import GEOMETRIA, BaseWizard, imagen

CLIENTE = Actor.cliente("cliente_a")
ANA = Actor.implementador("ana")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ServicioTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.implementacion.mail_contacto = "cliente@empresa.com"
        self.implementacion.save()

    def guardar(self, actor=CLIENTE, archivo="nueva", **cambios):
        argumentos = {"pagina": "primera", "geometria": GEOMETRIA}
        if archivo == "nueva":
            argumentos["imagen"] = imagen(300, 100, "firma.png")
        argumentos.update(cambios)
        return services.guardar_firma(self.implementacion, actor, **argumentos)

    def test_la_primera_vez_queda_propuesta_con_su_evento_y_su_historial(self):
        firma = self.guardar()
        self.assertEqual((firma.estado, firma.propuesta_por), ("propuesta", "Cliente"))
        self.assertEqual(firma.imagen_sha256, hashlib.sha256(firma.imagen.read()).hexdigest())
        evento = EventoImplementacion.objects.get(accion="firma.propuesta")
        self.assertEqual((evento.actor_tipo, evento.seccion, evento.post_envio), ("cliente", "firma", False))
        self.assertEqual(evento.datos["cambios"]["Firma de la empresa"]["despues"]["x"], 0.1)
        self.assertTrue(self.implementacion.versiones.filter(seccion="firma").exists())

    def test_reemplazar_la_imagen_no_borra_la_anterior_y_deja_las_dos_en_el_evento(self):
        primera = self.guardar()
        ruta_anterior, hash_anterior = primera.imagen.name, primera.imagen_sha256
        segunda = self.guardar(imagen=imagen(400, 150, "otra.png"))
        self.assertNotEqual(segunda.imagen.name, ruta_anterior)
        self.assertTrue(Path(primera.imagen.storage.path(ruta_anterior)).is_file())
        evento = EventoImplementacion.objects.get(accion="archivo.reemplazado")
        self.assertEqual(evento.datos["anterior"], {"ruta": ruta_anterior, "sha256": hash_anterior})
        self.assertEqual(evento.datos["nuevo"]["sha256"], segunda.imagen_sha256)
        self.assertNotEqual(hash_anterior, segunda.imagen_sha256)

    def test_guardar_otra_vez_sin_cambios_no_pierde_la_validacion(self):
        self.guardar()
        acciones.validar_firma(ANA, self.implementacion)
        self.guardar(archivo=None)
        self.assertEqual(self.implementacion.firma.estado, "validada")

    def test_si_el_cliente_cambia_algo_la_firma_vuelve_a_ser_propuesta(self):
        self.guardar()
        acciones.validar_firma(ANA, self.implementacion)
        self.guardar(archivo=None, pagina="ultima")
        firma = self.implementacion.firma
        self.assertEqual((firma.estado, firma.validada_por, firma.validada_en), ("propuesta", "", None))

    def test_si_estaba_observada_cualquier_guardado_del_cliente_es_su_respuesta(self):
        self.guardar()
        firma = self.implementacion.firma
        firma.estado, firma.motivos = "observada", ["ilegible"]
        firma.save()
        self.guardar(archivo=None)
        firma = self.implementacion.firma
        self.assertEqual((firma.estado, firma.motivos), ("propuesta", []))

    def test_la_correccion_del_equipo_queda_validada_y_registrada_como_posterior_al_envio(self):
        self.guardar()
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        corregida = {**GEOMETRIA, "empresa": {"x": 0.2, "y": 0.6, "ancho": 0.3, "alto": 0.1}}
        firma = self.guardar(actor=ANA, archivo=None, geometria=corregida)
        self.assertEqual((firma.estado, firma.validada_por), ("validada", "ana"))
        evento = EventoImplementacion.objects.get(accion="firma.corregida_por_implementador")
        self.assertTrue(evento.post_envio)
        self.assertEqual(evento.actor_ref, "ana")
        cambios = evento.datos["cambios"]
        self.assertEqual(cambios["Firma de la empresa › x"], {"antes": 0.1, "despues": 0.2})

    def test_sin_firma_el_control_de_faltantes_la_pide(self):
        mensajes = [(p["paso"], p["mensaje"]) for p in services.pendientes_de_envio(self.implementacion)]
        self.assertIn((services.PASO_FIRMA, "Subir la imagen de la firma y ubicarla sobre el recibo."), mensajes)

    def test_con_la_firma_cargada_deja_de_pedirla(self):
        self.guardar()
        pasos = [p["paso"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertNotIn(services.PASO_FIRMA, pasos)

    def test_sin_recibo_digital_no_hay_paso_de_firma(self):
        self.implementacion.modulos.update(activo=False)
        self.assertNotIn(services.PASO_FIRMA, services.pasos_activos(self.implementacion))
        self.assertNotIn(services.PASO_FIRMA, [p["paso"] for p in services.pendientes_de_envio(self.implementacion)])
