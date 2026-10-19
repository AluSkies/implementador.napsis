"""Editar después de validar pierde la validación."""

import tempfile

from django.test import override_settings
from django.utils import timezone

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Implementacion
from employees.forms import EmpleadoForm
from onboarding import acciones, services
from onboarding.tests.base import GEOMETRIA, EnviadaBase

ANA = Actor.implementador("ana")


def _eventos(accion):
    return EventoImplementacion.objects.filter(accion=accion)


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
