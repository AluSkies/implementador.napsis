"""El CUIL se escribe con o sin guiones, se guarda con los 11 dígitos y se muestra siempre con guiones."""

import io
import tempfile
from datetime import date

import openpyxl
from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from clients.models import Cliente, Implementacion, PersonaRol
from employees.forms import EmpleadoForm
from employees.models import Empleado
from employees.services import formatear_cuil, generar_nomina_xlsx, normalizar_cuil
from onboarding.services import PASO_NOMINA, PASO_ROLES
from onboarding.tests.base import BaseWizard, _url


class FormatearTests(SimpleTestCase):
    def test_agrega_los_guiones_si_no_estan(self):
        self.assertEqual(formatear_cuil("20111111112"), "20-11111111-2")

    def test_deja_igual_el_que_ya_los_tiene(self):
        self.assertEqual(formatear_cuil("20-11111111-2"), "20-11111111-2")

    def test_tolera_espacios_y_otros_separadores(self):
        self.assertEqual(formatear_cuil(" 20 11111111 2 "), "20-11111111-2")
        self.assertEqual(formatear_cuil("20.11111111.2"), "20-11111111-2")

    def test_lo_que_no_tiene_11_digitos_se_muestra_tal_cual(self):
        self.assertEqual(formatear_cuil("2011"), "2011")
        self.assertEqual(formatear_cuil("201111111123"), "201111111123")

    def test_vacio_o_nulo(self):
        self.assertEqual(formatear_cuil(""), "")
        self.assertEqual(formatear_cuil(None), "")

    def test_es_lo_inverso_de_normalizar(self):
        self.assertEqual(normalizar_cuil(formatear_cuil("20111111112")), "20111111112")

    def test_el_filtro_de_las_plantillas(self):
        html = Template("{% load cuil %}{{ valor|cuil }}").render(Context({"valor": "27333333334"}))
        self.assertEqual(html, "27-33333333-4")


class FormularioDeEmpleadoTests(TestCase):
    def setUp(self):
        self.implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
        self.empleado = Empleado.objects.create(
            implementacion=self.implementacion, cuil="20111111112", nombre="ANA", apellido="GOMEZ", fecha_ingreso=date(2020, 1, 1),
        )

    def datos(self, cuil):
        return {"cuil": cuil, "nombre": "ANA", "apellido": "GOMEZ", "fecha_ingreso": "2020-01-01"}

    def editar(self, cuil):
        return EmpleadoForm(self.datos(cuil), instance=self.empleado, implementacion=self.implementacion)

    def test_al_editar_se_ve_con_guiones(self):
        formulario = EmpleadoForm(instance=self.empleado, implementacion=self.implementacion)
        self.assertIn('value="20-11111111-2"', str(formulario["cuil"]))

    def test_acepta_los_dos_formatos_y_guarda_los_11_digitos(self):
        for texto in ("20-11111111-2", "20111111112"):
            with self.subTest(texto=texto):
                formulario = self.editar(texto)
                self.assertTrue(formulario.is_valid(), formulario.errors)
                self.assertEqual(formulario.cleaned_data["cuil"], "20111111112")

    def test_escribirlo_con_otro_formato_no_cuenta_como_un_cambio(self):
        for texto in ("20-11111111-2", "20111111112"):
            with self.subTest(texto=texto):
                formulario = self.editar(texto)
                self.assertTrue(formulario.is_valid())
                self.assertNotIn("cuil", formulario.changed_data)

    def test_cambiar_de_verdad_el_cuil_si_cuenta(self):
        formulario = self.editar("20-22222222-3")
        self.assertTrue(formulario.is_valid())
        self.assertIn("cuil", formulario.changed_data)

    def test_con_guiones_o_sin_ellos_es_el_mismo_empleado_repetido(self):
        otro = EmpleadoForm({**self.datos("20-11111111-2"), "nombre": "OTRA"}, implementacion=self.implementacion)
        self.assertFalse(otro.is_valid())
        self.assertIn("Ya hay un empleado cargado con ese CUIL.", otro.errors["cuil"])

    def test_un_cuil_corto_se_rechaza_con_un_mensaje_claro(self):
        formulario = EmpleadoForm(self.datos("20-1111-2"), implementacion=self.implementacion)
        self.assertFalse(formulario.is_valid())
        self.assertIn("11 dígitos", formulario.errors["cuil"][0])


