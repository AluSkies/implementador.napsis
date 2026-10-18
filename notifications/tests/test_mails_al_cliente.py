import re
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from clients.models import Cliente, Implementacion
from dashboard.tests.test_asignado import BasePanel
from onboarding.tests.test_wizard import BaseWizard, _url

CLAVE = "una-clave-larga-9XqT"


def _link(cuerpo):
    return re.search(r"https?://\S+/clave/nueva/\S+", cuerpo).group(0)


class InvitacionAlCrearTests(BasePanel):
    """Con mail del cliente en el alta, el cliente crea su propia contraseña por link."""

    def test_con_mail_manda_la_invitacion_y_no_genera_contrasena(self):
        self.crear(nombre="Empresa Nueva", username="nueva", mail_cliente="gerencia@nueva.com")
        usuario = User.objects.get(username="nueva")
        self.assertFalse(usuario.has_usable_password())
        self.assertEqual(usuario.email, "gerencia@nueva.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["gerencia@nueva.com"])
        self.assertIn("nueva", mail.outbox[0].body)  # el usuario va en el mail

    def test_no_muestra_ninguna_contrasena_en_pantalla(self):
        respuesta = self.crear(nombre="Empresa Nueva", mail_cliente="gerencia@nueva.com", follow=True) \
            if False else self.crear(nombre="Empresa Nueva", mail_cliente="gerencia@nueva.com")
        pagina = self.client.get(respuesta.url)
        self.assertNotContains(pagina, "contraseña:")
        self.assertContains(pagina, "gerencia@nueva.com")

    def test_el_mail_queda_precargado_en_los_datos_de_contacto(self):
        self.crear(nombre="Empresa Nueva", mail_cliente="gerencia@nueva.com")
        self.assertEqual(Implementacion.objects.get().mail_contacto, "gerencia@nueva.com")

    def test_el_link_permite_crear_la_contrasena_y_ingresar(self):
        self.crear(nombre="Empresa Nueva", username="nueva", mail_cliente="gerencia@nueva.com")
        link = _link(mail.outbox[0].body)
        cliente_web = self.client_class()
        pagina = cliente_web.get(link, follow=True)  # Django redirige al formulario con el token en sesión
        self.assertContains(pagina, "Creá tu contraseña")
        cliente_web.post(pagina.redirect_chain[-1][0], {"new_password1": CLAVE, "new_password2": CLAVE})
        self.assertEqual(cliente_web.post(reverse("login"), {"username": "nueva", "password": CLAVE}).status_code, 302)

    def test_el_link_se_puede_usar_una_sola_vez(self):
        self.crear(nombre="Empresa Nueva", username="nueva", mail_cliente="gerencia@nueva.com")
        link = _link(mail.outbox[0].body)
        web = self.client_class()
        formulario = web.get(link, follow=True).redirect_chain[-1][0]
        web.post(formulario, {"new_password1": CLAVE, "new_password2": CLAVE})
        self.assertContains(self.client_class().get(link, follow=True), "El link no es válido")

    def test_sin_mail_sigue_mostrando_la_contrasena_generada(self):
        respuesta = self.crear(nombre="Empresa Nueva", username="nueva")
        self.assertEqual(mail.outbox, [])
        self.assertTrue(User.objects.get(username="nueva").has_usable_password())
        self.assertContains(self.client.get(respuesta.url), "contraseña: ")

    def test_un_mail_invalido_no_crea_nada_y_avisa_en_el_modal(self):
        respuesta = self.crear(nombre="Empresa Nueva", mail_cliente="esto-no-es-un-mail")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "El mail del cliente no es válido")
        self.assertFalse(Cliente.objects.exists())

    def test_si_falla_el_envio_igual_se_crea_y_avisa(self):
        with patch("onboarding.acciones.notificaciones.enviar_invitacion", side_effect=OSError("SMTP caído")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                respuesta = self.crear(nombre="Empresa Nueva", username="nueva", mail_cliente="gerencia@nueva.com")
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Implementacion.objects.exists())
        self.assertContains(self.client.get(respuesta.url), "No se pudo enviar el mail")

    def test_el_mail_es_obligatorio_solo_si_se_quiere_invitar_a_un_cliente_nuevo(self):
        existente = Cliente.objects.create(nombre="Ya tiene", usuario=self.cliente_user)
        self.crear(cliente_id=str(existente.pk), mail_cliente="otro@ya.com")
        self.assertEqual(mail.outbox, [])  # ya tenía cuenta: no se la toca


