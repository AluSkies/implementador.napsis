"""Paso de nómina y sucursales."""

from django.core.files.uploadedfile import SimpleUploadedFile

from clients.models import Cliente, Implementacion, Sucursal
from employees.models import Empleado
from onboarding.tests.base import BaseWizard, _url


class EdicionDeEmpleadosEnElWizardTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.empleado = self.agregar_empleado()

    def test_cada_empleado_tiene_su_boton_de_editar(self):
        self.assertContains(self.client.get(_url(self.implementacion, 4)), f'href="?editar={self.empleado.pk}"')

    def test_editar_abre_el_formulario_con_sus_datos(self):
        respuesta = self.client.get(_url(self.implementacion, 4) + f"?editar={self.empleado.pk}")
        self.assertContains(respuesta, "Editando a PEREZ, JUAN")
        self.assertEqual(respuesta.context["edicion_form"].instance, self.empleado)

    def test_guardar_los_cambios(self):
        respuesta = self.client.post(_url(self.implementacion, 4), {
            "accion": "guardar_edicion", "empleado_id": self.empleado.pk,
            "cuil": "20111111112", "nombre": "Juan Carlos", "apellido": "Pérez", "puesto": "Analista",
            "fecha_ingreso": "2020-01-01",
        })
        self.assertRedirects(respuesta, _url(self.implementacion, 4), fetch_redirect_response=False)
        self.empleado.refresh_from_db()
        self.assertEqual((self.empleado.nombre, self.empleado.puesto), ("JUAN CARLOS", "Analista"))
        self.assertTrue(self.implementacion.versiones.filter(seccion="empleados").exists())

    def test_un_dato_invalido_vuelve_a_mostrar_el_formulario_con_el_error(self):
        respuesta = self.client.post(_url(self.implementacion, 4), {
            "accion": "guardar_edicion", "empleado_id": self.empleado.pk, "cuil": "123", "nombre": "A", "apellido": "B",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "11 dígitos")
        self.empleado.refresh_from_db()
        self.assertEqual(self.empleado.cuil, "20111111112")

    def test_no_se_puede_editar_el_empleado_de_otra_implementacion(self):
        ajeno = Empleado.objects.create(
            implementacion=Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa B")),
            cuil="20999999990", nombre="AJENO", apellido="OTRO",
        )
        respuesta = self.client.get(_url(self.implementacion, 4) + f"?editar={ajeno.pk}")
        self.assertNotContains(respuesta, "Editando a")
        self.client.post(_url(self.implementacion, 4), {
            "accion": "guardar_edicion", "empleado_id": ajeno.pk, "cuil": "20999999990", "nombre": "X", "apellido": "Y",
        })
        ajeno.refresh_from_db()
        self.assertEqual(ajeno.nombre, "AJENO")

    def test_agregar_a_mano_con_un_cuil_repetido_avisa_en_vez_de_dar_error(self):
        respuesta = self.client.post(_url(self.implementacion, 4), {
            "accion": "agregar_manual", "cuil": "20-11111111-2", "nombre": "Otro", "apellido": "Distinto",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Ya hay un empleado cargado con ese CUIL")
        self.assertEqual(Empleado.objects.count(), 1)


class ImportacionEnElWizardTests(BaseWizard):
    def test_un_archivo_roto_se_muestra_como_error_y_no_como_pagina_de_error(self):

        respuesta = self.client.post(
            _url(self.implementacion, 4),
            {"accion": "importar", "archivo": SimpleUploadedFile("nomina.xlsx", b"no es excel")},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "No pudimos leer el archivo")
        self.assertEqual(Empleado.objects.count(), 0)


class SucursalesConservanLaAsignacionTests(BaseWizard):
    """Antes, volver a guardar el paso de sucursales las borraba y recreaba: cada empleado perdía la suya."""

    modulos = ["Fichada"]

    def _guardar(self, *sucursales):
        datos = {"form-TOTAL_FORMS": str(len(sucursales)), "form-INITIAL_FORMS": "0",
                 "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000"}
        for i, (nombre, calle) in enumerate(sucursales):
            datos.update({f"form-{i}-nombre": nombre, f"form-{i}-calle": calle})
        return self.client.post(_url(self.implementacion, 3), datos)

    def test_volver_a_guardar_no_desasigna_a_los_empleados(self):
        self._guardar(("Central", "Mitre"), ("Norte", "Belgrano"))
        central = Sucursal.objects.get(nombre="Central")
        empleado = Empleado.objects.create(
            implementacion=self.implementacion, cuil="20111111112", nombre="JUAN", apellido="PEREZ", sucursal=central,
        )
        self._guardar(("Central", "Mitre 123"), ("Norte", "Belgrano"))
        empleado.refresh_from_db()
        self.assertEqual(empleado.sucursal, central)
        self.assertEqual(Sucursal.objects.get(nombre="Central").calle, "Mitre 123")  # se actualizó
        self.assertEqual(Sucursal.objects.count(), 2)

    def test_las_que_se_sacan_se_borran_y_las_nuevas_se_crean(self):
        self._guardar(("Central", "Mitre"), ("Norte", "Belgrano"))
        self._guardar(("Central", "Mitre"), ("Sur", "Alsina"))
        self.assertEqual(set(Sucursal.objects.values_list("nombre", flat=True)), {"Central", "Sur"})


class PasoNominaTests(BaseWizard):
    def test_no_se_puede_continuar_sin_empleados(self):
        respuesta = self.client.post(_url(self.implementacion, 4), {"accion": "continuar"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "al menos un empleado")

    def test_con_un_empleado_continua(self):
        self.agregar_empleado()
        respuesta = self.client.post(_url(self.implementacion, 4), {"accion": "continuar"})
        self.assertEqual(respuesta.status_code, 302)
