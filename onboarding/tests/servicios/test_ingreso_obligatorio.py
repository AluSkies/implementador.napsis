"""Fecha de ingreso obligatoria con Recibo Digital."""

import io
from datetime import date

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from automatizacion.actores import Actor
from clients.models import Cliente, Implementacion, ImplementacionModulo, Modulo
from employees.forms import EmpleadoForm
from employees.models import Empleado
from employees.services import ArchivoInvalido, leer_archivo_empleados
from onboarding import services


def _implementacion(*codigos):
    implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa A"))
    for codigo in codigos:
        modulo, _ = Modulo.objects.get_or_create(nombre=codigo.replace("_", " ").title())
        ImplementacionModulo.objects.create(implementacion=implementacion, modulo=modulo, activo=True)
    return implementacion


ANA = Actor.implementador("ana")


def _xlsx(filas, cabecera):
    libro = openpyxl.Workbook()
    libro.active.append(cabecera)
    for fila in filas:
        libro.active.append(fila)
    buffer = io.BytesIO()
    libro.save(buffer)
    return SimpleUploadedFile("nomina.xlsx", buffer.getvalue())


class UsaModuloTests(TestCase):
    def test_solo_cuenta_si_esta_activo(self):
        implementacion = _implementacion("fichada")
        self.assertTrue(implementacion.usa_modulo(Modulo.FICHADA))
        self.assertFalse(implementacion.usa_modulo(Modulo.RECIBO_DIGITAL))
        implementacion.modulos.update(activo=False)
        self.assertFalse(implementacion.usa_modulo(Modulo.FICHADA))


class AltaManualTests(TestCase):
    def form(self, implementacion, **extra):
        datos = {"cuil": "20111111112", "nombre": "Juan", "apellido": "Pérez", **extra}
        return EmpleadoForm(datos, implementacion=implementacion)

    def test_con_recibo_digital_la_fecha_de_ingreso_es_obligatoria(self):
        formulario = self.form(_implementacion("recibo_digital"))
        self.assertFalse(formulario.is_valid())
        self.assertIn("fecha_ingreso", formulario.errors)

    def test_con_la_fecha_se_acepta(self):
        self.assertTrue(self.form(_implementacion("recibo_digital"), fecha_ingreso="2020-01-01").is_valid())

    def test_sin_recibo_digital_sigue_siendo_opcional(self):
        self.assertTrue(self.form(_implementacion("fichada")).is_valid())


class ImportacionTests(TestCase):
    CABECERA = ["CUIL", "Nombre", "Apellido", "Fecha Ingreso (DD/MM/AAAA)"]

    def test_con_recibo_digital_una_fila_sin_fecha_es_un_error_de_fila(self):
        archivo = _xlsx([[20111111112, "Juan", "Pérez", None], [20222222223, "Ana", "Gómez", "01/02/2021"]], self.CABECERA)
        resultado = leer_archivo_empleados(archivo, ingreso_obligatorio=True)
        self.assertEqual(len(resultado.filas), 1)
        self.assertIn("fecha_ingreso", resultado.errores[0]["mensaje"])

    def test_si_falta_la_columna_se_dice_una_vez(self):
        archivo = _xlsx([[20111111112, "Juan", "Pérez"]], ["CUIL", "Nombre", "Apellido"])
        with self.assertRaisesMessage(ArchivoInvalido, "faltan columnas obligatorias: Fecha Ingreso"):
            leer_archivo_empleados(archivo, ingreso_obligatorio=True)

    def test_sin_recibo_digital_no_se_exige(self):
        archivo = _xlsx([[20111111112, "Juan", "Pérez", None]], self.CABECERA)
        self.assertEqual(leer_archivo_empleados(archivo).errores, [])

    def test_el_servicio_lo_exige_solo_con_recibo_digital(self):
        con = _implementacion("recibo_digital")
        sin = _implementacion("fichada")
        archivo = lambda: _xlsx([[20111111112, "Juan", "Pérez", None]], self.CABECERA)  # noqa: E731
        _filas, errores, _a = services.importar_archivo_empleados(con, archivo(), ANA)
        self.assertEqual(len(errores), 1)
        filas, errores, _a = services.importar_archivo_empleados(sin, archivo(), ANA)
        self.assertEqual((len(filas), errores), (1, []))


class PendientesTests(TestCase):
    def test_avisa_cuantos_empleados_no_tienen_fecha_de_ingreso(self):
        implementacion = _implementacion("recibo_digital")
        Empleado.objects.create(implementacion=implementacion, cuil="20111111112", nombre="A", apellido="B")
        pendiente = next(p for p in services.pendientes_de_envio(implementacion) if "fecha de ingreso" in p["mensaje"])
        self.assertEqual(pendiente["paso"], services.PASO_NOMINA)
        self.assertIn("1 empleado ", pendiente["mensaje"])
        Empleado.objects.create(implementacion=implementacion, cuil="20222222223", nombre="C", apellido="D")
        pendiente = next(p for p in services.pendientes_de_envio(implementacion) if "fecha de ingreso" in p["mensaje"])
        self.assertIn("2 empleados", pendiente["mensaje"])

    def test_deja_de_aparecer_al_completarlas(self):
        implementacion = _implementacion("recibo_digital")
        Empleado.objects.create(
            implementacion=implementacion, cuil="20111111112", nombre="A", apellido="B", fecha_ingreso=date(2020, 1, 1),
        )
        self.assertFalse([p for p in services.pendientes_de_envio(implementacion) if "fecha de ingreso" in p["mensaje"]])

    def test_sin_recibo_digital_no_se_pide(self):
        implementacion = _implementacion("fichada")
        Empleado.objects.create(implementacion=implementacion, cuil="20111111112", nombre="A", apellido="B")
        self.assertFalse([p for p in services.pendientes_de_envio(implementacion) if "fecha de ingreso" in p["mensaje"]])
