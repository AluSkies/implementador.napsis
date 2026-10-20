"""La firma en la ficha del panel y acceso a sus archivos."""

import tempfile

from dashboard.tests.base import crear_supervisor
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from clients.models import Cliente, UbicacionFirma
from onboarding.tests.base import BaseWizard, _url, datos_de_formulario


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PanelYArchivosTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.completar_todo()
        self.firma = self.implementacion.firma
        self.firma.estado = UbicacionFirma.ESTADO_PROPUESTA
        self.firma.save()
        self.implementacion.modelo_recibo.save("m.pdf", SimpleUploadedFile("m.pdf", b"%PDF-1.4"))
        self.ana = crear_supervisor("ana")
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def como_equipo(self):
        self.client.force_login(self.ana)

    def test_la_ficha_muestra_la_firma_con_sus_acciones(self):
        self.como_equipo()
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Firma del recibo")
        self.assertContains(pagina, "Propuesta por el cliente")
        self.assertContains(pagina, "Validar firma")
        self.assertContains(pagina, "Corregir la firma desde acá")
        self.assertContains(pagina, 'data-solo-lectura="1"')

    def test_sin_recibo_digital_la_ficha_no_muestra_la_firma(self):
        self.como_equipo()
        self.implementacion.modulos.update(activo=False)
        self.assertNotContains(self.client.get(self.url), "Firma del recibo")

    def test_validar_desde_la_ficha(self):
        self.como_equipo()
        self.client.post(self.url, {"accion": "validar_firma"})
        self.assertEqual(self.implementacion.firma.estado, "validada")
        self.assertNotContains(self.client.get(self.url), "Validar firma")

    def test_observar_desde_la_ficha(self):
        self.como_equipo()
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        self.client.post(self.url, {"accion": "observar_firma", "motivos": ["baja_calidad"], "comentario": "Está pixelada."})
        self.assertEqual(self.implementacion.firma.estado, "observada")
        self.assertEqual(self.implementacion.rondas.count(), 1)

    def test_corregir_desde_la_ficha_guarda_y_valida(self):
        self.como_equipo()
        respuesta = self.client.post(self.url, {"accion": "corregir_firma", **datos_de_formulario(empresa_x=25)})
        self.assertEqual(respuesta.status_code, 302)
        firma = self.implementacion.firma
        self.assertEqual((firma.estado, firma.geometria["empresa"]["x"], firma.validada_por), ("validada", 0.25, "ana"))

    def test_corregir_con_datos_invalidos_vuelve_con_el_error(self):
        self.como_equipo()
        respuesta = self.client.post(self.url, {"accion": "corregir_firma", **datos_de_formulario(empresa_x=95)})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "el recuadro se sale de la página")
        self.assertEqual(self.implementacion.firma.estado, "propuesta")

    def test_el_cliente_dueno_ve_su_firma_y_otro_cliente_no(self):
        ruta = reverse("media", kwargs={"ruta": self.firma.imagen.name})
        self.assertEqual(self.client.get(ruta).status_code, 200)
        ajeno = User.objects.create_user("cliente_b", password="x")
        Cliente.objects.create(nombre="Empresa B", usuario=ajeno)
        self.client.force_login(ajeno)
        self.assertEqual(self.client.get(ruta).status_code, 404)

    def test_enviada_el_cliente_ve_su_firma_en_solo_lectura(self):
        self.implementacion.enviado = self.implementacion.creado
        self.implementacion.save()
        pagina = self.client.get(_url(self.implementacion, 1))
        self.assertContains(pagina, "Así quedó ubicada la firma")
        self.assertContains(pagina, 'data-solo-lectura="1"')
