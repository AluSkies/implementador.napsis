import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse


class SaludTests(TestCase):
    def test_responde_ok_sin_login_cuando_hay_base(self):
        respuesta = self.client.get(reverse("salud"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {"estado": "ok"})

    def test_responde_503_si_no_llega_a_la_base(self):
        with patch("clients.views.connection.cursor", side_effect=RuntimeError("sin base")),                 self.assertLogs("django.request", "WARNING"):
            respuesta = self.client.get(reverse("salud"))
        self.assertEqual(respuesta.status_code, 503)

    def test_no_expone_datos(self):
        self.assertEqual(set(self.client.get(reverse("salud")).json()), {"estado"})


class LimiteDePedidosDeClaveTests(TestCase):
    """Un mismo mail no puede pedir el link más de una vez cada 10 minutos (para que el portal no
    sirva para llenar de mails una casilla ajena), y una IP tiene un tope general."""

    def setUp(self):
        cache.clear()
        User.objects.create_user("cli", password="clave-vieja-123", email="cli@a.com")
        self.url = reverse("clave_recuperar")

    def pedir(self, email="cli@a.com", **extra):
        return self.client.post(self.url, {"email": email}, **extra)

    def test_el_primer_pedido_manda_el_mail(self):
        self.pedir()
        self.assertEqual(len(mail.outbox), 1)

    def test_un_segundo_pedido_del_mismo_mail_no_manda_otro(self):
        self.pedir()
        respuesta = self.pedir()
        self.assertEqual(len(mail.outbox), 1)
        self.assertRedirects(respuesta, reverse("clave_enviada"))  # misma respuesta: no se revela nada

    def test_no_distingue_mayusculas_ni_espacios(self):
        self.pedir("cli@a.com")
        self.pedir(" CLI@A.COM ")
        self.assertEqual(len(mail.outbox), 1)

    def test_pasados_los_10_minutos_se_puede_volver_a_pedir(self):
        self.pedir()
        cache.clear()  # equivale a que venza la ventana
        self.pedir()
        self.assertEqual(len(mail.outbox), 2)

    def test_la_ventana_es_de_10_minutos(self):
        from clients.views import RecuperarClaveView

        self.assertEqual(RecuperarClaveView.VENTANA_SEGUNDOS, 600)

    def test_otro_mail_no_se_ve_afectado(self):
        User.objects.create_user("otro", password="clave-vieja-123", email="otro@a.com")
        self.pedir("cli@a.com")
        self.pedir("otro@a.com")
        self.assertEqual(len(mail.outbox), 2)

    def test_una_misma_ip_tiene_un_tope_de_pedidos(self):
        for i in range(12):
            User.objects.create_user(f"u{i}", password="clave-vieja-123", email=f"u{i}@a.com")
            self.pedir(f"u{i}@a.com", REMOTE_ADDR="1.2.3.4")
        self.assertEqual(len(mail.outbox), 10)

    def test_ips_distintas_no_comparten_el_tope(self):
        for i in range(3):
            User.objects.create_user(f"u{i}", password="clave-vieja-123", email=f"u{i}@a.com")
        with patch("clients.views.RecuperarClaveView.MAXIMO_POR_IP", 1):
            for i in range(3):
                self.pedir(f"u{i}@a.com", REMOTE_ADDR=f"1.2.3.{i}")
        self.assertEqual(len(mail.outbox), 3)

    def test_un_mail_desconocido_tambien_gasta_el_cupo_sin_revelar_nada(self):
        self.assertRedirects(self.pedir("nadie@a.com"), reverse("clave_enviada"))
        self.assertEqual(mail.outbox, [])


class SuperusuarioInicialTests(TestCase):
    """Una contraseña de ejemplo ("cambiar") no puede quedar de admin en un panel expuesto a internet."""

    def correr(self, password):
        entorno = {"DJANGO_SUPERUSER_USERNAME": "admin_prod", "DJANGO_SUPERUSER_PASSWORD": password}
        with patch.dict(os.environ, entorno):
            call_command("ensure_superuser", stdout=StringIO())

    def test_rechaza_una_contrasena_de_ejemplo_o_debil(self):
        for debil in ("cambiar", "12345678", "password"):
            with self.subTest(password=debil):
                with self.assertRaises(CommandError):
                    self.correr(debil)
        self.assertFalse(User.objects.filter(username="admin_prod").exists())

    def test_acepta_una_contrasena_razonable(self):
        self.correr("una-clave-larga-9XqT")
        self.assertTrue(User.objects.get(username="admin_prod").is_superuser)
