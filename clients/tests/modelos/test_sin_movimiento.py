"""«Implementación sin movimiento»: una pendiente a la que nadie le hizo nada en 7 días."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, Implementacion, Modulo
from clients.services import con_ultimo_movimiento, filtrar_y_ordenar_implementaciones
from onboarding import acciones, services

ANA = Actor.implementador("ana")


def implementacion_de_hace(dias, nombre="Empresa", **extra):
    """Una implementación creada hace `dias` días (la fecha de alta se retrasa a mano)."""
    implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre=nombre), **extra)
    Implementacion.objects.filter(pk=implementacion.pk).update(creado=timezone.now() - timedelta(days=dias, minutes=1))
    implementacion.refresh_from_db()
    return implementacion


def evento_de_hace(implementacion, dias, accion="paso.guardado"):
    return EventoImplementacion.objects.create(
        implementacion=implementacion, implementacion_uuid=implementacion.uuid, actor_tipo="cliente",
        accion=accion, momento=timezone.now() - timedelta(days=dias),
    )


class DerivacionTests(TestCase):
    def test_una_recien_creada_tiene_movimiento(self):
        self.assertFalse(implementacion_de_hace(0).sin_movimiento)

    def test_el_limite_es_de_7_dias(self):
        self.assertEqual(Implementacion.DIAS_SIN_MOVIMIENTO, 7)
        self.assertFalse(implementacion_de_hace(6).sin_movimiento)
        self.assertTrue(implementacion_de_hace(7).sin_movimiento)
        self.assertTrue(implementacion_de_hace(30).sin_movimiento)

    def test_sin_eventos_cuenta_desde_que_se_creo(self):
        implementacion = implementacion_de_hace(10)
        self.assertEqual(implementacion.ultimo_movimiento, implementacion.creado)

    def test_un_evento_reciente_la_saca(self):
        implementacion = implementacion_de_hace(30)
        evento_de_hace(implementacion, 1)
        self.assertFalse(implementacion.sin_movimiento)

    def test_cuenta_desde_el_ultimo_evento_no_desde_el_primero(self):
        implementacion = implementacion_de_hace(40)
        evento_de_hace(implementacion, 30)
        evento_de_hace(implementacion, 9)
        self.assertTrue(implementacion.sin_movimiento)
        self.assertEqual(implementacion.dias_sin_movimiento, 9)

    def test_un_evento_viejo_no_la_saca(self):
        implementacion = implementacion_de_hace(40)
        evento_de_hace(implementacion, 20)
        self.assertTrue(implementacion.sin_movimiento)

    def test_solo_aplica_a_las_pendientes(self):
        cumplida = implementacion_de_hace(30, "A", estado=Implementacion.ESTADO_CUMPLIDA)
        cancelada = implementacion_de_hace(30, "B", estado=Implementacion.ESTADO_CANCELADA)
        self.assertFalse(cumplida.sin_movimiento)
        self.assertFalse(cancelada.sin_movimiento)

    def test_no_es_un_estado_nuevo_sigue_figurando_donde_estaba(self):
        implementacion = implementacion_de_hace(30)
        self.assertTrue(implementacion.sin_movimiento)
        self.assertEqual(implementacion.estado_visual, Implementacion.VISUAL_A_COMPLETAR)

    def test_los_eventos_de_otra_implementacion_no_cuentan(self):
        una = implementacion_de_hace(30, "Una")
        otra = implementacion_de_hace(30, "Otra")
        evento_de_hace(otra, 0)
        self.assertTrue(una.sin_movimiento)
        self.assertFalse(otra.sin_movimiento)


class QueLaSacaTests(TestCase):
    """Cualquier acción sobre la implementación, un comentario o un envío la sacan de ahí."""

    def setUp(self):
        self.implementacion = implementacion_de_hace(20, mail_contacto="c@a.com")
        self.assertTrue(self.implementacion.sin_movimiento)

    def test_un_comentario(self):
        acciones.agregar_comentario(ANA, self.implementacion, "Lo llamé, no atiende.")
        self.assertFalse(Implementacion.objects.get(pk=self.implementacion.pk).sin_movimiento)

    def test_una_accion_del_equipo(self):
        acciones.reasignar(ANA, self.implementacion, User.objects.create_user("otro", password="x", is_staff=True))
        self.assertFalse(Implementacion.objects.get(pk=self.implementacion.pk).sin_movimiento)

    def test_que_el_cliente_guarde_un_paso(self):
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), set(), Actor.cliente("c"))
        self.assertFalse(Implementacion.objects.get(pk=self.implementacion.pk).sin_movimiento)

    def test_el_envio_de_la_documentacion(self):
        acciones.enviar_relevamiento(Actor.cliente("c"), self.implementacion, None)
        self.assertFalse(Implementacion.objects.get(pk=self.implementacion.pk).sin_movimiento)


class ListadoTests(TestCase):
    def setUp(self):
        self.quieta = implementacion_de_hace(10, "Quieta")
        self.activa = implementacion_de_hace(10, "Activa")
        evento_de_hace(self.activa, 1)
        self.nueva = implementacion_de_hace(0, "Nueva")
        self.cumplida = implementacion_de_hace(30, "Cumplida", estado=Implementacion.ESTADO_CUMPLIDA)

    def test_la_anotacion_coincide_con_la_propiedad(self):
        for implementacion in con_ultimo_movimiento(Implementacion.objects.all()):
            esperado = Implementacion.objects.get(pk=implementacion.pk)
            self.assertEqual(implementacion.sin_movimiento, esperado.sin_movimiento, implementacion.cliente.nombre)
            self.assertEqual(implementacion.ultimo_movimiento, esperado.ultimo_movimiento)

    def test_el_filtro_trae_solo_las_pendientes_quietas(self):
        resultado = filtrar_y_ordenar_implementaciones(Implementacion.objects.all(), {"estado": "sin_movimiento"})
        self.assertEqual([i.cliente.nombre for i in resultado], ["Quieta"])

    def test_el_listado_no_hace_una_consulta_por_fila(self):
        with self.assertNumQueries(1):
            lista = list(filtrar_y_ordenar_implementaciones(Implementacion.objects.all(), {}))
            [i.sin_movimiento for i in lista]

    def test_aparece_entre_las_opciones_del_filtro_de_estado(self):
        opciones = dict(Implementacion.opciones_de_filtro_de_estado())
        self.assertEqual(opciones["sin_movimiento"], "Implementación sin movimiento")
        self.assertIn("completado_cliente", opciones)
