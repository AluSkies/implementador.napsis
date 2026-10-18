"""Lo que el cliente no pudo completar queda registrado."""

from automatizacion.models import EventoImplementacion
from onboarding.tests.base import BaseWizard, _url


def _eventos(accion):
    return EventoImplementacion.objects.filter(accion=accion)


class ValidacionesDelWizardQuedanRegistradasTests(BaseWizard):
    """Lo que el cliente no pudo completar queda como dato (solo qué falló, no lo que escribió)."""

    def url(self, paso):
        return _url(self.implementacion, paso)

    def test_un_paso_con_errores_registra_los_campos_que_fallaron(self):
        self.client.post(self.url(1), {"razon_social": "", "cuits": "123", "telefono": "011-1"})
        errores = _eventos("validacion.fallida").get().datos
        self.assertEqual(errores["paso"], 1)
        self.assertIn("razon_social", errores["errores"])
        self.assertIn("cuits", errores["errores"])
        self.assertNotIn("011-1", str(errores))  # los valores cargados no se guardan

    def test_intentar_enviar_con_pendientes_registra_cuales(self):
        self.client.post(self.url(10), {"accion": "enviar"})
        datos = _eventos("validacion.fallida").get().datos
        self.assertEqual(datos["paso"], 10)
        self.assertTrue(datos["errores"]["pendientes"])
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)

    def test_un_archivo_roto_registra_el_motivo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.post(self.url(4), {"accion": "importar", "archivo": SimpleUploadedFile("n.xlsx", b"roto")})
        datos = _eventos("validacion.fallida").get().datos
        self.assertEqual(datos["paso"], 4)
        self.assertIn("No pudimos leer el archivo", datos["errores"]["archivo"][0])

    def test_un_alta_manual_invalida_tambien(self):
        self.client.post(self.url(4), {"accion": "agregar_manual", "cuil": "123", "nombre": "A", "apellido": "B"})
        self.assertIn("cuil", _eventos("validacion.fallida").get().datos["errores"])

    def test_guardar_bien_un_paso_deja_el_evento_de_paso_guardado_del_cliente(self):
        self.client.post(self.url(1), {
            "razon_social": "Empresa A S.A.", "cuits": "30-50001091-2", "telefono": "011-1", "mail_contacto": "a@a.com",
        })
        evento = _eventos("paso.guardado").get()
        self.assertEqual((evento.actor_tipo, evento.seccion, evento.post_envio), ("cliente", "datos_contacto", False))
        self.assertFalse(_eventos("validacion.fallida").exists())

    def test_el_envio_del_cliente_deja_su_evento_con_el_actor_cliente(self):
        self.completar_todo()
        self.client.post(self.url(10), {"accion": "enviar", "fecha_salida_productivo": ""})
        evento = _eventos("envio.confirmado").get()
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("cliente", self.usuario.username))
