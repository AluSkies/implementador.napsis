"""Alta, edición y baja de empleados."""

from django.test import TestCase

from automatizacion.actores import Actor
from clients.models import Cliente, Implementacion
from employees.forms import EmpleadoForm
from onboarding import services

TEST = Actor.implementador("Test")


class EmpleadosTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def test_agregar_empleado_guarda_version_antes_del_alta(self):
        form = EmpleadoForm(
            {"cuil": "20333333334", "nombre": "Ana", "apellido": "López"},
            implementacion=self.implementacion,
        )
        agregado = services.agregar_empleado(self.implementacion, form, TEST)

        self.assertTrue(agregado)
        self.assertEqual(self.implementacion.empleados.count(), 1)
        version = self.implementacion.versiones.get(seccion="empleados")
        self.assertEqual(version.datos, [])  # no había empleados al momento del snapshot

    def test_agregar_empleado_con_form_invalido_no_guarda_nada(self):
        form = EmpleadoForm({"cuil": ""}, implementacion=self.implementacion)
        agregado = services.agregar_empleado(self.implementacion, form, TEST)

        self.assertFalse(agregado)
        self.assertEqual(self.implementacion.empleados.count(), 0)
        self.assertFalse(self.implementacion.versiones.filter(seccion="empleados").exists())

    def test_eliminar_empleado_con_id_valido(self):
        form = EmpleadoForm(
            {"cuil": "20333333334", "nombre": "Ana", "apellido": "López"},
            implementacion=self.implementacion,
        )
        services.agregar_empleado(self.implementacion, form, TEST)
        empleado_id = self.implementacion.empleados.get().id

        services.eliminar_empleado(self.implementacion, str(empleado_id), TEST)

        self.assertEqual(self.implementacion.empleados.count(), 0)

    def test_eliminar_empleado_con_id_no_numerico_no_rompe(self):
        """Regresión: esto tiraba ValueError sin capturar (500) antes del fix."""
        try:
            services.eliminar_empleado(self.implementacion, "no-es-un-id", TEST)
        except ValueError:
            self.fail("eliminar_empleado no debería propagar ValueError ante un id inválido")

    def test_eliminar_empleado_con_id_no_numerico_no_guarda_version(self):
        services.eliminar_empleado(self.implementacion, "abc", TEST)
        self.assertFalse(self.implementacion.versiones.filter(seccion="empleados").exists())
