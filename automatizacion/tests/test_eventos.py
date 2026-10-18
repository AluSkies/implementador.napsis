import io
import json
import logging
from datetime import date

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from automatizacion import actores, correlacion, eventos
from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion, EventoInmutable
from clients.models import Cliente, Implementacion


def _implementacion(**extra):
    return Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa A"), **extra)


class ActorTests(TestCase):
    def test_segun_la_cuenta(self):
        self.assertEqual(Actor.de_usuario(User.objects.create_user("c", password="x")), Actor("cliente", "c"))
        self.assertEqual(Actor.de_usuario(User.objects.create_user("i", password="x", is_staff=True)), Actor("implementador", "i"))
        self.assertEqual(
            Actor.de_usuario(User.objects.create_user("a", password="x", is_staff=True, is_superuser=True)), Actor("admin", "a"),
        )

    def test_sin_cuenta_actua_el_sistema(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(Actor.de_usuario(None), actores.SISTEMA_PORTAL)
        self.assertEqual(Actor.de_usuario(AnonymousUser()), actores.SISTEMA_PORTAL)

    def test_la_etiqueta_del_historial_es_la_de_siempre(self):
        self.assertEqual(Actor.cliente("cliente_a").etiqueta, "Cliente")
        self.assertEqual(Actor.implementador("ana").etiqueta, "ana")
        self.assertEqual(actores.SISTEMA_PORTAL.etiqueta, "portal")

    def test_un_tipo_inventado_se_rechaza(self):
        with self.assertRaises(ValueError):
            Actor("duende", "x")

    def test_es_del_equipo(self):
        self.assertTrue(Actor.implementador("ana").es_del_equipo)
        self.assertTrue(Actor("admin", "a").es_del_equipo)
        self.assertFalse(Actor.cliente("c").es_del_equipo)
        self.assertFalse(Actor("agente", "x").es_del_equipo)


class RegistrarTests(TestCase):
    def test_guarda_quien_que_y_sobre_que(self):
        implementacion = _implementacion()
        evento = eventos.registrar(
            Actor.implementador("ana"), "implementacion.reasignada", implementacion,
            seccion="asignacion", datos={"hacia": "bruno"},
        )
        evento.refresh_from_db()
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("implementador", "ana"))
        self.assertEqual((evento.accion, evento.seccion, evento.datos), ("implementacion.reasignada", "asignacion", {"hacia": "bruno"}))
        self.assertEqual((evento.implementacion, evento.implementacion_uuid), (implementacion, implementacion.uuid))
        self.assertEqual((evento.origen, evento.version_esquema), ("web", 1))

    def test_un_evento_sin_implementacion_es_valido(self):
        evento = eventos.registrar(actores.SISTEMA_PORTAL, "sistema.arranco")
        self.assertIsNone(evento.implementacion_uuid)
        self.assertEqual(evento.origen, "sistema")

    def test_las_fechas_y_uuid_se_guardan_como_json(self):
        implementacion = _implementacion()
        evento = eventos.registrar(
            Actor.cliente("c"), "paso.guardado", implementacion, datos={"fecha": date(2026, 12, 1), "uuid": implementacion.uuid},
        )
        evento.refresh_from_db()
        self.assertEqual(evento.datos["fecha"], "2026-12-01")
        self.assertEqual(evento.datos["uuid"], str(implementacion.uuid))

    def test_se_ordenan_por_momento(self):
        implementacion = _implementacion()
        a = eventos.registrar(Actor.cliente("c"), "a", implementacion)
        b = eventos.registrar(Actor.cliente("c"), "b", implementacion)
        self.assertEqual(list(EventoImplementacion.objects.values_list("accion", flat=True)), ["a", "b"])
        self.assertLessEqual(a.momento, b.momento)


class PostEnvioTests(TestCase):
    """Marca lo que el equipo hace con la documentación ya enviada: son las correcciones."""

    def test_antes_del_envio_no_se_marca(self):
        self.assertFalse(eventos.registrar(Actor.implementador("ana"), "x", _implementacion()).post_envio)

    def test_el_equipo_despues_del_envio_se_marca(self):
        implementacion = _implementacion(enviado=timezone.now())
        self.assertTrue(eventos.registrar(Actor.implementador("ana"), "x", implementacion).post_envio)
        self.assertTrue(eventos.registrar(Actor("admin", "a"), "x", implementacion).post_envio)

    def test_el_cliente_o_el_sistema_no_se_marcan_como_correccion_del_equipo(self):
        implementacion = _implementacion(enviado=timezone.now())
        self.assertFalse(eventos.registrar(Actor.cliente("c"), "x", implementacion).post_envio)

    def test_se_puede_forzar(self):
        self.assertTrue(eventos.registrar(Actor.cliente("c"), "x", _implementacion(), post_envio=True).post_envio)


