from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clients.models import Cliente, Implementacion, Modulo


class AccesoDelPanelTests(TestCase):
    """@staff_member_required es lo único que impide que un cliente logueado
    entre al panel interno — sin esto, cualquier cuenta autenticada vería datos
    de otras empresas."""

    def setUp(self):
        self.cliente_user = User.objects.create_user(username="cliente_test", password="x")

    def test_anonimo_es_redirigido_al_login(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_cliente_no_staff_es_redirigido_al_login(self):
        self.client.force_login(self.cliente_user)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_staff_puede_entrar(self):
        staff = User.objects.create_user(username="admin_test", password="x", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)


class CrearImplementacionTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="admin_test", password="x", is_staff=True)
        self.client.force_login(self.staff)
        self.modulo_a = Modulo.objects.create(nombre="Módulo A")
        self.modulo_b = Modulo.objects.create(nombre="Módulo B")

    def test_crea_cliente_y_activa_solo_los_modulos_elegidos(self):
        response = self.client.post(reverse("dashboard:home"), {
            "accion": "crear_implementacion",
            "nombre": "Cliente Nuevo S.A.",
            "modulos": [str(self.modulo_a.id)],
        })

        implementacion = Implementacion.objects.get(cliente__nombre="Cliente Nuevo S.A.")
        self.assertRedirects(
            response, reverse("dashboard:implementacion_detalle", kwargs={"pk": implementacion.pk})
        )

        activos = set(
            implementacion.modulos.filter(activo=True).values_list("modulo__nombre", flat=True)
        )
        self.assertEqual(activos, {"Módulo A"})

    def test_crea_acceso_de_cliente_junto_con_la_implementacion(self):
        self.client.post(reverse("dashboard:home"), {
            "accion": "crear_implementacion", "nombre": "Cliente Nuevo S.A.", "modulos": [],
        })
        cliente = Cliente.objects.get(nombre="Cliente Nuevo S.A.")
        self.assertIsNotNone(cliente.usuario)
        self.assertFalse(cliente.usuario.is_staff)

    def test_registra_version_de_modulos_al_crear(self):
        """Regresión: antes de usar guardar_modulos() acá, la alta de módulos
        bypasseaba el versionado por completo."""
        self.client.post(reverse("dashboard:home"), {
            "accion": "crear_implementacion", "nombre": "Cliente Nuevo S.A.", "modulos": [str(self.modulo_a.id)],
        })
        implementacion = Implementacion.objects.get(cliente__nombre="Cliente Nuevo S.A.")
        self.assertTrue(implementacion.versiones.filter(seccion="modulos").exists())

    def test_valor_no_numerico_en_cliente_id_no_rompe(self):
        """Regresión: cliente_id/modulos con basura ya no debe tirar 500."""
        response = self.client.post(reverse("dashboard:home"), {
            "accion": "crear_implementacion", "cliente_id": "no-es-un-id",
            "nombre": "Otro Cliente S.A.", "modulos": ["abc", str(self.modulo_a.id)],
        })
        self.assertEqual(response.status_code, 302)
        implementacion = Implementacion.objects.get(cliente__nombre="Otro Cliente S.A.")
        activos = set(
            implementacion.modulos.filter(activo=True).values_list("modulo__nombre", flat=True)
        )
        self.assertEqual(activos, {"Módulo A"})


class ActualizarModulosTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="admin_test", password="x", is_staff=True)
        self.client.force_login(self.staff)
        self.modulo = Modulo.objects.create(nombre="Módulo A")
        cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=cliente)

    def test_valor_no_numerico_en_modulos_no_rompe(self):
        """Regresión: un valor no-entero en 'modulos' tiraba ValueError sin capturar (500)."""
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        response = self.client.post(url, {
            "accion": "actualizar_modulos", "modulos": ["abc", str(self.modulo.id)],
        })
        self.assertRedirects(response, url)
        self.assertTrue(
            self.implementacion.modulos.filter(modulo=self.modulo, activo=True).exists()
        )


class EliminarEmpleadoTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="admin_test", password="x", is_staff=True)
        self.client.force_login(self.staff)
        cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=cliente)

    def test_id_no_numerico_no_rompe(self):
        """Regresión: empleado_id="abc" tiraba ValueError sin capturar (500)."""
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})
        response = self.client.post(url, {"accion": "eliminar_empleado", "empleado_id": "abc"})
        self.assertRedirects(response, url)
