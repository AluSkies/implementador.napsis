"""Editor de la firma del recibo: el cliente sube la imagen y la ubica; el equipo la valida, la observa o la corrige."""

import hashlib
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, UbicacionFirma
from onboarding import acciones, services
from onboarding.forms import FirmaForm
from onboarding.tests.test_imagenes import imagen
from onboarding.tests.test_wizard import BaseWizard, _url

CLIENTE = Actor.cliente("cliente_a")
ANA = Actor.implementador("ana")

GEOMETRIA = {
    "empresa": {"x": 0.1, "y": 0.7, "ancho": 0.3, "alto": 0.1},
    "conforme": {"x": 0.1, "y": 0.85, "ancho": 0.3, "alto": 0.1},
    "disconforme": {"x": 0.55, "y": 0.85, "ancho": 0.3, "alto": 0.1},
}


def datos_de_formulario(**cambios):
    datos = {"pagina": "ultima"}
    for codigo, recuadro in GEOMETRIA.items():
        for campo, valor in recuadro.items():
            datos[f"{codigo}_{campo}"] = round(valor * 100, 1)
    datos.update(cambios)
    return datos


class FormularioTests(SimpleTestCase):
    def formulario(self, archivo=None, **cambios):
        return FirmaForm(datos_de_formulario(**cambios), {"imagen": archivo} if archivo else {})

    def test_acepta_png_y_jpg_y_guarda_fracciones_de_la_pagina(self):
        for nombre in ("firma.png", "firma.jpg"):
            with self.subTest(nombre=nombre):
                formulario = self.formulario(imagen(300, 100, nombre))
                self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.geometria(), GEOMETRIA)

    def test_sin_imagen_pide_subirla(self):
        formulario = self.formulario()
        self.assertFalse(formulario.is_valid())
        self.assertIn("Subí la imagen de la firma.", formulario.errors["imagen"])

    def test_rechaza_lo_que_no_es_jpg_o_png(self):
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (300, 100), "white").save(buffer, format="GIF")
        formulario = self.formulario(SimpleUploadedFile("firma.gif", buffer.getvalue()))
        self.assertFalse(formulario.is_valid())
        self.assertIn("JPG o PNG", formulario.errors["imagen"][0])

    def test_rechaza_un_archivo_que_no_es_una_imagen(self):
        formulario = self.formulario(SimpleUploadedFile("firma.png", b"no soy una imagen"))
        self.assertFalse(formulario.is_valid())
        self.assertIn("No pudimos leer la imagen", formulario.errors["imagen"][0])

    def test_rechaza_una_imagen_de_baja_resolucion_y_dice_cuanto_mide(self):
        formulario = self.formulario(imagen(100, 30, "firma.png"))
        self.assertFalse(formulario.is_valid())
        self.assertIn("100 × 30", formulario.errors["imagen"][0])
        self.assertIn("200 × 60", formulario.errors["imagen"][0])

    def test_un_recuadro_no_puede_salirse_de_la_pagina(self):
        formulario = self.formulario(imagen(300, 100), empresa_x=80, empresa_ancho=30)
        self.assertFalse(formulario.is_valid())
        self.assertIn("Firma de la empresa: el recuadro se sale de la página.", formulario.non_field_errors())

    def test_un_recuadro_no_puede_tener_tamano_cero(self):
        formulario = self.formulario(imagen(300, 100), conforme_alto=0)
        self.assertFalse(formulario.is_valid())
        self.assertTrue(formulario.non_field_errors())

    def test_los_valores_tienen_que_estar_entre_0_y_100(self):
        formulario = self.formulario(imagen(300, 100), conforme_x=120)
        self.assertFalse(formulario.is_valid())
        self.assertIn("conforme_x", formulario.errors)


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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PasoDelWizardTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.implementacion.modelo_recibo.save("m.pdf", SimpleUploadedFile("m.pdf", b"%PDF-1.4"))

    def post(self, archivo="nueva", **cambios):
        datos = datos_de_formulario(**cambios)
        if archivo == "nueva":
            datos["imagen"] = imagen(300, 100, "firma.png")
        return self.client.post(_url(self.implementacion, services.PASO_FIRMA), datos)

    def test_sin_modelo_de_recibo_manda_a_subirlo(self):
        self.implementacion.modelo_recibo.delete()
        respuesta = self.client.get(_url(self.implementacion, services.PASO_FIRMA))
        self.assertContains(respuesta, "Subir el modelo de recibo")
        self.assertNotContains(respuesta, "firma-escenario")

    def test_muestra_el_editor_con_el_recibo_y_los_campos_de_respaldo(self):
        pagina = self.client.get(_url(self.implementacion, services.PASO_FIRMA))
        self.assertContains(pagina, "firma-escenario")
        self.assertContains(pagina, f'data-modelo="{self.implementacion.modelo_recibo.url}"')
        self.assertContains(pagina, 'name="empresa_x"')
        self.assertContains(pagina, "Ajustar con números")

    def test_guardar_bien_deja_la_firma_y_sigue_al_proximo_paso(self):
        respuesta = self.post()
        self.assertRedirects(respuesta, _url(self.implementacion, services.PASO_REVISION), fetch_redirect_response=False)
        firma = self.implementacion.firma
        self.assertEqual((firma.pagina, firma.geometria), ("ultima", GEOMETRIA))

    def test_una_imagen_chica_no_se_guarda_y_queda_registrado_por_que(self):
        respuesta = self.post(archivo=None, imagen=imagen(50, 20, "firma.png"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIsNone(self.implementacion.firma)
        evento = EventoImplementacion.objects.get(accion="validacion.fallida")
        self.assertEqual(evento.datos["paso"], services.PASO_FIRMA)
        self.assertIn("imagen", evento.datos["errores"])

    def test_si_ya_hay_firma_se_puede_guardar_sin_subir_otra_imagen(self):
        self.post()
        self.assertEqual(self.post(archivo=None, pagina="primera").status_code, 302)
        self.assertEqual(self.implementacion.firma.pagina, "primera")

    def test_el_cliente_ve_lo_que_le_observaron_en_este_paso(self):
        self.post()
        self.completar_todo()
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        acciones.observar_firma(ANA, self.implementacion, ["ilegible"], "Subila de nuevo.")
        pagina = self.client.get(_url(self.implementacion, services.PASO_FIRMA))
        self.assertContains(pagina, "Hay que ajustar la firma del recibo")
        self.assertContains(pagina, "Subila de nuevo.")

    def test_el_envio_con_la_firma_faltante_se_rechaza(self):
        self.completar_todo()
        self.implementacion.firmas.all().delete()
        self.client.post(_url(self.implementacion, services.PASO_REVISION), {"accion": "enviar"})
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)


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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PanelYArchivosTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.completar_todo()
        self.firma = self.implementacion.firma
        self.firma.estado = UbicacionFirma.ESTADO_PROPUESTA
        self.firma.save()
        self.implementacion.modelo_recibo.save("m.pdf", SimpleUploadedFile("m.pdf", b"%PDF-1.4"))
        self.ana = User.objects.create_user("ana", password="x", is_staff=True)
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def como_equipo(self):
        self.client.force_login(self.ana)

    def test_la_ficha_muestra_la_firma_con_sus_acciones(self):
        self.como_equipo()
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Firma del recibo")
        self.assertContains(pagina, "Propuesta por el cliente")
        self.assertContains(pagina, "Validar firma")
        self.assertContains(pagina, "Corregir la firma desde acá")
        self.assertContains(pagina, 'data-solo-lectura="1"')

    def test_sin_recibo_digital_la_ficha_no_muestra_la_firma(self):
        self.como_equipo()
        self.implementacion.modulos.update(activo=False)
        self.assertNotContains(self.client.get(self.url), "Firma del recibo")

    def test_validar_desde_la_ficha(self):
        self.como_equipo()
        self.client.post(self.url, {"accion": "validar_firma"})
        self.assertEqual(self.implementacion.firma.estado, "validada")
        self.assertNotContains(self.client.get(self.url), "Validar firma")

    def test_observar_desde_la_ficha(self):
        self.como_equipo()
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        self.client.post(self.url, {"accion": "observar_firma", "motivos": ["baja_calidad"], "comentario": "Está pixelada."})
        self.assertEqual(self.implementacion.firma.estado, "observada")
        self.assertEqual(self.implementacion.rondas.count(), 1)

    def test_corregir_desde_la_ficha_guarda_y_valida(self):
        self.como_equipo()
        respuesta = self.client.post(self.url, {"accion": "corregir_firma", **datos_de_formulario(empresa_x=25)})
        self.assertEqual(respuesta.status_code, 302)
        firma = self.implementacion.firma
        self.assertEqual((firma.estado, firma.geometria["empresa"]["x"], firma.validada_por), ("validada", 0.25, "ana"))

    def test_corregir_con_datos_invalidos_vuelve_con_el_error(self):
        self.como_equipo()
        respuesta = self.client.post(self.url, {"accion": "corregir_firma", **datos_de_formulario(empresa_x=95)})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "el recuadro se sale de la página")
        self.assertEqual(self.implementacion.firma.estado, "propuesta")

    def test_el_cliente_dueno_ve_su_firma_y_otro_cliente_no(self):
        ruta = reverse("media", kwargs={"ruta": self.firma.imagen.name})
        self.assertEqual(self.client.get(ruta).status_code, 200)
        ajeno = User.objects.create_user("cliente_b", password="x")
        Cliente.objects.create(nombre="Empresa B", usuario=ajeno)
        self.client.force_login(ajeno)
        self.assertEqual(self.client.get(ruta).status_code, 404)

    def test_enviada_el_cliente_ve_su_firma_en_solo_lectura(self):
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        pagina = self.client.get(_url(self.implementacion, 1))
        self.assertContains(pagina, "Así quedó ubicada la firma")
        self.assertContains(pagina, 'data-solo-lectura="1"')
