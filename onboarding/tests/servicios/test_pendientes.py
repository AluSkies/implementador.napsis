"""Qué falta para poder enviar."""

from django.test import TestCase

from clients.models import (
    Cliente,
    Implementacion,
    ImplementacionModulo,
    Modulo,
    PersonaRol,
)
from employees.models import Empleado
from onboarding import services


class PendientesDeEnvioTests(TestCase):
    """Qué falta para poder enviar depende de los módulos contratados: sin Recibo Digital
    no se pide el modelo de recibo, y sin Recibo Digital ni Legajos no se piden roles."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def _activar(self, *nombres):
        for nombre in nombres:
            modulo, _ = Modulo.objects.get_or_create(nombre=nombre)
            ImplementacionModulo.objects.create(implementacion=self.implementacion, modulo=modulo, activo=True)

    def _pasos(self):
        return [p["paso"] for p in services.pendientes_de_envio(self.implementacion)]

    def test_sin_modulos_pide_empresa_nomina_y_el_modulo_obligatorio(self):
        self.assertEqual(self._pasos(), [1, 2, 4])  # el paso 2 es Recibo Digital, obligatorio

    def test_con_recibo_digital_pide_tambien_roles_y_modelo_de_recibo(self):
        self._activar("Recibo Digital")
        self.assertEqual(self._pasos(), [1, 4, 5, 6, 6, 7])  # modelo de recibo, tipos de liquidación y firma

    def test_con_legajos_pide_roles_pero_no_modelo_de_recibo(self):
        self._activar("Legajos")
        self.assertEqual(self._pasos(), [1, 2, 4, 5])

    def test_con_fichada_pide_al_menos_una_sucursal(self):
        self._activar("Fichada")
        self.assertEqual(self._pasos(), [1, 2, 3, 4])

    def test_la_razon_social_sola_no_alcanza_hace_falta_el_cuit(self):
        self.cliente.razon_social = "Empresa S.A."
        self.cliente.save()
        self.assertIn(1, self._pasos())

    def test_sin_recibo_digital_lo_unico_que_falta_con_todo_lo_demas_cargado_es_el_modulo(self):
        self.cliente.razon_social = "Empresa S.A."
        self.cliente.cuits = "30-50001091-2"
        self.cliente.save()
        Empleado.objects.create(implementacion=self.implementacion, cuil="20111111112", nombre="A", apellido="B")
        self.assertEqual(
            services.pendientes_de_envio(self.implementacion),
            [{"paso": 2, "mensaje": "Recibo Digital es obligatorio en toda implementación."}],
        )

    def test_un_rol_sin_nombre_no_cuenta(self):
        self._activar("Legajos")
        for rol in (PersonaRol.ROL_APODERADO, PersonaRol.ROL_LIQUIDADOR):
            PersonaRol.objects.create(implementacion=self.implementacion, rol=rol, apellido_nombre="X, Y")
        PersonaRol.objects.create(implementacion=self.implementacion, rol=PersonaRol.ROL_ADMIN_RRHH, apellido_nombre="")
        self.assertIn(5, self._pasos())
