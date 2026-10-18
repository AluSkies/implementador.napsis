"""Logo y banner en los formularios y su acceso."""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from clients.models import Cliente, Implementacion
from onboarding.forms import ImplementacionDatosForm
from onboarding.tests.base import BaseWizard, _url, imagen


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FormulariosTests(BaseWizard):
    def datos(self, **archivos):
        return {
            "tipo_firma": "digital", "segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [self.liquidacion.pk],
            "modelo_recibo": SimpleUploadedFile("m.pdf", b"%PDF-1.4"), **archivos,
        }

    def test_un_logo_en_medida_se_guarda(self):
        respuesta = self.client.post(_url(self.implementacion, 6), self.datos(logo=imagen(180, 90, "logo.png")))
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertTrue(self.implementacion.logo)

    def test_un_logo_grande_se_rechaza_y_no_se_guarda_nada(self):
        respuesta = self.client.post(_url(self.implementacion, 6), self.datos(logo=imagen(400, 400, "logo.png")))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("200 × 200", respuesta.context["form"].errors["logo"][0])
        self.implementacion.refresh_from_db()
        self.assertFalse(self.implementacion.logo)
        self.assertFalse(self.implementacion.modelo_recibo)  # el paso no se guardó

    def test_un_banner_fuera_de_medida_se_rechaza(self):
        respuesta = self.client.post(_url(self.implementacion, 6), self.datos(banner=imagen(800, 100, "banner.png")))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("1500 × 200", respuesta.context["form"].errors["banner"][0])

    def test_un_banner_en_medida_se_guarda(self):
        respuesta = self.client.post(_url(self.implementacion, 6), self.datos(banner=imagen(1550, 300, "banner.png")))
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertTrue(self.implementacion.banner)

    def test_ambas_son_opcionales(self):
        self.assertEqual(self.client.post(_url(self.implementacion, 6), self.datos()).status_code, 302)

    def test_una_imagen_ya_guardada_no_se_vuelve_a_validar_al_reenviar_el_paso(self):
        self.implementacion.logo.save("logo.png", imagen(100, 100), save=True)
        self.assertEqual(self.client.post(_url(self.implementacion, 6), self.datos()).status_code, 302)

    def test_el_paso_avisa_las_medidas_antes_de_subir(self):
        pagina = self.client.get(_url(self.implementacion, 6)).content.decode()
        self.assertIn("hasta 200 × 200 px", pagina)
        self.assertIn("entre 1500 × 200 y 1600 × 400 px", pagina)

    def test_el_formulario_del_panel_aplica_las_mismas_reglas(self):
        cliente = Cliente.objects.create(nombre="Empresa B")
        implementacion = Implementacion.objects.create(cliente=cliente)
        formulario = ImplementacionDatosForm(
            {"razon_social": "B S.A.", "cuits": "30-50001091-2", "telefono": "", "mail_contacto": ""},
            {"logo": imagen(300, 300, "logo.png")}, instance=implementacion,
        )
        self.assertFalse(formulario.is_valid())
        self.assertIn("logo", formulario.errors)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AccesoAlLogoTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.implementacion.logo.save("logo.png", imagen(100, 100), save=True)

    def test_el_cliente_dueno_lo_ve(self):
        self.assertEqual(self.client.get(reverse("media", kwargs={"ruta": self.implementacion.logo.name})).status_code, 200)

    def test_otro_cliente_no(self):
        from django.contrib.auth.models import User

        ajeno = User.objects.create_user("cliente_b", password="x")
        Cliente.objects.create(nombre="Empresa B", usuario=ajeno)
        self.client.force_login(ajeno)
        ruta = self.implementacion.logo.name
        self.assertEqual(self.client.get(reverse("media", kwargs={"ruta": ruta})).status_code, 404)

    def test_el_equipo_lo_ve(self):
        from django.contrib.auth.models import User

        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        self.assertEqual(self.client.get(reverse("media", kwargs={"ruta": self.implementacion.logo.name})).status_code, 200)

    def test_queda_en_el_historial_de_datos(self):
        from clients.services import foto_de_seccion

        self.assertIn("logo", foto_de_seccion(self.implementacion, "datos_contacto")["Logo"])
