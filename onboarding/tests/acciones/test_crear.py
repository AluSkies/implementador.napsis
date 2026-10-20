"""Alta de implementaciones desde las acciones (sin pantalla)."""

from unittest.mock import patch

from django.contrib import messages
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, Implementacion, Modulo
from onboarding import acciones
from onboarding.forms import CondicionesForm

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


class NuevaImplementacionDeUnClienteExistenteTests(TestCase):
    """Una empresa que ya tuvo una implementación no vuelve a cargar lo que ya sabemos de ella."""

    def setUp(self):
        self.ana = User.objects.create_user("ana", password="x", is_staff=True)
        self.cliente = Cliente.objects.create(nombre="Textil", razon_social="Textil S.A.", cuits="30-50001091-2")
        self.anterior = Implementacion.objects.create(
            cliente=self.cliente, mail_contacto="rrhh@textil.com", telefono="011-4444-5555",
        )

    def crear(self, **extra):
        return acciones.crear_implementacion(ANA, cliente=self.cliente, implementador=self.ana, base_url=URL, **extra)

    def test_hereda_el_telefono_y_el_mail_de_la_ultima(self):
        nueva = self.crear().implementacion
        self.assertEqual((nueva.mail_contacto, nueva.telefono), ("rrhh@textil.com", "011-4444-5555"))

    def test_un_mail_escrito_en_el_alta_tiene_prioridad(self):
        nueva = self.crear(mail_cliente="otro@textil.com").implementacion
        self.assertEqual((nueva.mail_contacto, nueva.telefono), ("otro@textil.com", "011-4444-5555"))

    def test_una_empresa_nueva_arranca_vacia(self):
        nueva = acciones.crear_implementacion(ANA, datos_cliente={"nombre": "Otra"}, base_url=URL).implementacion
        self.assertEqual((nueva.mail_contacto, nueva.telefono), ("", ""))

    def test_completa_la_razon_social_y_el_cuit_que_faltaban(self):
        self.cliente.razon_social, self.cliente.cuits = "", ""
        self.cliente.save()
        self.crear(datos_cliente={"razon_social": "Textil S.A.", "cuits": "30500010912"})
        self.cliente.refresh_from_db()
        self.assertEqual((self.cliente.razon_social, self.cliente.cuits), ("Textil S.A.", "30-50001091-2"))
        self.assertIn("razon_social", _eventos("implementacion.creada").get().datos["empresa_completada"])

    def test_lo_que_llega_vacio_no_borra_lo_cargado(self):
        self.crear(datos_cliente={"razon_social": "", "cuits": ""})
        self.cliente.refresh_from_db()
        self.assertEqual((self.cliente.razon_social, self.cliente.cuits), ("Textil S.A.", "30-50001091-2"))

    def test_un_cuit_invalido_no_crea_nada(self):
        resultado = self.crear(datos_cliente={"cuits": "123"})
        self.assertFalse(resultado.ok)
        self.assertEqual(self.cliente.implementaciones.count(), 1)
