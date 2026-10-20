"""Crear o cambiar la contraseña: el motivo del rechazo se ve aparte de las reglas."""

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


class ClaveConfirmarTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("empresa-ejemplo", password="x")
        uid = urlsafe_base64_encode(force_bytes(self.usuario.pk))
        token = default_token_generator.make_token(self.usuario)
        self.url = self.client.get(f"/clave/nueva/{uid}/{token}/").url

    def enviar(self, clave):
        return self.client.post(self.url, {"new_password1": clave, "new_password2": clave})

    def test_una_clave_valida_se_guarda(self):
        self.assertEqual(self.enviar("Clave-Segura-2026!").status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("Clave-Segura-2026!"))

    def test_el_motivo_del_rechazo_sale_en_el_recuadro_de_error_y_no_entre_las_reglas(self):
        pagina = self.enviar("empresa2026").content.decode()
        recuadro = pagina.split('class="error-box"')[1].split("</span>")[0]
        self.assertIn("muy similar a nombre de usuario", recuadro)
        self.assertIn('class="reglas"', pagina)
        self.assertNotIn("muy similar a nombre de usuario", pagina.split('class="reglas"')[1].split("</span>")[0])
