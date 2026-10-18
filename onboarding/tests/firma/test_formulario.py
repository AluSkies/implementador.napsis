"""Formulario de la firma: imagen y recuadros."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from onboarding.forms import FirmaForm
from onboarding.tests.base import GEOMETRIA, datos_de_formulario, imagen


class FormularioTests(SimpleTestCase):
    def formulario(self, archivo=None, **cambios):
        return FirmaForm(datos_de_formulario(**cambios), {"imagen": archivo} if archivo else {})

    def test_acepta_png_y_jpg_y_guarda_fracciones_de_la_pagina(self):
        for nombre in ("firma.png", "firma.jpg"):
            with self.subTest(nombre=nombre):
                formulario = self.formulario(imagen(300, 100, nombre))
                self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.geometria(), GEOMETRIA)

    def test_sin_imagen_pide_subirla(self):
        formulario = self.formulario()
        self.assertFalse(formulario.is_valid())
        self.assertIn("Subí la imagen de la firma.", formulario.errors["imagen"])

    def test_rechaza_lo_que_no_es_jpg_o_png(self):
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (300, 100), "white").save(buffer, format="GIF")
        formulario = self.formulario(SimpleUploadedFile("firma.gif", buffer.getvalue()))
        self.assertFalse(formulario.is_valid())
        self.assertIn("JPG o PNG", formulario.errors["imagen"][0])

    def test_rechaza_un_archivo_que_no_es_una_imagen(self):
        formulario = self.formulario(SimpleUploadedFile("firma.png", b"no soy una imagen"))
        self.assertFalse(formulario.is_valid())
        self.assertIn("No pudimos leer la imagen", formulario.errors["imagen"][0])

    def test_rechaza_una_imagen_de_baja_resolucion_y_dice_cuanto_mide(self):
        formulario = self.formulario(imagen(100, 30, "firma.png"))
        self.assertFalse(formulario.is_valid())
        self.assertIn("100 × 30", formulario.errors["imagen"][0])
        self.assertIn("200 × 60", formulario.errors["imagen"][0])

    def test_un_recuadro_no_puede_salirse_de_la_pagina(self):
        formulario = self.formulario(imagen(300, 100), empresa_x=80, empresa_ancho=30)
        self.assertFalse(formulario.is_valid())
        self.assertIn("Firma de la empresa: el recuadro se sale de la página.", formulario.non_field_errors())

    def test_un_recuadro_no_puede_tener_tamano_cero(self):
        formulario = self.formulario(imagen(300, 100), conforme_alto=0)
        self.assertFalse(formulario.is_valid())
        self.assertTrue(formulario.non_field_errors())

    def test_los_valores_tienen_que_estar_entre_0_y_100(self):
        formulario = self.formulario(imagen(300, 100), conforme_x=120)
        self.assertFalse(formulario.is_valid())
        self.assertIn("conforme_x", formulario.errors)
