"""Comentarios internos: notas privadas del equipo en cada implementación."""

import tempfile

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from automatizacion.actores import Actor
from automatizacion.congelada import contenido_de
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, ComentarioInterno, Implementacion
from onboarding import acciones
from onboarding.tests.base import EnviadaBase

ANA = Actor.implementador("ana")
SECRETO = "Este cliente es dificil, no mencionar el descuento"


class AgregarComentarioTests(TestCase):
    def setUp(self):
        self.implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa A"))
        self.ana = User.objects.create_user("ana", password="x", is_staff=True, first_name="Ana", last_name="Paz")

    def comentar(self, texto="Lo llamé y quedó en mandar los legajos."):
        return acciones.agregar_comentario(ANA, self.implementacion, texto, autor=self.ana)

    def test_guarda_el_comentario_con_su_autor(self):
        resultado = self.comentar()
        self.assertTrue(resultado.ok)
        comentario = self.implementacion.comentarios.get()
        self.assertEqual((comentario.autor, comentario.autor_nombre), (self.ana, "Ana Paz"))
        self.assertEqual(comentario.texto, "Lo llamé y quedó en mandar los legajos.")

    def test_el_nombre_queda_aunque_se_borre_la_cuenta(self):
        self.comentar()
        self.ana.delete()
        comentario = self.implementacion.comentarios.get()
        self.assertIsNone(comentario.autor)
        self.assertEqual(comentario.autor_nombre, "Ana Paz")

    def test_deja_un_evento_solo_con_el_id_no_con_el_texto(self):
        self.comentar()
        evento = EventoImplementacion.objects.get(accion="comentario.agregado")
        self.assertEqual(evento.datos, {"comentario_id": self.implementacion.comentarios.get().pk})
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("implementador", "ana"))

    def test_se_recorta_el_espacio_sobrante(self):
        self.comentar("   hola   \n")
        self.assertEqual(self.implementacion.comentarios.get().texto, "hola")

    def test_no_acepta_uno_vacio(self):
        for texto in ("", "   ", None):
            with self.subTest(texto=texto):
                resultado = self.comentar(texto)
                self.assertEqual(resultado.avisos[0].texto, "Escribí el comentario.")
        self.assertFalse(self.implementacion.comentarios.exists())

    def test_tiene_un_largo_maximo(self):
        resultado = self.comentar("x" * (ComentarioInterno.MAX_LARGO + 1))
        self.assertIn("hasta 2000 caracteres", resultado.avisos[0].texto)
        self.assertFalse(self.implementacion.comentarios.exists())
        self.comentar("x" * ComentarioInterno.MAX_LARGO)
        self.assertEqual(self.implementacion.comentarios.count(), 1)

    def test_un_cliente_no_puede_comentar(self):
        resultado = acciones.agregar_comentario(Actor.cliente("cliente_a"), self.implementacion, "hola")
        self.assertIn("Solo el equipo", resultado.avisos[0].texto)
        self.assertFalse(self.implementacion.comentarios.exists())

    def test_el_mas_nuevo_va_primero(self):
        self.comentar("primero")
        self.comentar("segundo")
        self.assertEqual([c.texto for c in self.implementacion.comentarios.all()], ["segundo", "primero"])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PrivacidadTests(EnviadaBase):
    """El cliente nunca ve los comentarios: ni en sus pantallas, ni en sus mails, ni en lo que se congela."""

    def setUp(self):
        super().setUp()
        acciones.agregar_comentario(ANA, self.implementacion, SECRETO)

    def test_no_aparecen_en_las_pantallas_del_cliente(self):
        for url in (
            reverse("onboarding:wizard_step", kwargs={"token": self.implementacion.token, "step": 1}),
            reverse("onboarding:enviado", kwargs={"token": self.implementacion.token}),
            reverse("onboarding:mis_implementaciones"),
        ):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), SECRETO, status_code=200)

    def test_no_forman_parte_de_la_configuracion_congelada(self):
        self.assertNotIn(SECRETO, str(contenido_de(self.implementacion)))
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertNotIn(SECRETO, str(self.implementacion.congeladas.get().contenido))

    def test_el_cliente_no_puede_comentar_por_el_panel(self):
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        self.client.post(url, {"accion": "agregar_comentario", "texto": "intento"})
        self.assertEqual(self.implementacion.comentarios.count(), 1)  # solo el del equipo

    def test_no_viajan_en_los_mails_al_cliente(self):
        mail.outbox.clear()
        acciones.devolver_al_cliente(ANA, self.implementacion, "Ajustá la nómina")
        self.assertTrue(mail.outbox)
        self.assertTrue(all(SECRETO not in m.body for m in mail.outbox))