class ReenvioDesdeLaFichaTests(BasePanel):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(nombre="Empresa A", usuario=self.cliente_user)
        self.implementacion = Implementacion.objects.create(cliente=self.cliente, mail_contacto="contacto@a.com")
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_reenvia_al_mail_de_contacto_y_lo_guarda_en_la_cuenta(self):
        self.client.post(self.url, {"accion": "enviar_invitacion"})
        self.assertEqual(mail.outbox[0].to, ["contacto@a.com"])
        self.cliente_user.refresh_from_db()
        self.assertEqual(self.cliente_user.email, "contacto@a.com")

    def test_no_cambia_la_contrasena_actual(self):
        self.client.post(self.url, {"accion": "enviar_invitacion"})
        self.cliente_user.refresh_from_db()
        self.assertTrue(self.cliente_user.check_password("x"))

    def test_sin_ningun_mail_avisa_y_no_manda_nada(self):
        self.implementacion.mail_contacto = ""
        self.implementacion.save()
        self.client.post(self.url, {"accion": "enviar_invitacion"})
        self.assertEqual(mail.outbox, [])
        self.assertContains(self.client.get(self.url), "No hay un mail cargado")

    def test_desde_la_ficha_se_puede_crear_el_acceso_con_invitacion(self):
        self.cliente.usuario = None
        self.cliente.save()
        self.client.post(self.url, {"accion": "regenerar_acceso", "username": "nuevo", "mail_cliente": "x@a.com"})
        self.assertEqual(mail.outbox[0].to, ["x@a.com"])
        self.assertFalse(User.objects.get(username="nuevo").has_usable_password())


