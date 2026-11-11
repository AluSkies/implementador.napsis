"""Endurecimientos de seguridad: cómo se sirven los archivos subidos, dónde viajan las credenciales recién generadas,
qué se guarda en el caché y la mitigación de pdf.js."""

import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ServidoDeArchivosTests(TestCase):
    """Un archivo que el navegador interprete como página, servido desde nuestro dominio, tendría acceso a la sesión de
    quien lo abra (el equipo abre archivos que suben los clientes). Solo imágenes y PDF se muestran; lo demás se descarga."""

    def setUp(self):
        self.admin = User.objects.create_user("admin_t", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def pedir(self, nombre, contenido=b"contenido"):
        ruta = default_storage.save(f"implementaciones/otros/{nombre}", ContentFile(contenido))
        return self.client.get(reverse("media", kwargs={"ruta": ruta}))

    def test_una_pagina_se_descarga_y_no_se_muestra(self):
        for nombre in ("firma.html", "firma.htm", "firma.svg", "firma.xhtml", "firma.js", "firma.txt", "firma"):
            with self.subTest(nombre=nombre):
                respuesta = self.pedir(nombre, b"<script>alert(1)</script>")
                self.assertEqual(respuesta["Content-Type"], "application/octet-stream")
                self.assertTrue(respuesta["Content-Disposition"].startswith("attachment"))

    def test_las_imagenes_se_muestran_con_su_tipo_y_una_politica_que_no_ejecuta_nada(self):
        for nombre, tipo in (("a.png", "image/png"), ("a.jpg", "image/jpeg"), ("a.jpeg", "image/jpeg"), ("a.PNG", "image/png")):
            with self.subTest(nombre=nombre):
                respuesta = self.pedir(nombre)
                self.assertEqual(respuesta["Content-Type"], tipo)
                self.assertIn("sandbox", respuesta["Content-Security-Policy"])
                self.assertIn("default-src 'none'", respuesta["Content-Security-Policy"])

    def test_el_pdf_se_muestra_como_pdf_sin_la_politica_que_rompe_el_visor(self):
        respuesta = self.pedir("modelo.pdf", b"%PDF-1.4")
        self.assertEqual(respuesta["Content-Type"], "application/pdf")
        self.assertNotIn("attachment", respuesta.get("Content-Disposition", ""))
        self.assertFalse(respuesta.has_header("Content-Security-Policy"))

    def test_el_navegador_no_adivina_el_tipo(self):
        self.assertEqual(self.pedir("a.png")["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.pedir("a.html")["X-Content-Type-Options"], "nosniff")


class CredencialesYCacheTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin_t", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def test_los_avisos_se_guardan_en_la_sesion_y_no_en_una_cookie(self):
        self.assertTrue(settings.MESSAGE_STORAGE.endswith("session.SessionStorage"))

    def test_la_contrasena_recien_generada_no_viaja_en_una_cookie(self):
        respuesta = self.client.post(reverse("dashboard:implementadores"), {
            "username": "nueva", "first_name": "Nora", "last_name": "Paz", "email": "n@napsislatam.com", "rol": "implementador",
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertNotIn("messages", respuesta.cookies)
        # y se muestra una sola vez, en la página siguiente
        pagina = self.client.get(respuesta.url)
        self.assertContains(pagina, "contraseña: ")
        self.assertNotContains(self.client.get(respuesta.url), "contraseña: ")

    def test_lo_que_ve_alguien_con_sesion_no_se_guarda_en_el_cache(self):
        cabecera = self.client.get(reverse("dashboard:home"))["Cache-Control"]
        for parte in ("no-cache", "no-store", "private"):
            self.assertIn(parte, cabecera)

    def test_una_pagina_publica_sin_sesion_no_cambia(self):
        self.client.logout()
        self.assertNotIn("no-store", self.client.get(reverse("landing")).get("Cache-Control", ""))

    def test_no_pisa_la_politica_que_ya_traiga_la_respuesta(self):
        from django.http import HttpResponse
        from django.test import RequestFactory

        from clients.security import SinCacheConSesionMiddleware

        pedido = RequestFactory().get("/x")
        pedido.user = self.admin
        propia = SinCacheConSesionMiddleware(lambda r: HttpResponse("ok", headers={"Cache-Control": "max-age=60"}))(pedido)
        self.assertEqual(propia["Cache-Control"], "max-age=60")


class Pdfjs3_11Tests(SimpleTestCase):
    """CVE-2024-4367: pdf.js 3.11 (el que viaja con el repositorio) ejecuta código de un PDF armado a propósito si deja
    activa la evaluación de fuentes. El modelo de recibo lo sube el cliente y lo abre el equipo."""

    def test_el_editor_abre_los_pdf_sin_evaluar_fuentes(self):
        editor = (Path(settings.BASE_DIR) / "static" / "firma_editor.js").read_text(encoding="utf-8")
        self.assertIn("isEvalSupported: false", editor)
        self.assertNotIn("getDocument(url)", editor)  # la forma vieja, sin opciones

    def test_la_version_incluida_sigue_siendo_la_que_conocemos(self):
        """Si alguien actualiza pdf.js, este test avisa que hay que revisar si la mitigación sigue haciendo falta."""
        leeme = (Path(settings.BASE_DIR) / "static" / "vendor" / "pdfjs" / "LEEME.md").read_text(encoding="utf-8")
        self.assertIn("3.11.174", leeme)