class NominaDescargadaTests(TestCase):
    def test_la_planilla_que_baja_el_equipo_trae_los_cuil_con_guiones(self):
        implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
        jefe = Empleado.objects.create(implementacion=implementacion, cuil="20111111112", nombre="J", apellido="J")
        Empleado.objects.create(
            implementacion=implementacion, cuil="27333333334", nombre="E", apellido="E", reporta_a=jefe, aprobador=jefe,
        )
        buffer = generar_nomina_xlsx(implementacion.empleados.order_by("cuil"))
        hoja = openpyxl.load_workbook(io.BytesIO(buffer.getvalue())).active
        encabezados = [c.value for c in hoja[1]]
        fila = dict(zip(encabezados, [c.value for c in hoja[3]], strict=True))
        self.assertEqual(fila["CUIL"], "27-33333333-4")
        self.assertEqual(fila["Reporta A (CUIL)"], "20-11111111-2")
        self.assertEqual(fila["Aprobador (CUIL)"], "20-11111111-2")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PantallasTests(BaseWizard):
    def role(self, cuil="20111111112"):
        return PersonaRol.objects.create(
            implementacion=self.implementacion, rol="apoderado", apellido_nombre="Gómez, Ana", cuil=cuil,
        )

    def test_la_nomina_del_wizard_muestra_los_cuil_con_guiones(self):
        self.agregar_empleado("20111111112", "ANA", "GOMEZ")
        pagina = self.client.get(_url(self.implementacion, PASO_NOMINA)).content.decode()
        self.assertIn("<td>20-11111111-2</td>", pagina)
        self.assertNotIn("<td>20111111112</td>", pagina)

    def test_los_roles_guardados_vuelven_a_mostrarse_con_guiones(self):
        self.agregar_empleado("20111111112", "ANA", "GOMEZ")
        self.role()
        pagina = self.client.get(_url(self.implementacion, PASO_ROLES)).content.decode()
        self.assertIn('value="20-11111111-2"', pagina)

    def test_la_ficha_del_equipo_muestra_nomina_y_roles_con_guiones(self):
        self.agregar_empleado("20111111112", "ANA", "GOMEZ")
        self.role()
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        ficha = self.client.get(url).content.decode()
        self.assertIn("<td>20-11111111-2</td>", ficha)
        self.assertNotIn("<td>20111111112</td>", ficha)

    def test_los_roles_se_aceptan_con_o_sin_guiones_y_se_guardan_con_los_digitos(self):
        self.agregar_empleado("20111111112", "ANA", "GOMEZ")
        self.agregar_empleado("20222222223", "LUIS", "RUIZ")
        for texto in ("20-11111111-2", "20111111112"):
            filas = [("apoderado", "Gómez, Ana", texto), ("liquidador", "Ruiz, Luis", "20-22222222-3"), ("admin_rrhh", "Sosa, Eva", "")]
            datos = {"form-TOTAL_FORMS": "3", "form-INITIAL_FORMS": "0", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "6"}
            for i, (rol, nombre, cuil) in enumerate(filas):
                datos.update({f"form-{i}-rol": rol, f"form-{i}-apellido_nombre": nombre, f"form-{i}-cuil": cuil})
            respuesta = self.client.post(_url(self.implementacion, PASO_ROLES), datos)
            self.assertEqual(respuesta.status_code, 302, texto)
            self.assertEqual(self.implementacion.roles.get(rol="apoderado").cuil, "20111111112", texto)
            self.assertEqual(self.implementacion.roles.get(rol="liquidador").cuil, "20222222223", texto)
