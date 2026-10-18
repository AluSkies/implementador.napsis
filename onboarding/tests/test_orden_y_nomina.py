import json


from clients.models import Cliente, Implementacion, Sucursal
from employees.models import Empleado
from onboarding import services
from onboarding.tests.test_wizard import BaseWizard, _url


class OrdenDelWizardTests(BaseWizard):
    """Nómina antes que roles (para elegir de ahí a las personas) y sucursales antes que la
    nómina (para asignar a cada empleado la suya)."""

    modulos = ["Recibo Digital", "Fichada", "Novedades", "Legajos"]

    def test_el_orden_de_los_pasos(self):
        self.assertEqual(
            (services.PASO_DATOS, services.PASO_MODULOS, services.PASO_SUCURSALES, services.PASO_NOMINA,
             services.PASO_ROLES, services.PASO_CONFIGURACION, services.PASO_LICENCIAS,
             services.PASO_DOCUMENTOS, services.PASO_REVISION),
            tuple(range(1, 10)),
        )
        self.assertEqual(services.pasos_activos(self.implementacion), list(range(1, 10)))

    def test_la_nomina_viene_antes_que_los_roles_y_las_sucursales_antes_que_la_nomina(self):
        self.assertLess(services.PASO_NOMINA, services.PASO_ROLES)
        self.assertLess(services.PASO_SUCURSALES, services.PASO_NOMINA)

    def test_cada_paso_muestra_su_titulo(self):
        titulos = {4: "Carga de empleados", 5: "Apoderado/s, Liquidador y Admin. de RRHH", 3: "Sucursales"}
        for paso, titulo in titulos.items():
            with self.subTest(paso=paso):
                self.assertContains(self.client.get(_url(self.implementacion, paso)), titulo)

    def test_al_guardar_las_sucursales_se_sigue_con_la_nomina(self):
        datos = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "0", "form-MIN_NUM_FORMS": "0",
                 "form-MAX_NUM_FORMS": "1000", "form-0-nombre": "Central", "form-0-calle": "Mitre"}
        respuesta = self.client.post(_url(self.implementacion, 3), datos)
        self.assertRedirects(respuesta, _url(self.implementacion, 4), fetch_redirect_response=False)

    def test_al_continuar_la_nomina_se_sigue_con_los_roles(self):
        self.agregar_empleado()
        respuesta = self.client.post(_url(self.implementacion, 4), {"accion": "continuar"})
        self.assertRedirects(respuesta, _url(self.implementacion, 5), fetch_redirect_response=False)

    def test_los_pendientes_de_envio_apuntan_al_paso_correcto(self):
        pendientes = {p["paso"]: p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)}
        self.assertIn("Cargar la nómina", pendientes[4])
        self.assertIn("rol", pendientes[5])
        self.assertIn("modelo de recibo", pendientes[6])


class RolesDesdeLaNominaTests(BaseWizard):
    def test_con_nomina_ofrece_elegir_a_las_personas(self):
        Empleado.objects.create(
            implementacion=self.implementacion, cuil="20111111112", nombre="JUAN", apellido="PEREZ", mail="j@x.com",
        )
        respuesta = self.client.get(_url(self.implementacion, 5))
        self.assertContains(respuesta, 'id="nomina-lista"')
        self.assertContains(respuesta, "PEREZ, JUAN — 20111111112")
        datos = json.loads(
            respuesta.content.decode().split('id="nomina-datos" type="application/json">')[1].split("</script>")[0]
        )
        self.assertEqual(datos[0]["cuil"], "20111111112")
        self.assertEqual(datos[0]["apellido_nombre"], "PEREZ, JUAN")
        self.assertEqual(datos[0]["mail"], "j@x.com")

    def test_el_buscador_aparece_en_cada_fila(self):
        self.agregar_empleado()
        respuesta = self.client.get(_url(self.implementacion, 5))
        self.assertEqual(respuesta.content.decode().count('class="elegir-de-nomina"'), 6)

    def test_sin_nomina_sugiere_cargarla_primero(self):
        respuesta = self.client.get(_url(self.implementacion, 5))
        self.assertNotContains(respuesta, "nomina-lista")
        self.assertContains(respuesta, "primero cargás la nómina")

    def test_solo_ofrece_los_empleados_de_esta_implementacion(self):
        otro = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa B"))
        Empleado.objects.create(implementacion=otro, cuil="20999999990", nombre="AJENO", apellido="OTRO")
        self.assertNotContains(self.client.get(_url(self.implementacion, 5)), "AJENO")


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
        from django.core.files.uploadedfile import SimpleUploadedFile

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
