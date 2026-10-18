import tempfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from clients.models import Cliente, Implementacion


class PortalLoginViewTests(TestCase):
    """Un solo login para staff y clientes, que redirige según el rol. La parte
    delicada (clients/views.py:PortalLoginView.get_success_url) es no honrar un
    ?next= que no corresponde al rol logueado — si no, un cliente con un link
    viejo a /panel/ termina en un loop infinito login -> panel -> login."""

    def setUp(self):
        self.staff = User.objects.create_user(username="admin_test", password="x", is_staff=True)
        self.cliente_user = User.objects.create_user(username="cliente_test", password="x")
        Cliente.objects.create(nombre="Empresa de Prueba", usuario=self.cliente_user)

    def test_staff_logueado_es_redirigido_al_panel(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_cliente_logueado_es_redirigido_a_sus_implementaciones(self):
        self.client.force_login(self.cliente_user)
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("onboarding:mis_implementaciones"))

    def test_cliente_con_next_al_panel_no_hace_loop(self):
        """Regresión: antes de este chequeo, next=/panel/ para un no-staff mandaba
        al panel, que lo rebotaba de nuevo al login con el mismo next -> loop."""
        self.client.force_login(self.cliente_user)
        response = self.client.get(reverse("login") + "?next=/panel/")
        self.assertRedirects(response, reverse("onboarding:mis_implementaciones"))

    def test_staff_con_next_al_panel_lo_honra(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("login") + "?next=/panel/clientes/999/")
        self.assertRedirects(response, "/panel/clientes/999/", fetch_redirect_response=False)

    def test_login_de_staff_funciona(self):
        response = self.client.post(reverse("login"), {"username": "admin_test", "password": "x"})
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_login_de_cliente_no_staff_no_entra_al_panel(self):
        """No hay un login separado para staff: cualquiera puede loguearse acá,
        pero el panel sigue bloqueado por @staff_member_required."""
        self.client.force_login(self.cliente_user)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_anonimo_no_entra_al_panel(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MediaProtegidaTests(TestCase):
    """Los adjuntos de un cliente (banner, modelo de recibo) no pueden ser públicos
    ni visibles para otro cliente — la app los sirve con permisos en vez del proxy."""

    def setUp(self):
        self.staff = User.objects.create_user(username="admin_test", password="x", is_staff=True)
        self.dueno = User.objects.create_user(username="dueno", password="x")
        self.otro = User.objects.create_user(username="otro", password="x")
        self.cliente = Cliente.objects.create(nombre="Dueño S.A.", usuario=self.dueno)
        Cliente.objects.create(nombre="Otro S.A.", usuario=self.otro)
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)
        self.implementacion.banner.save("banner.png", ContentFile(b"contenido-banner"))
        self.url = self.implementacion.banner.url

    def test_anonimo_es_redirigido_al_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_staff_puede_descargarlo(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"contenido-banner")

    def test_el_cliente_dueno_puede_descargarlo(self):
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_otro_cliente_recibe_404(self):
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_archivo_inexistente_es_404(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/media/implementaciones/banners/no-existe.png").status_code, 404)

    def test_no_se_puede_salir_de_media_con_dos_puntos(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/media/../manage.py").status_code, 404)
        self.assertEqual(self.client.get("/media/implementaciones/../../manage.py").status_code, 404)