class InmutabilidadTests(TestCase):
    def setUp(self):
        self.evento = eventos.registrar(Actor.cliente("c"), "x", _implementacion())

    def test_no_se_modifica(self):
        self.evento.accion = "otra"
        with self.assertRaises(EventoInmutable):
            self.evento.save()

    def test_no_se_borra(self):
        with self.assertRaises(EventoInmutable):
            self.evento.delete()

    def test_no_se_modifica_ni_se_borra_en_lote(self):
        with self.assertRaises(EventoInmutable):
            EventoImplementacion.objects.update(accion="otra")
        with self.assertRaises(EventoInmutable):
            EventoImplementacion.objects.all().delete()
        with self.assertRaises(EventoInmutable):
            EventoImplementacion.objects.bulk_update([self.evento], ["accion"])

    def test_si_se_borra_la_implementacion_la_historia_queda(self):
        implementacion = self.evento.implementacion
        uuid = implementacion.uuid
        implementacion.delete()
        self.evento.refresh_from_db()
        self.assertIsNone(self.evento.implementacion)
        self.assertEqual(self.evento.implementacion_uuid, uuid)

    def test_el_admin_es_de_solo_lectura(self):
        modelo_admin = admin.site._registry[EventoImplementacion]
        pedido = RequestFactory().get("/admin/")
        self.assertFalse(modelo_admin.has_add_permission(pedido))
        self.assertFalse(modelo_admin.has_change_permission(pedido, self.evento))
        self.assertFalse(modelo_admin.has_delete_permission(pedido, self.evento))


class DiferenciasTests(SimpleTestCase):
    def test_solo_lo_que_cambio(self):
        antes = {"Teléfono": "111", "Mail": "a@a.com", "Igual": 1}
        despues = {"Teléfono": "222", "Mail": "a@a.com", "Igual": 1}
        self.assertEqual(eventos.diferencias(antes, despues), {"Teléfono": {"antes": "111", "despues": "222"}})

    def test_campos_nuevos_y_borrados(self):
        self.assertEqual(
            eventos.diferencias({"a": 1}, {"b": 2}),
            {"a": {"antes": 1, "despues": None}, "b": {"antes": None, "despues": 2}},
        )

    def test_sin_cambios_es_vacio(self):
        self.assertEqual(eventos.diferencias({"a": 1}, {"a": 1}), {})


class CorrelacionTests(TestCase):
    def test_el_evento_lleva_el_id_del_pedido(self):
        correlacion.nueva()
        evento = eventos.registrar(Actor.cliente("c"), "x", _implementacion())
        self.assertEqual(evento.correlation_id, correlacion.actual())
        self.assertEqual(len(evento.correlation_id), 32)

    def test_cada_pedido_web_recibe_su_id_y_lo_devuelve(self):
        a = self.client.get(reverse("landing"))
        b = self.client.get(reverse("landing"))
        self.assertTrue(a["X-Request-ID"])
        self.assertNotEqual(a["X-Request-ID"], b["X-Request-ID"])

    def test_acepta_el_id_que_manda_el_proxy_si_es_razonable(self):
        self.assertEqual(self.client.get(reverse("landing"), HTTP_X_REQUEST_ID="abc12345-proxy")["X-Request-ID"], "abc12345-proxy")

    def test_ignora_un_id_con_formato_raro(self):
        valor = self.client.get(reverse("landing"), HTTP_X_REQUEST_ID="<script>alert(1)</script>")["X-Request-ID"]
        self.assertRegex(valor, r"^[0-9a-f]{32}$")

    def test_el_log_incluye_el_id(self):
        correlacion.nueva()
        registro = logging.LogRecord("x", logging.ERROR, "x.py", 1, "m", None, None)
        correlacion.CorrelacionFilter().filter(registro)
        self.assertEqual(registro.correlacion, correlacion.actual())


class ExportarEventosTests(TestCase):
    def test_exporta_una_linea_json_por_evento(self):
        implementacion = _implementacion()
        eventos.registrar(Actor.cliente("c"), "paso.guardado", implementacion, seccion="roles", datos={"x": 1})
        eventos.registrar(Actor.implementador("ana"), "implementacion.cumplida", implementacion)
        salida = io.StringIO()
        from unittest.mock import patch

        with patch("sys.stdout", salida):
            call_command("exportar_eventos")
        lineas = [json.loads(linea) for linea in salida.getvalue().splitlines()]
        self.assertEqual([linea["accion"] for linea in lineas], ["paso.guardado", "implementacion.cumplida"])
        self.assertEqual(lineas[0]["implementacion"], str(implementacion.uuid))
        self.assertEqual(lineas[0]["datos"], {"x": 1})
        self.assertEqual(lineas[0]["seccion"], "roles")

    def test_filtra_por_implementacion(self):
        a, b = _implementacion(), _implementacion()
        eventos.registrar(Actor.cliente("c"), "de-a", a)
        eventos.registrar(Actor.cliente("c"), "de-b", b)
        salida = io.StringIO()
        from unittest.mock import patch

        with patch("sys.stdout", salida):
            call_command("exportar_eventos", implementacion=str(b.uuid))
        self.assertEqual([json.loads(x)["accion"] for x in salida.getvalue().splitlines()], ["de-b"])

    def test_escribe_a_un_archivo(self):
        import tempfile
        from pathlib import Path

        eventos.registrar(Actor.cliente("c"), "x", _implementacion())
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "eventos.jsonl"
            call_command("exportar_eventos", salida=str(destino), stderr=io.StringIO())
            self.assertEqual(len(destino.read_text(encoding="utf-8").splitlines()), 1)

    def test_una_fecha_invalida_se_rechaza(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("exportar_eventos", desde="ayer")
