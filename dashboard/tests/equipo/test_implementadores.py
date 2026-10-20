from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clients.models import Cliente, Implementacion
from dashboard import services

LISTA = "dashboard:implementadores"
DATOS_ALTA = {"username": "lramos", "first_name": "Lucía", "last_name": "Ramos", "email": "lramos@napsislatam.com", "rol": "implementador"}


class BaseRoles(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_t", password="x", is_staff=True, is_superuser=True)
        self.impl = User.objects.create_user(username="impl_t", password="x", is_staff=True)
        self.cliente_user = User.objects.create_user(username="cliente_t", password="x")
        Cliente.objects.create(nombre="Empresa de Prueba", usuario=self.cliente_user)

    def detalle(self, usuario):
        return reverse("dashboard:implementador_detalle", kwargs={"pk": usuario.pk})


class AccesoPorRolTests(BaseRoles):
    """Solo el Admin administra implementadores. Un implementador recibe 403 (y no un
    redirect al login, que lo devolvería al mismo lugar y armaría un loop)."""

    def test_anonimo_va_al_login(self):
        respuesta = self.client.get(reverse(LISTA))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)

    def test_cliente_no_entra(self):
        self.client.force_login(self.cliente_user)
        respuesta = self.client.get(reverse(LISTA))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)

    def test_implementador_recibe_403_en_lista_y_detalle(self):
        self.client.force_login(self.impl)
        self.assertEqual(self.client.get(reverse(LISTA)).status_code, 403)
        self.assertEqual(self.client.get(self.detalle(self.impl)).status_code, 403)

    def test_implementador_no_puede_crear_cuentas(self):
        self.client.force_login(self.impl)
        self.assertEqual(self.client.post(reverse(LISTA), DATOS_ALTA).status_code, 403)
        self.assertFalse(User.objects.filter(username="lramos").exists())

    def test_implementador_no_puede_dar_de_baja_a_otros_ni_resetear_claves(self):
        self.client.force_login(self.impl)
        otro = User.objects.create_user(username="otro", password="clave-original", is_staff=True)
        self.assertEqual(self.client.post(self.detalle(otro), {"accion": "dar_de_baja"}).status_code, 403)
        self.assertEqual(self.client.post(self.detalle(otro), {"accion": "resetear_password"}).status_code, 403)
        otro.refresh_from_db()
        self.assertTrue(otro.is_active)
        self.assertTrue(otro.check_password("clave-original"))

    def test_el_implementador_sigue_usando_el_resto_del_panel(self):
        self.client.force_login(self.impl)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)

    def test_el_admin_entra(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse(LISTA)).status_code, 200)


class MenuSegunRolTests(BaseRoles):
    def test_el_admin_ve_el_link_a_implementadores_y_su_rol(self):
        self.client.force_login(self.admin)
        pagina = self.client.get(reverse("dashboard:home"))
        self.assertContains(pagina, reverse(LISTA))
        self.assertContains(pagina, "(Admin)")

    def test_el_implementador_no_ve_el_link_y_se_identifica_como_implementador(self):
        self.client.force_login(self.impl)
        pagina = self.client.get(reverse("dashboard:home"))
        self.assertNotContains(pagina, reverse(LISTA))
        self.assertContains(pagina, "(Implementador)")


