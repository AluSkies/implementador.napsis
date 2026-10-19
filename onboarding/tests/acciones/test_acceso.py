"""Acceso del cliente creado junto con la implementación."""

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, Implementacion
from onboarding import acciones

ANA = Actor.implementador("ana")
URL = "https://portal.napsis.example/"


def _eventos(accion):
    return EventoImplementacion.objects.filter(accion=accion)


class AccesoDelClienteTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("cli", password="clave", email="cli@a.com")
        self.cliente = Cliente.objects.create(nombre="Empresa A", usuario=self.usuario)
        self.implementacion = Implementacion.objects.create(cliente=self.cliente, mail_contacto="contacto@a.com")

    def test_reiniciar_la_contrasena_genera_una_nueva_y_la_anterior_deja_de_servir(self):
        resultado = acciones.entregar_acceso(ANA, self.cliente, base_url=URL, implementacion=self.implementacion)
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.check_password("clave"))
        self.assertIn("Nueva contraseña generada", resultado.avisos[0].texto)
        self.assertEqual(_eventos("acceso.contrasena_reiniciada").get().datos["username"], "cli")

    def test_un_mail_invalido_se_rechaza(self):
        resultado = acciones.entregar_acceso(ANA, self.cliente, mail="roto")
        self.assertEqual(resultado.errores, ["El mail no es válido."])

    def test_invitar_manda_el_link_y_no_toca_la_contrasena(self):
        resultado = acciones.invitar_cliente(ANA, self.cliente, self.implementacion, base_url=URL)
        self.assertEqual(mail.outbox[0].to, ["cli@a.com"])
        self.assertTrue(self.usuario.check_password("clave"))
        self.assertTrue(resultado.ok)

    def test_si_la_cuenta_no_tiene_mail_usa_el_de_contacto_y_lo_guarda(self):
        self.usuario.email = ""
        self.usuario.save()
        acciones.invitar_cliente(ANA, self.cliente, self.implementacion, base_url=URL)
        self.usuario.refresh_from_db()
        self.assertEqual((self.usuario.email, mail.outbox[0].to), ("contacto@a.com", ["contacto@a.com"]))

    def test_sin_cuenta_o_sin_mail_avisa_en_vez_de_fallar(self):
        sin_cuenta = Cliente.objects.create(nombre="Sin acceso")
        self.assertIn("todavía no tiene acceso", acciones.invitar_cliente(ANA, sin_cuenta).errores[0])
        self.usuario.email = ""
        self.usuario.save()
        self.assertIn("No hay un mail cargado", acciones.invitar_cliente(ANA, self.cliente).errores[0])
        self.assertEqual(mail.outbox, [])