class RecuperarContrasenaTests(TestCase):
    def setUp(self):
        cache.clear()  # el límite de pedidos usa la caché: no puede arrastrarse de un test a otro
        self.usuario = User.objects.create_user("cli", password="clave-vieja-123", email="cli@a.com")

    def test_el_login_ofrece_recuperar_la_contrasena(self):
        self.assertContains(self.client.get(reverse("login")), reverse("clave_recuperar"))

    def test_manda_el_link_y_con_el_se_cambia_la_clave(self):
        self.client.post(reverse("clave_recuperar"), {"email": "CLI@a.com"})  # no distingue mayúsculas
        self.assertEqual(len(mail.outbox), 1)
        web = self.client_class()
        formulario = web.get(_link(mail.outbox[0].body), follow=True).redirect_chain[-1][0]
        web.post(formulario, {"new_password1": CLAVE, "new_password2": CLAVE})
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(CLAVE))

    def test_un_mail_desconocido_responde_igual_y_no_manda_nada(self):
        respuesta = self.client.post(reverse("clave_recuperar"), {"email": "nadie@a.com"})
        self.assertRedirects(respuesta, reverse("clave_enviada"))
        self.assertEqual(mail.outbox, [])

    def test_alcanza_a_un_cliente_invitado_que_todavia_no_creo_su_clave(self):
        User.objects.create_user("nuevo", password=None, email="nuevo@a.com")
        self.client.post(reverse("clave_recuperar"), {"email": "nuevo@a.com"})
        self.assertEqual(len(mail.outbox), 1)

    def test_una_cuenta_dada_de_baja_no_recibe_nada(self):
        self.usuario.is_active = False
        self.usuario.save()
        self.client.post(reverse("clave_recuperar"), {"email": "cli@a.com"})
        self.assertEqual(mail.outbox, [])

    def test_un_link_alterado_no_sirve(self):
        self.client.post(reverse("clave_recuperar"), {"email": "cli@a.com"})
        roto = _link(mail.outbox[0].body)[:-4] + "xxxx/"
        self.assertContains(self.client.get(roto, follow=True), "El link no es válido")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ConfirmacionesAlClienteTests(BaseWizard):
    def _enviar(self):
        return self.client.post(_url(self.implementacion, 9), {"accion": "enviar"})

    def test_al_enviar_el_relevamiento_el_cliente_recibe_la_confirmacion(self):
        self.implementacion.mail_contacto = "contacto@a.com"
        self.implementacion.save()
        self.completar_todo()
        self._enviar()
        para_cliente = [m for m in mail.outbox if m.to == ["contacto@a.com"]]
        self.assertEqual(len(para_cliente), 1)
        self.assertEqual(para_cliente[0].subject, "Recibimos tu información")
        self.assertIn("Empresa A S.A.", para_cliente[0].body)

    def test_si_no_hay_mail_del_cliente_no_manda_nada_y_el_envio_funciona(self):
        self.completar_todo()
        self._enviar()
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)
        self.assertFalse([m for m in mail.outbox if m.subject == "Recibimos tu información"])

    def test_si_falla_la_confirmacion_el_cliente_igual_queda_enviado(self):
        self.implementacion.mail_contacto = "contacto@a.com"
        self.implementacion.save()
        self.completar_todo()
        with patch("onboarding.acciones.notificaciones.notificar_cliente_relevamiento_recibido", side_effect=OSError("SMTP")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                respuesta = self._enviar()
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)

    def test_si_falla_el_aviso_de_contacto_el_cliente_no_ve_un_error(self):
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        with patch("onboarding.acciones.notificaciones.notificar_revision_solicitada", side_effect=OSError("SMTP")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                respuesta = self.client.post(_url(self.implementacion, 1), {"accion": "pedir_revision", "mensaje": "hola"})
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertTrue(self.implementacion.revision_solicitada)


class AvisoDeImplementacionCumplidaTests(BasePanel):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(nombre="Empresa A", razon_social="Empresa A S.A.", usuario=self.cliente_user)
        self.implementacion = Implementacion.objects.create(cliente=self.cliente, mail_contacto="contacto@a.com")
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_al_marcarla_cumplida_le_avisa_al_cliente(self):
        self.client.post(self.url, {"accion": "marcar_cumplida"})
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)
        self.assertEqual([m.subject for m in mail.outbox], ["Tu implementación está lista"])
        self.assertEqual(mail.outbox[0].to, ["contacto@a.com"])

    def test_usa_el_mail_de_la_cuenta_si_la_implementacion_no_tiene(self):
        self.implementacion.mail_contacto = ""
        self.implementacion.save()
        self.cliente_user.email = "cuenta@a.com"
        self.cliente_user.save()
        self.client.post(self.url, {"accion": "marcar_cumplida"})
        self.assertEqual(mail.outbox[0].to, ["cuenta@a.com"])

    def test_si_falla_igual_queda_cumplida_y_se_avisa_al_equipo(self):
        with patch("onboarding.acciones.notificaciones.notificar_cliente_implementacion_cumplida", side_effect=OSError("SMTP")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                self.client.post(self.url, {"accion": "marcar_cumplida"})
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)
        self.assertContains(self.client.get(self.url), "no se pudo avisarle al cliente")

    def test_anular_no_manda_nada_al_cliente(self):
        self.implementacion.anular()
        self.assertEqual(mail.outbox, [])


class MailsEnTextoPlanoTests(TestCase):
    """Los mails son texto plano: un "&" o un apóstrofo tienen que verse tal cual, no como &amp; / &#x27;."""

    def test_la_razon_social_no_sale_con_entidades_html(self):
        cliente = Cliente.objects.create(nombre="Pérez & Hijos", razon_social="Pérez & Hijos S.R.L. - D'Angelo")
        implementacion = Implementacion.objects.create(cliente=cliente, mail_contacto="c@a.com")
        from notifications.services import notificar_cliente_implementacion_cumplida, notificar_cliente_relevamiento_recibido

        notificar_cliente_relevamiento_recibido(implementacion)
        notificar_cliente_implementacion_cumplida(implementacion)
        for enviado in mail.outbox:
            self.assertIn("Pérez & Hijos S.R.L. - D'Angelo", enviado.body)
            self.assertNotIn("&amp;", enviado.body)
            self.assertNotIn("&#x27;", enviado.body)

    def test_el_mail_de_recuperar_tampoco(self):
        User.objects.create_user("o'brien", password="x", email="ob@a.com")
        cache.clear()
        self.client.post(reverse("clave_recuperar"), {"email": "ob@a.com"})
        self.assertIn("o'brien", mail.outbox[0].body)
        self.assertNotIn("&#x27;", mail.outbox[0].body)
