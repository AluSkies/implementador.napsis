from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clients.models import Cliente, Implementacion

CUIT = "30-50001091-2"


class BasePanel(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_t", password="x", is_staff=True, is_superuser=True)
        self.ana = User.objects.create_user(username="ana", password="x", is_staff=True, first_name="Ana", last_name="Paz")
        self.cliente_user = User.objects.create_user(username="cliente_t", password="x")
        self.client.force_login(self.ana)

    def crear(self, **datos):
        return self.client.post(reverse("dashboard:home"), {"accion": "crear_implementacion", **datos})


class AltaConAsignadoTests(BasePanel):
    """El implementador asignado lleva la implementación y recibe sus notificaciones.
    Por defecto es quien la crea, pero se puede elegir a otro en el formulario."""

    def test_por_defecto_queda_asignada_a_quien_la_crea(self):
        self.crear(nombre="Empresa Nueva S.A.")
        implementacion = Implementacion.objects.get(cliente__nombre="Empresa Nueva S.A.")
        self.assertEqual(implementacion.implementador_asignado, self.ana)
        self.assertEqual(implementacion.creado_por, self.ana)

    def test_se_puede_asignar_a_otro_miembro_del_equipo(self):
        self.crear(nombre="Empresa Nueva S.A.", implementador_id=str(self.admin.pk))
        implementacion = Implementacion.objects.get(cliente__nombre="Empresa Nueva S.A.")
        self.assertEqual(implementacion.implementador_asignado, self.admin)
        self.assertEqual(implementacion.creado_por, self.ana)  # quién la creó no cambia

    def test_un_id_invalido_o_de_un_cliente_cae_a_quien_la_crea(self):
        for valor in ("abc", str(self.cliente_user.pk), "999999"):
            with self.subTest(valor=valor):
                self.crear(nombre=f"Empresa {valor}", implementador_id=valor)
                self.assertEqual(
                    Implementacion.objects.get(cliente__nombre=f"Empresa {valor}").implementador_asignado, self.ana,
                )

    def test_una_cuenta_dada_de_baja_no_se_puede_asignar(self):
        baja = User.objects.create_user(username="baja", password="x", is_staff=True, is_active=False)
        self.crear(nombre="Empresa Nueva S.A.", implementador_id=str(baja.pk))
        self.assertEqual(Implementacion.objects.get().implementador_asignado, self.ana)

    def test_el_formulario_ofrece_solo_al_equipo_activo_con_el_usuario_actual_elegido(self):
        User.objects.create_user(username="baja", password="x", is_staff=True, is_active=False)
        respuesta = self.client.get(reverse("dashboard:home"))
        ofrecidos = {u.username for u in respuesta.context["asignables"]}
        self.assertEqual(ofrecidos, {"admin_t", "ana"})
        self.assertContains(respuesta, "(vos)")


class AltaConRazonSocialYCuitTests(BasePanel):
    def test_razon_social_y_cuit_son_opcionales(self):
        self.crear(nombre="Empresa Nueva S.A.")
        cliente = Cliente.objects.get(nombre="Empresa Nueva S.A.")
        self.assertEqual((cliente.razon_social, cliente.cuits), ("", ""))

    def test_si_vienen_se_guardan_con_el_cuit_normalizado(self):
        self.crear(nombre="Fantasía", razon_social="Empresa Nueva S.A.", cuits="30500010912")
        cliente = Cliente.objects.get(nombre="Fantasía")
        self.assertEqual(cliente.razon_social, "Empresa Nueva S.A.")
        self.assertEqual(cliente.cuits, CUIT)

    def test_un_cuit_invalido_no_crea_nada_y_avisa(self):
        respuesta = self.crear(nombre="Empresa Nueva S.A.", cuits="30-50001091-3")
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Cliente.objects.filter(nombre="Empresa Nueva S.A.").exists())
        self.assertContains(respuesta, "no es válido")


class ReasignarYListadoTests(BasePanel):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(nombre="Empresa A")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente, implementador_asignado=self.ana)
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_se_puede_reasignar(self):
        self.client.post(self.url, {"accion": "reasignar", "implementador_id": str(self.admin.pk)})
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.implementador_asignado, self.admin)

    def test_no_se_puede_reasignar_a_un_cliente(self):
        self.client.post(self.url, {"accion": "reasignar", "implementador_id": str(self.cliente_user.pk)})
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.implementador_asignado, self.ana)

    def test_el_listado_muestra_el_asignado(self):
        self.assertContains(self.client.get(reverse("dashboard:home")), "Ana Paz")

    def test_una_implementacion_sin_asignado_no_rompe_el_listado_ni_el_detalle(self):
        """Regresión: el template evaluaba asignado.username aunque no hubiera asignado (500)."""
        Implementacion.objects.update(implementador_asignado=None)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "sin asignar")


class FechaDeImplementacionDelEquipoTests(BasePanel):
    """A diferencia del cliente, el equipo puede poner cualquier fecha."""

    def setUp(self):
        super().setUp()
        cliente = Cliente.objects.create(nombre="Empresa A")
        self.implementacion = Implementacion.objects.create(cliente=cliente)
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_puede_poner_una_fecha_de_manana_y_hasta_una_pasada(self):
        for fecha in ("2099-01-01", "2020-01-01"):
            with self.subTest(fecha=fecha):
                self.client.post(self.url, {"accion": "actualizar_fecha_productivo", "fecha_salida_productivo": fecha})
                self.implementacion.refresh_from_db()
                self.assertEqual(self.implementacion.fecha_salida_productivo.isoformat(), fecha)

    def test_queda_en_el_historial_con_el_nombre_del_usuario(self):
        self.client.post(self.url, {"accion": "actualizar_fecha_productivo", "fecha_salida_productivo": "2099-01-01"})
        self.assertEqual(self.implementacion.versiones.get(seccion="fecha_implementacion").editado_por, "ana")
