from django.contrib.auth.models import User
from django.test import TestCase

from clients.models import Cliente, Implementacion
from clients.services import (
    crear_o_resetear_acceso,
    filtrar_y_ordenar_implementaciones,
    generar_password,
    guardar_version,
    registrar_snapshot_builder,
)


class GenerarPasswordTests(TestCase):
    def test_longitud_y_alfabeto_legible(self):
        """Sin 0/O/1/I/l — son justo los caracteres que un cliente puede transcribir
        mal desde un mail o un papel."""
        password = generar_password()
        self.assertEqual(len(password), 10)
        for caracter in "0O1Il":
            self.assertNotIn(caracter, password)


class CrearOResetearAccesoTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Constructora Demo S.A.")

    def test_crea_usuario_nuevo_sin_privilegios_de_staff(self):
        username, password = crear_o_resetear_acceso(self.cliente)
        self.cliente.refresh_from_db()

        self.assertIsNotNone(self.cliente.usuario)
        self.assertEqual(self.cliente.usuario.username, username)
        self.assertFalse(self.cliente.usuario.is_staff)
        self.assertTrue(self.cliente.usuario.check_password(password))

    def test_usa_el_username_sugerido_slugificado(self):
        username, _password = crear_o_resetear_acceso(self.cliente, username="Constructora Demo")
        self.assertEqual(username, "constructora-demo")

    def test_evita_colision_de_username_agregando_sufijo(self):
        User.objects.create_user(username="constructora-demo", password="x")
        username, _password = crear_o_resetear_acceso(self.cliente, username="Constructora Demo")
        self.assertEqual(username, "constructora-demo2")

    def test_resetear_no_crea_un_segundo_usuario(self):
        username_1, password_1 = crear_o_resetear_acceso(self.cliente)
        self.cliente.refresh_from_db()

        username_2, password_2 = crear_o_resetear_acceso(self.cliente)
        self.cliente.refresh_from_db()

        self.assertEqual(username_1, username_2)
        self.assertNotEqual(password_1, password_2)
        self.assertEqual(User.objects.filter(username=username_1).count(), 1)

    def test_resetear_fuerza_is_staff_false(self):
        """Si alguna vez a esta cuenta la promovieron a staff a mano, un reset de
        contraseña de cliente no debería dejarla con acceso al panel interno."""
        crear_o_resetear_acceso(self.cliente)
        self.cliente.refresh_from_db()
        self.cliente.usuario.is_staff = True
        self.cliente.usuario.save()

        crear_o_resetear_acceso(self.cliente)
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.usuario.is_staff)


class FiltrarYOrdenarImplementacionesTests(TestCase):
    def setUp(self):
        self.cliente_a = Cliente.objects.create(nombre="Andina Construcciones")
        self.cliente_b = Cliente.objects.create(nombre="Bavaria Alimentos")
        self.pendiente = Implementacion.objects.create(cliente=self.cliente_a)
        self.cumplida = Implementacion.objects.create(
            cliente=self.cliente_b, estado=Implementacion.ESTADO_CUMPLIDA,
        )

    def _pks(self, params):
        qs = filtrar_y_ordenar_implementaciones(Implementacion.objects.all(), params)
        return list(qs.values_list("pk", flat=True))

    def test_filtra_por_nombre_de_cliente_parcial_e_insensible_a_mayusculas(self):
        self.assertEqual(self._pks({"cliente": "andina"}), [self.pendiente.pk])

    def test_filtra_por_estado_visual(self):
        self.assertEqual(self._pks({"estado": "completo"}), [self.cumplida.pk])
        self.assertEqual(self._pks({"estado": "a_completar"}), [self.pendiente.pk])

    def test_estado_invalido_no_filtra_nada(self):
        pks = self._pks({"estado": "no-existe"})
        self.assertCountEqual(pks, [self.pendiente.pk, self.cumplida.pk])

    def test_ordenar_por_columna_desconocida_cae_a_creado(self):
        # No debe tirar, y debe devolver ambas.
        pks = self._pks({"ordenar": "columna-inventada"})
        self.assertCountEqual(pks, [self.pendiente.pk, self.cumplida.pk])


class RegistroDeSnapshotBuildersTests(TestCase):
    """guardar_version() delega en el registro de _SNAPSHOT_BUILDERS — este es el
    mecanismo por el que employees (y cualquier otra app) puede aportar su propio
    snapshot sin que clients tenga que importarla."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def test_registrar_snapshot_builder_agrega_una_seccion_nueva(self):
        llamadas = []

        def builder_de_prueba(implementacion):
            llamadas.append(implementacion.pk)
            return {"ok": True}

        registrar_snapshot_builder("seccion_de_prueba", builder_de_prueba)
        try:
            version = guardar_version(self.implementacion, "seccion_de_prueba", "Test")
            self.assertEqual(llamadas, [self.implementacion.pk])
            self.assertEqual(version.datos, {"ok": True})
        finally:
            # No contaminar otros tests con una sección que no existe realmente.
            from clients.services import _SNAPSHOT_BUILDERS
            _SNAPSHOT_BUILDERS.pop("seccion_de_prueba", None)

    def test_empleados_ya_esta_registrado_por_la_app_employees(self):
        """Si employees.apps.EmployeesConfig.ready() no corrió o se rompió, esto
        avisa acá en vez de fallar recién cuando alguien borre un empleado."""
        from clients.services import _SNAPSHOT_BUILDERS
        self.assertIn("empleados", _SNAPSHOT_BUILDERS)

    def test_guardar_version_usa_el_builder_registrado_para_datos_contacto(self):
        self.implementacion.telefono = "011-4000-0000"
        self.implementacion.save(update_fields=["telefono"])

        version = guardar_version(self.implementacion, "datos_contacto", "Test")
        self.assertEqual(version.datos["Teléfono"], "011-4000-0000")
        self.assertEqual(version.editado_por, "Test")
        self.assertEqual(version.seccion, "datos_contacto")
