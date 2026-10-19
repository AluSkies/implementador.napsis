from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()
CLAVE_NUEVA = "una-clave-larga-9XqT"


class PerfilTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("ana", password="clave-vieja-123", is_staff=True)
        self.url = reverse("perfil")

    def test_exige_sesion(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)

    def test_el_menu_de_usuario_tiene_mi_perfil_y_salir(self):
        self.client.force_login(self.usuario)
        html = self.client.get(self.url).content.decode()
        menu = html[html.index('class="menu-usuario"'):html.index("</details>")]
        self.assertIn(f'href="{self.url}"', menu)
        self.assertIn("Mi perfil", menu)
        self.assertIn("Salir", menu)
        self.assertIn("<svg", menu)  # la hamburguesa

    def test_cambia_la_contrasena_y_conserva_la_sesion(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(self.url, {
            "old_password": "clave-vieja-123", "new_password1": CLAVE_NUEVA, "new_password2": CLAVE_NUEVA,
        })
        self.assertRedirects(respuesta, self.url)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(CLAVE_NUEVA))
        self.assertEqual(self.client.get(self.url).status_code, 200)  # sigue logueada

    def test_con_la_clave_actual_incorrecta_no_cambia_nada(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(self.url, {
            "old_password": "otra", "new_password1": CLAVE_NUEVA, "new_password2": CLAVE_NUEVA,
        })
        self.assertEqual(respuesta.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("clave-vieja-123"))

    def test_tambien_lo_usan_los_clientes(self):
        cliente = User.objects.create_user("cli", password="clave-vieja-123")
        self.client.force_login(cliente)
        self.assertEqual(self.client.get(self.url).status_code, 200)
