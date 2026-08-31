from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from clients.models import Cliente, Implementacion
from employees.models import Empleado
from employees.services import (
    normalizar_cuil,
    normalizar_texto,
    parse_archivo_empleados,
    snapshot_empleados,
)


def _csv(contenido):
    return SimpleUploadedFile("nomina.csv", contenido.encode("utf-8"), content_type="text/csv")


class NormalizarTests(TestCase):
    def test_normalizar_texto_saca_tildes_y_pasa_a_mayusculas(self):
        self.assertEqual(normalizar_texto("García Núñez"), "GARCIA NUNEZ")

    def test_normalizar_texto_colapsa_espacios_de_mas(self):
        self.assertEqual(normalizar_texto("  Juan   Pérez  "), "JUAN PEREZ")

    def test_normalizar_texto_none_es_string_vacio(self):
        self.assertEqual(normalizar_texto(None), "")

    def test_normalizar_cuil_saca_guiones_y_espacios(self):
        self.assertEqual(normalizar_cuil("20-11111111-2"), "20111111112")

    def test_normalizar_cuil_none_es_string_vacio(self):
        self.assertEqual(normalizar_cuil(None), "")


class ParseArchivoEmpleadosTests(TestCase):
    def test_fila_valida_se_parsea_correctamente(self):
        archivo = _csv("CUIL,Nombre,Apellido,Mail\n20111111112,Juan,Pérez,juan@example.com\n")
        filas, errores = parse_archivo_empleados(archivo)

        self.assertEqual(errores, [])
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["cuil"], "20111111112")
        self.assertEqual(filas[0]["nombre"], "JUAN")
        self.assertEqual(filas[0]["apellido"], "PEREZ")
        self.assertEqual(filas[0]["mail"], "juan@example.com")

    def test_falta_un_campo_obligatorio(self):
        archivo = _csv("CUIL,Nombre,Apellido\n20111111112,Juan,\n")
        filas, errores = parse_archivo_empleados(archivo)

        self.assertEqual(filas, [])
        self.assertEqual(len(errores), 1)
        self.assertEqual(errores[0]["fila"], 2)
        self.assertIn("apellido", errores[0]["mensaje"])

    def test_cuil_invalido_por_longitud(self):
        archivo = _csv("CUIL,Nombre,Apellido\n123,Juan,Pérez\n")
        _filas, errores = parse_archivo_empleados(archivo)

        self.assertEqual(len(errores), 1)
        self.assertIn("CUIL inválido", errores[0]["mensaje"])

    def test_cuil_duplicado_dentro_del_archivo(self):
        archivo = _csv(
            "CUIL,Nombre,Apellido\n"
            "20111111112,Juan,Pérez\n"
            "20111111112,Otro,Empleado\n"
        )
        filas, errores = parse_archivo_empleados(archivo)

        self.assertEqual(len(filas), 1)
        self.assertEqual(len(errores), 1)
        self.assertIn("duplicado", errores[0]["mensaje"])
        self.assertEqual(errores[0]["fila"], 3)

    def test_header_con_variacion_de_mayusculas_y_espacios_igual_matchea(self):
        archivo = _csv("cuil ,  nombre,APELLIDO\n20111111112,Juan,Pérez\n")
        filas, errores = parse_archivo_empleados(archivo)

        self.assertEqual(errores, [])
        self.assertEqual(filas[0]["cuil"], "20111111112")

    def test_booleano_si_no(self):
        archivo = _csv(
            "CUIL,Nombre,Apellido,Es Supervisor (SI/NO),Home Office (SI/NO)\n"
            "20111111112,Juan,Pérez,SI,NO\n"
        )
        filas, _errores = parse_archivo_empleados(archivo)

        self.assertTrue(filas[0]["es_supervisor"])
        self.assertFalse(filas[0]["home_office"])


class SnapshotEmpleadosTests(TestCase):
    def test_devuelve_una_fila_por_empleado(self):
        cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        implementacion = Implementacion.objects.create(cliente=cliente)
        Empleado.objects.create(
            implementacion=implementacion, cuil="20111111112", nombre="Juan", apellido="Pérez",
            legajo="1001", puesto="Analista",
        )

        snapshot = snapshot_empleados(implementacion)

        self.assertEqual(snapshot, [
            {"CUIL": "20111111112", "Apellido y Nombre": "Pérez, Juan", "Legajo": "1001", "Puesto": "Analista"},
        ])

    def test_implementacion_sin_empleados_devuelve_lista_vacia(self):
        cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        implementacion = Implementacion.objects.create(cliente=cliente)
        self.assertEqual(snapshot_empleados(implementacion), [])