class AltaDeImplementadorTests(BaseRoles):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_crea_un_implementador_sin_privilegios_de_admin(self):
        self.client.post(reverse(LISTA), DATOS_ALTA)
        nuevo = User.objects.get(username="lramos")
        self.assertTrue(nuevo.is_staff)
        self.assertFalse(nuevo.is_superuser)
        self.assertEqual(nuevo.get_full_name(), "Lucía Ramos")

    def test_no_se_puede_crear_un_admin_mandando_campos_de_mas(self):
        self.client.post(reverse(LISTA), {**DATOS_ALTA, "is_superuser": "on", "is_staff": "", "is_active": ""})
        nuevo = User.objects.get(username="lramos")
        self.assertFalse(nuevo.is_superuser)
        self.assertTrue(nuevo.is_staff)
        self.assertTrue(nuevo.is_active)

    def test_muestra_la_password_una_sola_vez_y_sirve_para_ingresar(self):
        respuesta = self.client.post(reverse(LISTA), DATOS_ALTA, follow=True)
        aviso = " ".join(str(m) for m in respuesta.context["messages"])
        self.assertIn("lramos", aviso)
        password = aviso.split("contraseña: ")[1].split(" ")[0]

        self.client.logout()
        ingreso = self.client.post(reverse("login"), {"username": "lramos", "password": password})
        self.assertRedirects(ingreso, reverse("dashboard:home"))

    def test_rechaza_un_usuario_repetido_sin_distinguir_mayusculas(self):
        respuesta = self.client.post(reverse(LISTA), {**DATOS_ALTA, "username": "IMPL_T"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Ya existe una cuenta con ese usuario")
        self.assertEqual(User.objects.filter(username__iexact="impl_t").count(), 1)

    def test_todos_los_campos_son_obligatorios(self):
        respuesta = self.client.post(reverse(LISTA), {"username": "sinmail"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(User.objects.filter(username="sinmail").exists())


class ListadoTests(BaseRoles):
    def test_lista_solo_implementadores_no_admins_ni_clientes(self):
        self.client.force_login(self.admin)
        nombres = [u.username for u in self.client.get(reverse(LISTA)).context["implementadores"]]
        self.assertEqual(nombres, ["impl_t"])

    def test_cuenta_las_implementaciones_que_creo_cada_uno(self):
        cliente = Cliente.objects.get(nombre="Empresa de Prueba")
        Implementacion.objects.create(cliente=cliente, creado_por=self.impl)
        Implementacion.objects.create(cliente=cliente, creado_por=self.impl)
        self.assertEqual(services.implementadores().get(pk=self.impl.pk).creadas, 2)

    def test_un_admin_o_un_cliente_no_se_pueden_abrir_por_esta_pantalla(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.detalle(self.admin)).status_code, 404)
        self.assertEqual(self.client.get(self.detalle(self.cliente_user)).status_code, 404)


class ModificacionYBajaTests(BaseRoles):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_modifica_los_datos_pero_no_el_usuario(self):
        self.client.post(self.detalle(self.impl), {
            "accion": "guardar", "rol": "implementador", "first_name": "Nuevo", "last_name": "Nombre", "email": "nuevo@napsislatam.com",
            "username": "intento_de_cambio",
        })
        self.impl.refresh_from_db()
        self.assertEqual(self.impl.first_name, "Nuevo")
        self.assertEqual(self.impl.email, "nuevo@napsislatam.com")
        self.assertEqual(self.impl.username, "impl_t")

    def test_resetear_password_invalida_la_anterior(self):
        self.client.post(self.detalle(self.impl), {"accion": "resetear_password"})
        self.impl.refresh_from_db()
        self.assertFalse(self.impl.check_password("x"))

    def test_dar_de_baja_corta_el_ingreso_y_reactivar_lo_devuelve(self):
        self.client.post(self.detalle(self.impl), {"accion": "dar_de_baja"})
        self.impl.refresh_from_db()
        self.assertFalse(self.impl.is_active)

        otro_navegador = self.client_class()
        self.assertEqual(otro_navegador.post(reverse("login"), {"username": "impl_t", "password": "x"}).status_code, 200)

        self.client.post(self.detalle(self.impl), {"accion": "reactivar"})
        self.impl.refresh_from_db()
        self.assertTrue(self.impl.is_active)
        self.assertEqual(otro_navegador.post(reverse("login"), {"username": "impl_t", "password": "x"}).status_code, 302)

    def test_la_baja_corta_la_sesion_que_ya_estaba_abierta(self):
        sesion_del_implementador = self.client_class()
        sesion_del_implementador.force_login(self.impl)
        self.assertEqual(sesion_del_implementador.get(reverse("dashboard:home")).status_code, 200)

        self.client.post(self.detalle(self.impl), {"accion": "dar_de_baja"})

        self.assertEqual(sesion_del_implementador.get(reverse("dashboard:home")).status_code, 302)

    def test_la_baja_conserva_la_cuenta_y_lo_que_creo(self):
        cliente = Cliente.objects.get(nombre="Empresa de Prueba")
        implementacion = Implementacion.objects.create(cliente=cliente, creado_por=self.impl)
        self.client.post(self.detalle(self.impl), {"accion": "dar_de_baja"})
        implementacion.refresh_from_db()
        self.assertEqual(implementacion.creado_por, self.impl)
