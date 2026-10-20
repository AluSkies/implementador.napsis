"""Logo y banner en los formularios y su acceso."""

import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import TipoLiquidacion
from clients.models import Cliente, Implementacion
from onboarding.forms import ConfiguracionForm, ImplementacionDatosForm
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


class CampoDeArchivoActualTests(TestCase):
    """Los archivos ya cargados se muestran con «Quitar» (que se puede deshacer) y «Reemplazar»; el modelo de
    recibo es obligatorio, así que solo se reemplaza."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        with override_settings(MEDIA_ROOT=self.media):
            self.implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
            self.implementacion.logo.save("logo.png", imagen(100, 100, "logo.png"))
            self.implementacion.modelo_recibo.save("recibo.pdf", SimpleUploadedFile("recibo.pdf", b"%PDF-1.4 x"))

    def pagina(self, **kwargs):
        with override_settings(MEDIA_ROOT=self.media):
            return str(ConfiguracionForm(instance=self.implementacion, **kwargs)["logo"]), str(
                ConfiguracionForm(instance=self.implementacion)["modelo_recibo"]
            )

    def test_el_logo_cargado_se_muestra_con_miniatura_y_boton_quitar(self):
        logo, _ = self.pagina()
        self.assertIn("archivo-actual-miniatura", logo)
        self.assertIn("data-quitar", logo)
        self.assertIn('name="logo-clear"', logo)
        self.assertIn("Reemplazar por otro archivo", logo)

    def test_sin_archivo_solo_ofrece_elegir_uno(self):
        implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="B"))
        html = str(ConfiguracionForm(instance=implementacion)["logo"])
        self.assertIn("Elegir un archivo", html)
        self.assertNotIn("data-quitar", html)

    def test_el_modelo_de_recibo_no_se_puede_quitar_solo_reemplazar(self):
        _, modelo = self.pagina()
        self.assertNotIn("data-quitar", modelo)
        self.assertNotIn("modelo_recibo-clear", modelo)
        self.assertIn("solo reemplazar", modelo)
        self.assertIn('type="file"', modelo)

    def test_marcar_quitar_y_guardar_borra_el_logo(self):
        tipo = TipoLiquidacion.objects.create(nombre="Normal")
        datos = {"segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [tipo.pk], "logo-clear": "on"}
        with override_settings(MEDIA_ROOT=self.media):
            formulario = ConfiguracionForm(datos, instance=self.implementacion)
            self.assertTrue(formulario.is_valid(), formulario.errors)
            formulario.save()
        self.implementacion.refresh_from_db()
        self.assertFalse(self.implementacion.logo)
        self.assertTrue(self.implementacion.modelo_recibo)


class ModeloDeReciboEsUnPdfTests(TestCase):
    """El modelo de recibo tiene que ser un PDF de verdad, lo cargue quien lo cargue (cliente, panel o admin)."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
        self.tipo = TipoLiquidacion.objects.create(nombre="Normal")

    def guardar(self, formulario_clase, archivo):
        datos = {"segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [self.tipo.pk], "razon_social": "A SA", "cuits": ""}
        with override_settings(MEDIA_ROOT=self.media):
            formulario = formulario_clase(datos, {"modelo_recibo": archivo}, instance=self.implementacion)
            return formulario, formulario.is_valid()

    def test_un_pdf_se_acepta_en_el_wizard_y_en_el_panel(self):
        for clase in (ConfiguracionForm, ImplementacionDatosForm):
            formulario, valido = self.guardar(clase, SimpleUploadedFile("m.pdf", b"%PDF-1.4 contenido"))
            self.assertTrue(valido, (clase.__name__, formulario.errors))

    def test_otro_tipo_de_archivo_se_rechaza_en_el_wizard_y_en_el_panel(self):
        for clase in (ConfiguracionForm, ImplementacionDatosForm):
            formulario, valido = self.guardar(clase, SimpleUploadedFile("m.docx", b"PK\x03\x04 no soy pdf"))
            self.assertFalse(valido, clase.__name__)
            self.assertIn("modelo_recibo", formulario.errors, clase.__name__)

    def test_un_archivo_renombrado_a_pdf_se_rechaza(self):
        for clase in (ConfiguracionForm, ImplementacionDatosForm):
            formulario, valido = self.guardar(clase, SimpleUploadedFile("m.pdf", b"MZ\x90\x00 es un ejecutable"))
            self.assertFalse(valido, clase.__name__)
            self.assertIn("no es un PDF válido", str(formulario.errors["modelo_recibo"]))
