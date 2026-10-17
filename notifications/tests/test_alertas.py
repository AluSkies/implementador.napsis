import io
import logging

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import path

from notifications.alertas import AlertaErrorHandler


def vista_que_falla(request):
    raise ValueError("algo se rompió")


def vista_que_falla_distinto(request):
    raise KeyError("otra cosa")


urlpatterns = [
    path("falla/", vista_que_falla),
    path("falla-distinto/", vista_que_falla_distinto),
]


@override_settings(ROOT_URLCONF="notifications.tests.test_alertas", ERROR_ALERT_EMAILS=["dev@napsislatam.com"])
class AlertaDeErrorPorMailTests(TestCase):
    """Un 500 le avisa al equipo por mail, una vez cada 10 minutos por tipo de error."""

    def setUp(self):
        cache.clear()
        self.client.raise_request_exception = False
        # El traceback también sale por consola: se desvía para que no ensucie la salida de los
        # tests. (No sirve assertLogs: reemplaza los handlers y el de la alerta no se ejecutaría.)
        for handler in logging.getLogger("django.request").handlers:
            if type(handler) is logging.StreamHandler:
                original = handler.setStream(io.StringIO())
                self.addCleanup(handler.setStream, original)

    def fallar(self, url="/falla/"):
        return self.client.get(url)

    def test_un_500_manda_un_mail_con_el_error_y_donde_ocurrio(self):
        respuesta = self.fallar()
        self.assertEqual(respuesta.status_code, 500)
        self.assertEqual(len(mail.outbox), 1)
        alerta = mail.outbox[0]
        self.assertEqual(alerta.to, ["dev@napsislatam.com"])
        self.assertIn("ValueError", alerta.subject)
        self.assertIn("/falla/", alerta.subject)
        self.assertIn("algo se rompió", alerta.body)
        self.assertIn("vista_que_falla", alerta.body)  # el traceback

    def test_el_mismo_error_repetido_no_manda_un_mail_por_pedido(self):
        for _ in range(5):
            self.fallar()
        self.assertEqual(len(mail.outbox), 1)

    def test_un_error_distinto_si_avisa(self):
        self.fallar()
        self.fallar("/falla-distinto/")
        self.assertEqual(len(mail.outbox), 2)

    def test_pasados_los_10_minutos_vuelve_a_avisar(self):
        self.fallar()
        cache.clear()
        self.fallar()
        self.assertEqual(len(mail.outbox), 2)

    def test_incluye_al_usuario_pero_no_los_datos_del_pedido(self):
        usuario = User.objects.create_user("ana", password="x")
        self.client.force_login(usuario)
        self.client.post("/falla/", {"cuil": "20111111112", "password": "secreta-123"})
        cuerpo = mail.outbox[0].body
        self.assertIn("Usuario: ana", cuerpo)
        self.assertNotIn("20111111112", cuerpo)
        self.assertNotIn("secreta-123", cuerpo)

    @override_settings(ERROR_ALERT_EMAILS=[])
    def test_sin_destinatarios_no_manda_nada(self):
        self.fallar()
        self.assertEqual(mail.outbox, [])

    def test_si_falla_el_envio_del_aviso_no_empeora_el_error(self):
        from unittest.mock import patch

        with patch("django.core.mail.send_mail", side_effect=OSError("SMTP caído")):
            with self.assertLogs("notifications.alertas", level="WARNING"):
                respuesta = self.fallar()
        self.assertEqual(respuesta.status_code, 500)

    def test_los_errores_que_no_son_500_no_avisan(self):
        with self.assertLogs("django.request", level="WARNING"):
            self.client.get("/no-existe/")
        self.assertEqual(mail.outbox, [])


class ConfiguracionDeLaAlertaTests(SimpleTestCase):
    def test_django_request_esta_conectado_al_handler(self):
        from django.conf import settings

        self.assertIn("alerta_mail", settings.LOGGING["loggers"]["django.request"]["handlers"])
        self.assertTrue(any(isinstance(h, AlertaErrorHandler) for h in logging.getLogger("django.request").handlers))

    @override_settings(ERROR_ALERT_EMAILS=["dev@napsislatam.com"])
    def test_un_registro_sin_excepcion_se_ignora(self):
        registro = logging.LogRecord("django.request", logging.ERROR, "x.py", 1, "mensaje", None, None)
        AlertaErrorHandler().emit(registro)
        self.assertEqual(mail.outbox, [])
