"""Las acciones se pueden usar sin una pantalla: no reciben un request, solo un actor."""

from datetime import date
from unittest.mock import patch

from django.contrib import messages
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, Implementacion, Modulo
from employees.models import Empleado
from onboarding import acciones
from onboarding.forms import CondicionesForm
from onboarding.tests.test_wizard import BaseWizard, _url

ANA = Actor.implementador("ana")
SISTEMA = Actor("servicio", "hubspot")
URL = "https://portal.napsis.example/"


def _eventos(accion):
    return EventoImplementacion.objects.filter(accion=accion)


class CrearImplementacionTests(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user("ana", password="x", is_staff=True)
        self.modulo = Modulo.objects.create(nombre="Fichada")

    def crear(self, **extra):
        datos = {
            "cliente": None, "datos_cliente": {"nombre": "Empresa Nueva", "razon_social": "Nueva S.A.", "cuits": "30-50001091-2"},
            "username": "nueva", "mail_cliente": "gerencia@nueva.com", "implementador": self.ana,
            "creado_por": self.ana, "modulo_ids": {self.modulo.pk}, "base_url": URL, **extra,
        }
        return acciones.crear_implementacion(ANA, **datos)

    def test_crea_todo_sin_necesitar_un_request(self):
        resultado = self.crear()
        implementacion = resultado.implementacion
        self.assertTrue(resultado.ok)
        self.assertEqual((implementacion.cliente.nombre, implementacion.cliente.cuits), ("Empresa Nueva", "30-50001091-2"))
        self.assertEqual((implementacion.implementador_asignado, implementacion.creado_por), (self.ana, self.ana))
        self.assertEqual(list(implementacion.modulos.values_list("modulo__codigo", flat=True)), ["fichada"])
        self.assertEqual(implementacion.origen, "portal")

    def test_con_mail_invita_y_el_link_usa_la_url_que_se_le_pasa(self):
        resultado = self.crear()
        self.assertEqual(mail.outbox[0].to, ["gerencia@nueva.com"])
        self.assertIn("https://portal.napsis.example/clave/nueva/", mail.outbox[0].body)
        self.assertIn("Le mandamos a gerencia@nueva.com", resultado.avisos[0].texto)
        self.assertFalse(User.objects.get(username="nueva").has_usable_password())

    def test_sin_mail_entrega_una_contrasena_para_mostrar_una_vez(self):
        resultado = self.crear(mail_cliente="")
        self.assertEqual(mail.outbox, [])
        self.assertIn("contraseña: ", resultado.avisos[0].texto)
        self.assertEqual(resultado.avisos[0].nivel, messages.SUCCESS)

    def test_registra_los_eventos_sin_guardar_la_contrasena(self):
        self.crear(mail_cliente="")
        creada = _eventos("implementacion.creada").get()
        self.assertEqual((creada.actor_tipo, creada.actor_ref), ("implementador", "ana"))
        self.assertEqual((creada.datos["cliente_nuevo"], creada.datos["modulos"], creada.datos["implementador"]),
                         (True, ["fichada"], "ana"))
        acceso = _eventos("acceso.creado").get()
        self.assertEqual((acceso.datos["username"], acceso.datos["invitacion"]), ("nueva", False))
        self.assertNotIn("contraseña", str(list(EventoImplementacion.objects.values_list("datos", flat=True))).lower())

    def test_con_invitacion_queda_el_evento_del_mail(self):
        self.crear()
        self.assertEqual(_eventos("mail.enviado").get().datos, {"tipo": "invitacion", "destinatarios": ["gerencia@nueva.com"]})

    def test_si_falla_el_mail_la_implementacion_igual_se_crea_y_se_avisa(self):
        with patch("onboarding.acciones.notificaciones.enviar_invitacion", side_effect=OSError("SMTP")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                resultado = self.crear()
        self.assertTrue(resultado.ok)
        self.assertTrue(Implementacion.objects.exists())
        self.assertEqual(resultado.avisos[0].nivel, messages.WARNING)
        self.assertIn("No se pudo enviar el mail", resultado.avisos[0].texto)
        self.assertEqual(_eventos("mail.fallido").get().datos, {"tipo": "invitacion", "error": "OSError"})

    def test_con_un_cliente_existente_no_toca_su_cuenta(self):
        usuario = User.objects.create_user("cli", password="clave")
        cliente = Cliente.objects.create(nombre="Ya existe", usuario=usuario)
        resultado = self.crear(cliente=cliente, datos_cliente=None, mail_cliente="otro@ya.com")
        self.assertEqual(mail.outbox, [])
        self.assertFalse(_eventos("acceso.creado").exists())
        self.assertEqual(resultado.implementacion.cliente, cliente)
        self.assertTrue(User.objects.get(username="cli").check_password("clave"))

    def test_los_errores_no_crean_nada(self):
        casos = {
            "mail": ({"mail_cliente": "no-es-un-mail"}, "El mail del cliente no es válido"),
            "nombre": ({"datos_cliente": {"nombre": " "}}, "Elegí un cliente existente"),
            "cuit": ({"datos_cliente": {"nombre": "X", "cuits": "123"}}, "CUIT"),
        }
        for nombre, (extra, texto) in casos.items():
            with self.subTest(caso=nombre):
                resultado = self.crear(**extra)
                self.assertFalse(resultado.ok)
                self.assertIn(texto, resultado.errores[0])
        self.assertFalse(Cliente.objects.exists())
        self.assertFalse(Implementacion.objects.exists())
        self.assertFalse(EventoImplementacion.objects.exists())

    def test_es_todo_o_nada(self):
        with patch("onboarding.acciones.services.guardar_modulos", side_effect=RuntimeError("base caída")):
            with self.assertRaises(RuntimeError):
                self.crear()
        self.assertFalse(Cliente.objects.exists() or User.objects.filter(username="nueva").exists())
        self.assertEqual(mail.outbox, [])

    def test_el_mismo_caso_de_un_sistema_externo_no_se_crea_dos_veces(self):
        primero = self.crear(origen="hubspot", id_externo="deal-77")
        segundo = self.crear(origen="hubspot", id_externo="deal-77", datos_cliente={"nombre": "Otra"})
        self.assertFalse(primero.ya_existia)
        self.assertTrue(segundo.ya_existia)
        self.assertEqual(segundo.implementacion, primero.implementacion)
        self.assertEqual(Implementacion.objects.count(), 1)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_aplica_las_condiciones(self):
        condiciones = CondicionesForm({"tipo_firma": "digital", "max_roles": "4"})
        self.assertTrue(condiciones.is_valid())
        implementacion = self.crear(condiciones=condiciones).implementacion
        self.assertEqual((implementacion.tipo_firma, implementacion.tipo_firma_editable, implementacion.max_roles), ("digital", False, 4))

    def test_un_sistema_puede_crear_sin_cuenta_de_usuario(self):
        resultado = acciones.crear_implementacion(
            SISTEMA, datos_cliente={"nombre": "Desde el CRM"}, mail_cliente="crm@cliente.com",
            origen="hubspot", id_externo="42", base_url=URL,
        )
        implementacion = resultado.implementacion
        self.assertEqual((implementacion.creado_por, implementacion.implementador_asignado), (None, None))
        self.assertEqual(_eventos("implementacion.creada").get().actor_tipo, "servicio")


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


class EstadoDeLaImplementacionTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa A")
        self.implementacion = Implementacion.objects.create(
            cliente=self.cliente, mail_contacto="contacto@a.com", enviado=timezone.now(),
        )

    def test_reasignar_registra_de_quien_a_quien(self):
        antes = User.objects.create_user("antes", password="x", is_staff=True)
        despues = User.objects.create_user("despues", password="x", is_staff=True, first_name="Des", last_name="Pues")
        self.implementacion.implementador_asignado = antes
        self.implementacion.save()
        resultado = acciones.reasignar(ANA, self.implementacion, despues)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.implementador_asignado, despues)
        self.assertEqual(_eventos("implementacion.reasignada").get().datos, {"desde": "antes", "hacia": "despues"})
        self.assertIn("Des Pues", resultado.avisos[0].texto)

    def test_marcar_cumplida_avisa_al_cliente(self):
        acciones.marcar_cumplida(ANA, self.implementacion, base_url=URL)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)
        self.assertEqual(mail.outbox[0].subject, "Tu implementación está lista")
        self.assertIn("https://portal.napsis.example/login/", mail.outbox[0].body)
        evento = _eventos("estado.cumplida").get()
        self.assertEqual((evento.datos["estado_anterior"], evento.post_envio), ("pendiente", True))

    def test_si_el_mail_falla_queda_cumplida_igual_y_se_avisa(self):
        with patch("onboarding.acciones.notificaciones.notificar_cliente_implementacion_cumplida", side_effect=OSError("SMTP")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                resultado = acciones.marcar_cumplida(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)
        self.assertIn("no se pudo avisarle al cliente", resultado.avisos[0].texto)

    def test_sin_mail_del_cliente_no_hay_aviso_ni_falla(self):
        self.implementacion.mail_contacto = ""
        self.implementacion.save()
        resultado = acciones.marcar_cumplida(ANA, self.implementacion)
        self.assertEqual((resultado.avisos, mail.outbox), ([], []))
        self.assertFalse(_eventos("mail.enviado").exists())

    def test_anular(self):
        acciones.anular(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CANCELADA)
        self.assertEqual(_eventos("estado.cancelada").get().datos, {"estado_anterior": "pendiente"})

    def test_reabrir_deja_constancia_de_como_estaba(self):
        self.implementacion.paso_actual = 7
        self.implementacion.save()
        acciones.reabrir(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual((self.implementacion.paso_actual, self.implementacion.enviado), (1, None))
        antes = _eventos("estado.reabierta").get().datos["antes"]
        self.assertEqual((antes["paso_actual"], antes["estado"]), (7, "pendiente"))
        self.assertIsNotNone(antes["enviado"])

    def test_atender_la_revision(self):
        self.implementacion.pedir_revision("Llamen")
        acciones.atender_revision(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.revision_atendida_en)
        self.assertTrue(_eventos("revision.atendida").exists())


class EnvioDelClienteTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa A", razon_social="Empresa A S.A.", cuits="30500010912")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente, mail_contacto="contacto@a.com")
        Empleado.objects.create(implementacion=self.implementacion, cuil="20111111112", nombre="J", apellido="P")
        self.cliente_actor = Actor.cliente("cli")

    def enviar(self, **extra):
        return acciones.enviar_relevamiento(self.cliente_actor, self.implementacion, date(2026, 12, 1), base_url=URL, **extra)

    def test_registra_el_envio_con_la_fecha_pedida(self):
        self.enviar()
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)
        self.assertEqual(self.implementacion.fecha_salida_productivo, date(2026, 12, 1))
        evento = _eventos("envio.confirmado").get()
        self.assertEqual((evento.datos["fecha_salida_productivo"], evento.datos["empleados"], evento.post_envio),
                         ("2026-12-01", 1, False))
        self.assertTrue(_eventos("implementacion.fecha_cambiada").exists())

    def test_avisa_al_equipo_y_confirma_al_cliente(self):
        with self.settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsis.com"]):
            self.enviar()
        destinatarios = {m.to[0] for m in mail.outbox}
        self.assertEqual(destinatarios, {"equipo@napsis.com", "contacto@a.com"})
        resumen = next(m for m in mail.outbox if m.to == ["equipo@napsis.com"])
        self.assertIn("https://portal.napsis.example/panel/implementaciones/", resumen.body)
        self.assertEqual({e.datos["tipo"] for e in _eventos("mail.enviado")}, {"equipo_resumen", "cliente_recibido"})

    def test_si_los_mails_fallan_el_envio_queda_igual(self):
        with patch("onboarding.acciones.notificaciones.notificar_implementacion_completa", side_effect=OSError("SMTP")), \
                patch("onboarding.acciones.notificaciones.notificar_cliente_relevamiento_recibido", side_effect=OSError("SMTP")), \
                self.assertLogs("onboarding.acciones", level="ERROR"):
            resultado = self.enviar()
        self.implementacion.refresh_from_db()
        self.assertTrue(resultado.ok)
        self.assertIsNotNone(self.implementacion.enviado)
        self.assertEqual(_eventos("mail.fallido").count(), 2)

    def test_pedir_que_lo_contacten(self):
        self.implementacion.enviado = timezone.now()
        self.implementacion.save()
        with self.settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsis.com"]):
            resultado = acciones.pedir_revision(self.cliente_actor, self.implementacion, "Llamen por favor", base_url=URL)
        self.implementacion.refresh_from_db()
        self.assertTrue(self.implementacion.revision_solicitada)
        self.assertEqual(_eventos("revision.solicitada").get().datos, {"mensaje": "Llamen por favor"})
        self.assertIn("Le avisamos al equipo", resultado.avisos[0].texto)
        self.assertEqual(mail.outbox[0].to, ["equipo@napsis.com"])

    def test_registrar_lo_que_no_se_pudo_completar(self):
        acciones.registrar_validacion_fallida(self.cliente_actor, self.implementacion, 1, {"cuits": ["inválido"]})
        evento = _eventos("validacion.fallida").get()
        self.assertEqual((evento.datos["paso"], evento.datos["errores"]), (1, {"cuits": ["inválido"]}))


class ResultadoTests(TestCase):
    def test_mostrar_usa_el_sistema_de_mensajes(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        pedido = RequestFactory().get("/")
        pedido.session = {}
        pedido._messages = FallbackStorage(pedido)
        acciones.Resultado(avisos=[acciones.Aviso(messages.WARNING, "ojo")]).mostrar(pedido)
        self.assertEqual([str(m) for m in pedido._messages], ["ojo"])


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
        self.client.post(self.url(9), {"accion": "enviar"})
        datos = _eventos("validacion.fallida").get().datos
        self.assertEqual(datos["paso"], 9)
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
        self.client.post(self.url(9), {"accion": "enviar", "fecha_salida_productivo": ""})
        evento = _eventos("envio.confirmado").get()
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("cliente", self.usuario.username))
