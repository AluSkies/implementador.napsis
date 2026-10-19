"""Recibo Digital obligatorio, sucursales, firma observada y faltantes."""

import tempfile

from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse

from automatizacion.actores import Actor
from clients.models import Modulo, Sucursal
from onboarding import acciones, services
from onboarding.forms import ModulosForm
from onboarding.tests.base import GEOMETRIA, BaseWizard, EnviadaBase, _url

ANA = Actor.implementador("ana")
CLIENTE = Actor.cliente("cliente_a")


class ReciboDigitalObligatorioTests(BaseWizard):
    def recibo(self):
        return Modulo.objects.get(codigo=Modulo.RECIBO_DIGITAL)

    def test_el_equipo_no_lo_puede_sacar(self):
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), set(), ANA)
        self.assertTrue(self.implementacion.usa_modulo(Modulo.RECIBO_DIGITAL))

    def test_se_agrega_solo_al_crear_una_implementacion_sin_modulos(self):
        resultado = acciones.crear_implementacion(
            ANA, datos_cliente={"nombre": "Nueva S.A."}, modulo_ids=[], creado_por=None,
        )
        self.assertTrue(resultado.implementacion.usa_modulo(Modulo.RECIBO_DIGITAL))

    def test_en_el_formulario_figura_marcado_y_no_se_puede_cambiar(self):
        formulario = ModulosForm(modulos_qs=Modulo.objects.all(), activos_ids=set())
        campo = formulario.fields[f"modulo_{self.recibo().id}"]
        self.assertTrue(campo.disabled)
        self.assertTrue(campo.initial)
        self.assertIn("obligatorio", campo.label)

    def test_el_cliente_que_manda_todo_destildado_lo_conserva(self):
        self.implementacion.modulos_editables_por_cliente = True
        self.implementacion.save()
        otro, _ = Modulo.objects.get_or_create(nombre="Fichada")
        self.client.post(_url(self.implementacion, services.PASO_MODULOS), {})
        self.assertTrue(self.implementacion.usa_modulo(Modulo.RECIBO_DIGITAL))
        self.assertFalse(self.implementacion.usa_modulo(otro.codigo))

    def test_si_faltara_se_avisa_como_pendiente(self):
        self.implementacion.modulos.all().delete()
        mensajes = [(p["paso"], p["mensaje"]) for p in services.pendientes_de_envio(self.implementacion)]
        self.assertIn((services.PASO_MODULOS, "Recibo Digital es obligatorio en toda implementación."), mensajes)

    def test_en_el_panel_figura_marcado_y_como_obligatorio(self):
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        pagina = self.client.get(url)
        self.assertContains(pagina, "(obligatorio)")
        self.client.post(url, {"accion": "actualizar_modulos"})
        self.assertTrue(self.implementacion.usa_modulo(Modulo.RECIBO_DIGITAL))


class SucursalesConFichadaTests(BaseWizard):
    modulos = ["Recibo Digital", "Fichada"]

    def pasos(self):
        return [p["paso"] for p in services.pendientes_de_envio(self.implementacion)]

    def test_sin_sucursales_falta_cargar_una(self):
        self.assertIn(services.PASO_SUCURSALES, self.pasos())

    def test_con_una_con_nombre_alcanza(self):
        Sucursal.objects.create(implementacion=self.implementacion, nombre="Casa central")
        self.assertNotIn(services.PASO_SUCURSALES, self.pasos())

    def test_una_sin_nombre_no_cuenta(self):
        Sucursal.objects.create(implementacion=self.implementacion, nombre="", calle="Mitre")
        self.assertIn(services.PASO_SUCURSALES, self.pasos())

    def test_sin_fichada_no_se_pide(self):
        self.implementacion.modulos.filter(modulo__nombre="Fichada").update(activo=False)
        self.assertNotIn(services.PASO_SUCURSALES, self.pasos())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FirmaObservadaTests(EnviadaBase):
    def test_observada_no_se_puede_reenviar_sin_ajustarla(self):
        acciones.observar_firma(ANA, self.implementacion, ["ilegible"])
        mensajes = [(p["paso"], p["mensaje"]) for p in services.pendientes_de_envio(self.implementacion)]
        self.assertIn((services.PASO_FIRMA, "Ajustar la firma según lo que pidió el equipo de Napsis."), mensajes)

    def test_al_ajustarla_el_cliente_puede_reenviar(self):
        acciones.observar_firma(ANA, self.implementacion, ["ilegible"])
        services.guardar_firma(self.implementacion, CLIENTE, pagina="primera", geometria=GEOMETRIA)
        self.assertEqual(services.pendientes_de_envio(self.implementacion), [])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class QueFaltaParaValidarTests(EnviadaBase):
    def test_la_firma_propuesta_figura_como_lo_unico_que_falta(self):
        firma = self.implementacion.firma
        firma.estado = "propuesta"
        firma.save()
        self.assertEqual(services.pendientes_de_validacion(self.implementacion), ["Falta validar la firma del recibo."])

    def test_validada_la_firma_no_falta_nada(self):
        self.assertEqual(services.pendientes_de_validacion(self.implementacion), [])

    def test_la_ficha_lo_muestra_antes_de_apretar_validar(self):
        firma = self.implementacion.firma
        firma.estado = "propuesta"
        firma.save()
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        pagina = self.client.get(url)
        self.assertContains(pagina, "Para poder validar falta")
        self.assertContains(pagina, "Falta validar la firma del recibo.")

    def test_sin_faltantes_la_ficha_no_muestra_el_aviso(self):
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        self.assertNotContains(self.client.get(url), "Para poder validar falta")
