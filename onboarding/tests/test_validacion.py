"""Reglas de validación: qué impide validar o cumplir, qué invalida una validación y Recibo Digital obligatorio."""

import tempfile

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Implementacion, Modulo, Sucursal
from employees.forms import EmpleadoForm
from onboarding import acciones, services
from onboarding.forms import ModulosForm
from onboarding.tests.test_firma import GEOMETRIA
from onboarding.tests.test_rondas import EnviadaBase
from onboarding.tests.test_wizard import BaseWizard, _url

CLIENTE = Actor.cliente("cliente_a")
ANA = Actor.implementador("ana")


def _eventos(accion):
    return EventoImplementacion.objects.filter(accion=accion)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CumplirTests(EnviadaBase):
    def test_solo_se_cumple_lo_que_esta_validado(self):
        resultado = acciones.marcar_cumplida(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_PENDIENTE)
        self.assertIn("ya validada", resultado.avisos[0].texto)
        self.assertFalse(_eventos("estado.cumplida").exists())
        self.assertEqual(mail.outbox, [])

    def test_validada_si_se_cumple(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        acciones.marcar_cumplida(ANA, self.implementacion)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CUMPLIDA)

    def test_no_se_cumple_lo_que_el_cliente_no_envio(self):
        otra = Implementacion.objects.create(cliente=self.cliente, validada_en=timezone.now())
        acciones.marcar_cumplida(ANA, otra)
        self.assertEqual(otra.estado, Implementacion.ESTADO_PENDIENTE)

    def test_no_se_cumple_una_cancelada(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        acciones.anular(ANA, self.implementacion)
        acciones.marcar_cumplida(ANA, self.implementacion)
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_CANCELADA)

    def test_un_pedido_directo_al_panel_tampoco_la_cumple(self):
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        self.client.post(url, {"accion": "marcar_cumplida"})
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_PENDIENTE)

    def test_la_ficha_ofrece_cumplir_solo_si_esta_validada(self):
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        self.assertNotContains(self.client.get(url), "Marcar implementación como cumplida")
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertContains(self.client.get(url), "Marcar implementación como cumplida")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class EditarDespuesDeValidarTests(EnviadaBase):
    """Si el equipo cambia algo de lo que se va a configurar, la validación se pierde."""

    def setUp(self):
        super().setUp()
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertIsNotNone(self.implementacion.validada_en)

    def assertRevocada(self, seccion):
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.validada_en)
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_COMPLETADO_CLIENTE)
        evento = _eventos("estado.validacion_revocada").get()
        self.assertEqual((evento.seccion, evento.actor_ref), (seccion, "ana"))

    def assertSigueValidada(self):
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.validada_en)
        self.assertFalse(_eventos("estado.validacion_revocada").exists())

    def test_cambiar_los_tipos_de_liquidacion(self):
        services.guardar_liquidaciones(self.implementacion, [], ANA)
        self.assertRevocada("liquidaciones")

    def test_guardar_lo_mismo_no_la_invalida(self):
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], ANA)
        self.assertSigueValidada()

    def test_cambiar_la_fecha_de_implementacion_no_la_invalida(self):
        services.guardar_fecha_implementacion(self.implementacion, timezone.localdate(), ANA)
        self.assertSigueValidada()

    def test_cambiar_la_razon_social_o_el_modelo_de_recibo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from onboarding.forms import ImplementacionDatosForm

        formulario = ImplementacionDatosForm(
            {"razon_social": "Otra S.A.", "cuits": "30-50001091-2", "telefono": "", "mail_contacto": ""},
            {"modelo_recibo": SimpleUploadedFile("nuevo.pdf", b"%PDF-1.4 otro")}, instance=self.implementacion,
        )
        self.assertTrue(formulario.is_valid(), formulario.errors)
        services.guardar_datos_contacto(self.implementacion, formulario, ANA)
        self.assertRevocada("datos_contacto")

    def test_cambiar_los_roles(self):
        from onboarding.forms import rol_formset_obligatorio

        roles = [
            {"rol": r.rol, "apellido_nombre": "Cambiado, X" if r.rol == "admin_rrhh" else r.apellido_nombre,
             "cuil": r.cuil, "mail": r.mail}
            for r in self.implementacion.roles.all()
        ]
        datos = {"roles-TOTAL_FORMS": len(roles), "roles-INITIAL_FORMS": 0, "roles-MIN_NUM_FORMS": 0, "roles-MAX_NUM_FORMS": 6}
        for i, rol in enumerate(roles):
            for campo, valor in rol.items():
                datos[f"roles-{i}-{campo}"] = valor
        formset = rol_formset_obligatorio(6, cuils_nomina={r["cuil"] for r in roles if r["cuil"]})(datos, prefix="roles")
        self.assertTrue(formset.is_valid(), formset.errors)
        services.guardar_roles(self.implementacion, formset, ANA)
        self.assertRevocada("roles")

    def test_agregar_un_empleado(self):
        formulario = EmpleadoForm(
            {"cuil": "20333333334", "nombre": "Ana", "apellido": "Paz", "fecha_ingreso": "2020-01-01"},
            implementacion=self.implementacion,
        )
        self.assertTrue(services.agregar_empleado(self.implementacion, formulario, ANA))
        self.assertRevocada("empleados")

    def test_editar_un_empleado_solo_si_algo_cambio(self):
        empleado = self.implementacion.empleados.first()
        datos = {"cuil": empleado.cuil, "nombre": empleado.nombre, "apellido": empleado.apellido,
                 "fecha_ingreso": empleado.fecha_ingreso.isoformat()}
        igual = EmpleadoForm(datos, instance=empleado, implementacion=self.implementacion)
        self.assertTrue(services.editar_empleado(self.implementacion, igual, ANA))
        self.assertSigueValidada()
        distinto = EmpleadoForm({**datos, "nombre": "Otro"}, instance=empleado, implementacion=self.implementacion)
        self.assertTrue(services.editar_empleado(self.implementacion, distinto, ANA))
        self.assertRevocada("empleados")

    def test_eliminar_un_empleado(self):
        empleado = self.implementacion.empleados.exclude(cuil__in=[r.cuil for r in self.implementacion.roles.all()]).first()
        if empleado is None:
            empleado = self.agregar_empleado("20444444445", "Z", "Z")
            self.implementacion.refresh_from_db()
        services.eliminar_empleado(self.implementacion, empleado.pk, ANA)
        self.assertRevocada("empleados")

    def test_importar_nomina_con_empleados_nuevos_o_distintos(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        def csv(texto):
            return SimpleUploadedFile("nomina.csv", texto.encode(), content_type="text/csv")

        contenido = "CUIL;Nombre;Apellido;Fecha Ingreso (DD/MM/AAAA)" + chr(10) + "20555555556;Eva;Sosa;01/01/2021" + chr(10)
        services.importar_archivo_empleados(self.implementacion, csv(contenido), ANA)
        self.assertRevocada("empleados")

    def test_reimportar_lo_mismo_no_cambia_nada_y_no_la_invalida(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        empleado = self.implementacion.empleados.first()
        cabecera = "CUIL;Nombre;Apellido;Fecha Ingreso (DD/MM/AAAA)"
        datos = f"{empleado.cuil};{empleado.nombre};{empleado.apellido};01/01/2020"
        fila = cabecera + chr(10) + datos + chr(10)
        services.importar_archivo_empleados(self.implementacion, SimpleUploadedFile("n.csv", fila.encode()), ANA)
        self.assertSigueValidada()

    def test_corregir_la_firma_desde_el_panel(self):
        corregida = {**GEOMETRIA, "empresa": {"x": 0.3, "y": 0.5, "ancho": 0.2, "alto": 0.1}}
        services.guardar_firma(self.implementacion, ANA, pagina="ultima", geometria=corregida)
        self.assertRevocada("firma")

    def test_volver_a_aprobar_despues_de_corregir_funciona(self):
        services.guardar_liquidaciones(self.implementacion, [], ANA)
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], ANA)
        self.assertTrue(acciones.aprobar_para_configurar(ANA, self.implementacion).ok)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.validada_en)

    def test_una_cumplida_no_pierde_su_fecha_por_una_edicion_posterior(self):
        acciones.marcar_cumplida(ANA, self.implementacion)
        validada = Implementacion.objects.get(pk=self.implementacion.pk).validada_en
        services.guardar_liquidaciones(self.implementacion, [], ANA)
        self.assertEqual(Implementacion.objects.get(pk=self.implementacion.pk).validada_en, validada)


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
