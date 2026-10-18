from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from clients.security import ip_del_cliente

CLAVE_OK = "clave-correcta-123"


class IpDelClienteTests(SimpleTestCase):
    """Sin esto, detrás del proxy todos los usuarios compartirían una IP (la del proxy)
    y el límite de intentos quedaría mal calculado o sería evadible."""

    def _request(self, **meta):
        return RequestFactory().get("/", **meta)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_sin_proxy_usa_remote_addr_e_ignora_el_header(self):
        request = self._request(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6")
        self.assertEqual(ip_del_cliente(request), "10.0.0.1")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_un_proxy_toma_la_ultima_entrada(self):
        request = self._request(REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.7")
        self.assertEqual(ip_del_cliente(request), "203.0.113.7")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_dos_proxies_toma_la_anteultima(self):
        request = self._request(REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR="203.0.113.7, 198.51.100.2")
        self.assertEqual(ip_del_cliente(request), "203.0.113.7")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_sin_header_cae_a_remote_addr(self):
        self.assertEqual(ip_del_cliente(self._request(REMOTE_ADDR="172.18.0.1")), "172.18.0.1")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_header_mas_corto_que_los_proxies_cae_a_remote_addr(self):
        request = self._request(REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.assertEqual(ip_del_cliente(request), "172.18.0.1")


@override_settings(TRUSTED_PROXY_COUNT=0)
class LimiteDeIntentosTests(TestCase):
    """5 fallos seguidos (misma IP + mismo usuario) bloquean ese par; el login es público
    y estará expuesto a internet, así que no puede permitir fuerza bruta."""

    def setUp(self):
        User.objects.create_user(username="cliente_a", password=CLAVE_OK)
        User.objects.create_user(username="cliente_b", password=CLAVE_OK)
        self.url = reverse("login")

    def _intentar(self, usuario="cliente_a", clave="incorrecta", **extra):
        return self.client.post(self.url, {"username": usuario, "password": clave}, **extra)

    def _fallar(self, veces, **kwargs):
        for _ in range(veces):
            self._intentar(**kwargs)

    def test_con_cuatro_fallos_todavia_se_puede_entrar(self):
        self._fallar(4)
        self.assertEqual(self._intentar(clave=CLAVE_OK).status_code, 302)

    def test_al_quinto_fallo_se_bloquea_aun_con_la_clave_correcta(self):
        self._fallar(5)
        respuesta = self._intentar(clave=CLAVE_OK)
        self.assertEqual(respuesta.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_el_mensaje_de_bloqueo_esta_en_castellano(self):
        self._fallar(5)
        self.assertContains(self._intentar(clave=CLAVE_OK), "Acceso bloqueado temporalmente", status_code=429)

    def test_otro_usuario_desde_la_misma_ip_no_se_ve_afectado(self):
        self._fallar(5)
        respuesta = self._intentar(usuario="cliente_b", clave=CLAVE_OK)
        self.assertEqual(respuesta.status_code, 302)

    def test_el_mismo_usuario_desde_otra_ip_no_se_ve_afectado(self):
        """Evita que alguien deje afuera a un cliente ajeno solo nombrándolo."""
        self._fallar(5, REMOTE_ADDR="10.0.0.9")
        respuesta = self._intentar(clave=CLAVE_OK, REMOTE_ADDR="10.0.0.10")
        self.assertEqual(respuesta.status_code, 302)

    def test_un_ingreso_correcto_reinicia_la_cuenta(self):
        self._fallar(4)
        self.assertEqual(self._intentar(clave=CLAVE_OK).status_code, 302)
        self.client.logout()
        self._fallar(4)  # sin el reinicio serían 8 fallos acumulados: ya estaría bloqueado
        self.assertEqual(self._intentar(clave=CLAVE_OK).status_code, 302)

    def test_tambien_protege_el_login_del_admin(self):
        url_admin = reverse("admin:login")
        for _ in range(5):
            self.client.post(url_admin, {"username": "cliente_a", "password": "incorrecta"})
        respuesta = self.client.post(url_admin, {"username": "cliente_a", "password": CLAVE_OK})
        self.assertEqual(respuesta.status_code, 429)


@override_settings(TRUSTED_PROXY_COUNT=1)
class LimiteDetrasDelProxyTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="cliente_a", password=CLAVE_OK)
        self.url = reverse("login")

    def _intentar(self, forwarded, clave="incorrecta"):
        return self.client.post(
            self.url, {"username": "cliente_a", "password": clave},
            REMOTE_ADDR="172.18.0.1", HTTP_X_FORWARDED_FOR=forwarded,
        )

    def test_inventar_el_x_forwarded_for_no_evade_el_bloqueo(self):
        for i in range(5):
            self._intentar(f"1.1.1.{i}, 203.0.113.7")  # entrada inventada distinta cada vez
        self.assertEqual(self._intentar("2.2.2.2, 203.0.113.7", CLAVE_OK).status_code, 429)

    def test_otro_cliente_real_detras_del_mismo_proxy_no_queda_bloqueado(self):
        for _ in range(5):
            self._intentar("203.0.113.7")
        self.assertEqual(self._intentar("198.51.100.9", CLAVE_OK).status_code, 302)
