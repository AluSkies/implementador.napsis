import tempfile
from io import StringIO

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from catalog.models import TipoLicencia, TipoLiquidacion
from clients.models import Cliente, Implementacion, ImplementacionLiquidacion
from dashboard.tests import test_asignado
from onboarding import services
from onboarding.forms import LicenciasNovedadesForm, LiquidacionesForm
from onboarding.tests.test_wizard import BaseWizard, _url

CLIENTE = Actor.cliente("cliente_a")
ANA = Actor.implementador("ana")


class CatalogoDeLiquidacionesTests(TestCase):
    def test_el_seed_carga_los_diez_tipos_en_el_orden_del_wizard_de_napsis(self):
        call_command("seed_catalogos", stdout=StringIO())
        self.assertEqual(
            list(TipoLiquidacion.objects.values_list("nombre", flat=True)),
            ["Liquidación Normal", "Aguinaldo", "Anticipos", "Formulario 1357", "Ajustes", "Liquidación Final",
             "Primera Quincena", "Segunda Quincena", "Gratificación - Bono", "Formulario 1357 Anual"],
        )
        self.assertEqual(TipoLiquidacion.objects.get(nombre="Aguinaldo").codigo, "aguinaldo")

    def test_no_pisa_lo_corregido_en_el_admin(self):
        call_command("seed_catalogos", stdout=StringIO())
        TipoLiquidacion.objects.filter(codigo="anticipos").update(nombre="Anticipos de sueldo")
        call_command("seed_catalogos", stdout=StringIO())
        call_command("seed_catalogos", "--completar", stdout=StringIO())
        self.assertEqual(TipoLiquidacion.objects.count(), 10)
        self.assertEqual(TipoLiquidacion.objects.get(codigo="anticipos").nombre, "Anticipos de sueldo")

    def test_vacaciones_queda_marcada_como_automatica(self):
        call_command("seed_catalogos", stdout=StringIO())
        self.assertEqual(
            list(TipoLicencia.objects.filter(automatica=True).values_list("nombre", flat=True)), ["Vacaciones"],
        )


class FormularioTests(TestCase):
    def setUp(self):
        self.normal = TipoLiquidacion.objects.create(nombre="Liquidación Normal")
        self.aguinaldo = TipoLiquidacion.objects.create(nombre="Aguinaldo")

    def test_hay_que_elegir_al_menos_uno(self):
        formulario = LiquidacionesForm({})
        self.assertFalse(formulario.is_valid())
        self.assertIn("al menos un tipo de liquidación", formulario.errors["tipos_liquidacion"][0])

    def test_acepta_uno_o_varios(self):
        self.assertTrue(LiquidacionesForm({"tipos_liquidacion": [self.normal.pk, self.aguinaldo.pk]}).is_valid())

    def test_parte_de_lo_ya_elegido(self):
        implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
        ImplementacionLiquidacion.objects.create(implementacion=implementacion, tipo_liquidacion=self.aguinaldo, activo=True)
        ImplementacionLiquidacion.objects.create(implementacion=implementacion, tipo_liquidacion=self.normal, activo=False)
        formulario = LiquidacionesForm(implementacion=implementacion)
        self.assertEqual(formulario.fields["tipos_liquidacion"].initial, [self.aguinaldo.pk])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PasoDeConfiguracionTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.aguinaldo = TipoLiquidacion.objects.create(nombre="Aguinaldo", orden=1)

    def post(self, *tipos):
        return self.client.post(_url(self.implementacion, 6), {
            "tipo_firma": "digital", "segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [t.pk for t in tipos],
            "modelo_recibo": SimpleUploadedFile("m.pdf", b"%PDF-1.4"),
        })

    def test_muestra_los_tipos_en_orden(self):
        pagina = self.client.get(_url(self.implementacion, 6)).content.decode()
        self.assertLess(pagina.index("Liquidación Normal"), pagina.index("Aguinaldo"))

    def test_sin_elegir_ninguno_no_avanza(self):
        respuesta = self.post()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Elegí al menos un tipo de liquidación")

    def test_guarda_los_elegidos_y_deja_los_demas_inactivos(self):
        self.assertEqual(self.post(self.aguinaldo).status_code, 302)
        activos = self.implementacion.liquidaciones.filter(activo=True).values_list("tipo_liquidacion__nombre", flat=True)
        self.assertEqual(list(activos), ["Aguinaldo"])
        self.assertFalse(self.implementacion.liquidaciones.get(tipo_liquidacion=self.liquidacion).activo)

    def test_queda_en_el_historial_y_como_evento(self):
        self.post(self.aguinaldo, self.liquidacion)
        evento = EventoImplementacion.objects.get(accion="paso.guardado", seccion="liquidaciones")
        self.assertEqual(evento.actor_tipo, "cliente")
        self.assertEqual(evento.datos["cambios"]["Aguinaldo"], {"antes": None, "despues": True})
        self.assertTrue(self.implementacion.versiones.filter(seccion="liquidaciones").exists())

    def test_cambiar_la_eleccion_registra_el_antes_y_el_despues(self):
        self.post(self.aguinaldo, self.liquidacion)
        self.post(self.aguinaldo)
        ultimo = EventoImplementacion.objects.filter(seccion="liquidaciones").last()
        self.assertEqual(ultimo.datos["cambios"], {"Liquidación Normal": {"antes": True, "despues": False}})


