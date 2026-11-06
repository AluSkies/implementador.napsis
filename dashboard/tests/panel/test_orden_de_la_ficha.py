"""Cómo se ordenan las acciones de la ficha: Reasignar en una sola línea y los botones del acceso del cliente en una fila."""

from django.urls import reverse

from clients.models import Cliente, Implementacion
from dashboard.tests.base import BasePanel


class BaseFicha(BasePanel):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(nombre="Empresa A", usuario=self.cliente_user)
        self.implementacion = Implementacion.objects.create(cliente=self.cliente, implementador_asignado=self.ana)
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        self.url_empresa = reverse("dashboard:cliente_detalle", kwargs={"pk": self.cliente.pk})


class ReasignarEnUnaLineaTests(BaseFicha):
    def test_el_selector_y_el_boton_van_juntos_en_un_formulario_en_linea(self):
        pagina = self.client.get(self.url).content.decode()
        self.assertIn('<form method="post" class="form-en-linea">', pagina)
        formulario = pagina.split('<form method="post" class="form-en-linea">')[1].split("</form>")[0]
        self.assertIn('name="implementador_id"', formulario)
        self.assertIn("Reasignar", formulario)
        self.assertNotIn('style="margin-bottom:12px;"', pagina)

    def test_quien_no_asigna_ve_solo_el_nombre(self):
        from django.contrib.auth.models import User

        implementador = User.objects.create_user("beto", password="x", is_staff=True, first_name="Beto")
        self.implementacion.implementador_asignado = implementador
        self.implementacion.save()
        self.client.force_login(implementador)
        pagina = self.client.get(self.url).content.decode()
        self.assertNotIn('form-en-linea', pagina)
        self.assertNotIn('value="reasignar"', pagina)
        self.assertRegex(pagina, r"Implementador asignado:</strong>\s+Beto")  # solo el nombre, sin selector

    def test_una_asignada_no_tiene_marcador_de_sin_asignar(self):
        self.assertNotIn("— sin asignar —", self.client.get(self.url).content.decode())

    def test_una_sin_asignar_no_preselecciona_a_nadie(self):
        self.implementacion.implementador_asignado = None
        self.implementacion.save()
        pagina = self.client.get(self.url).content.decode()
        self.assertIn('<option value="" selected disabled>— sin asignar —</option>', pagina)

    def test_apretar_reasignar_sin_elegir_a_nadie_no_cambia_nada(self):
        self.implementacion.implementador_asignado = None
        self.implementacion.save()
        self.client.post(self.url, {"accion": "reasignar"})  # el marcador es «disabled»: el navegador no manda el campo
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.implementador_asignado)


class BotonesDelAccesoTests(BaseFicha):
    BOTONES = ("Reiniciar contraseña", "Enviar mail para crear contraseña")

    def fila_de_botones(self, url):
        pagina = self.client.get(url).content.decode()
        return pagina.split('<div class="actions compacta">')[1].split("<p class=\"muted\">El mail va a")[0]

    def test_en_la_ficha_los_dos_botones_van_en_una_sola_fila(self):
        fila = self.fila_de_botones(self.url)
        for boton in self.BOTONES:
            self.assertIn(boton, fila)

    def test_en_la_ficha_de_la_empresa_tambien(self):
        fila = self.fila_de_botones(self.url_empresa)
        for boton in self.BOTONES:
            self.assertIn(boton, fila)

    def test_la_aclaracion_del_mail_aparece_una_sola_vez_debajo(self):
        pagina = self.client.get(self.url).content.decode()
        self.assertEqual(pagina.count("El mail va a"), 1)
        self.assertEqual(pagina.count("No cambia la contraseña actual hasta que el cliente use el link."), 1)

    def test_sin_cuenta_se_ofrece_crearla_y_no_los_botones_de_una_cuenta_existente(self):
        self.cliente.usuario = None
        self.cliente.save()
        for url, prefijo in ((self.url, "acceso"), (self.url_empresa, "empresa")):
            pagina = self.client.get(url).content.decode()
            self.assertIn("Crear acceso", pagina)
            self.assertIn(f'id="username_{prefijo}"', pagina)  # cada pantalla con sus ids
            for boton in self.BOTONES:
                self.assertNotIn(boton, pagina)

    def test_los_botones_siguen_mandando_las_mismas_acciones(self):
        pagina = self.client.get(self.url).content.decode()
        self.assertIn('name="accion" value="regenerar_acceso"', pagina)
        self.assertIn('name="accion" value="enviar_invitacion"', pagina)