class ControlDeFaltantesTests(BaseWizard):
    def test_con_recibo_digital_pide_elegir_un_tipo(self):
        mensajes = [(p["paso"], p["mensaje"]) for p in services.pendientes_de_envio(self.implementacion)]
        self.assertIn((6, "Elegir al menos un tipo de liquidación."), mensajes)

    def test_deja_de_pedirlo_cuando_hay_uno(self):
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], CLIENTE)
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertNotIn("Elegir al menos un tipo de liquidación.", mensajes)

    def test_sin_recibo_digital_no_se_pide(self):
        self.implementacion.modulos.update(activo=False)
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertNotIn("Elegir al menos un tipo de liquidación.", mensajes)

    def test_si_se_desactivan_todos_vuelve_a_pedirlo(self):
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], CLIENTE)
        services.guardar_liquidaciones(self.implementacion, [], CLIENTE)
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertIn("Elegir al menos un tipo de liquidación.", mensajes)


class VacacionesAutomaticasTests(BaseWizard):
    modulos = ["Novedades"]

    def setUp(self):
        super().setUp()
        self.vacaciones = TipoLicencia.objects.create(nombre="Vacaciones", automatica=True)
        self.otra = TipoLicencia.objects.create(nombre="Licencia por Mudanza")

    def formulario(self, datos=None):
        return LicenciasNovedadesForm(
            datos, licencias_qs=TipoLicencia.objects.all(), novedades_qs=[], estado_por_licencia={}, estado_por_novedad={},
        )

    def test_se_muestra_tildada_y_no_se_puede_cambiar(self):
        campo = self.formulario().fields[f"licencia_{self.vacaciones.id}_activo"]
        self.assertTrue(campo.disabled)
        self.assertTrue(campo.initial)

    def test_aunque_el_formulario_no_la_mande_queda_activa(self):
        formulario = self.formulario({f"licencia_{self.otra.id}_activo": "on"})
        self.assertTrue(formulario.is_valid())
        self.assertTrue(formulario.cleaned_data[f"licencia_{self.vacaciones.id}_activo"])

    def test_las_demas_siguen_siendo_opcionales(self):
        campo = self.formulario().fields[f"licencia_{self.otra.id}_activo"]
        self.assertFalse(campo.disabled)
        self.assertFalse(campo.initial)

    def test_el_paso_explica_que_se_crea_sola(self):
        self.assertContains(self.client.get(_url(self.implementacion, 8)), "Napsis la crea sola")

    def test_guardar_el_paso_la_deja_activa(self):
        self.client.post(_url(self.implementacion, 8), {f"licencia_{self.otra.id}_activo": "on"})
        self.assertTrue(self.implementacion.licencias.get(tipo_licencia=self.vacaciones).activo)


class PanelYResumenTests(test_asignado.BasePanel):
    def setUp(self):
        super().setUp()
        self.normal = TipoLiquidacion.objects.create(nombre="Liquidación Normal")
        self.aguinaldo = TipoLiquidacion.objects.create(nombre="Aguinaldo", orden=1)
        self.implementacion = Implementacion.objects.create(
            cliente=Cliente.objects.create(nombre="Empresa A"), mail_contacto="c@a.com",
        )
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_se_editan_desde_la_ficha(self):
        respuesta = self.client.post(self.url, {"accion": "actualizar_liquidaciones", "tipos_liquidacion": [self.aguinaldo.pk]})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            list(self.implementacion.liquidaciones.filter(activo=True).values_list("tipo_liquidacion__nombre", flat=True)),
            ["Aguinaldo"],
        )
        evento = EventoImplementacion.objects.get(seccion="liquidaciones")
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("implementador", "ana"))

    def test_sin_elegir_ninguno_vuelve_con_el_error(self):
        respuesta = self.client.post(self.url, {"accion": "actualizar_liquidaciones"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Elegí al menos un tipo de liquidación")

    def test_la_ficha_muestra_los_elegidos(self):
        services.guardar_liquidaciones(self.implementacion, [self.normal, self.aguinaldo], ANA)
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Tipos de liquidación")
        self.assertContains(pagina, "Liquidación Normal, Aguinaldo")

    def test_el_mail_al_equipo_los_incluye(self):
        from notifications.services import notificar_implementacion_completa

        services.guardar_liquidaciones(self.implementacion, [self.aguinaldo], ANA)
        with self.settings(IMPLEMENTATION_TEAM_EMAILS=["equipo@napsis.com"]):
            notificar_implementacion_completa(self.implementacion)
        self.assertIn("Tipos de liquidación: Aguinaldo", mail.outbox[0].body)
