"""Medidas aceptadas del logo y del banner."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from clients.validators import validar_medidas_banner, validar_medidas_logo
from onboarding.tests.base import imagen


class MedidasDelLogoTests(SimpleTestCase):
    def test_acepta_hasta_200_por_200(self):
        for medidas in ((200, 200), (100, 50), (1, 1)):
            with self.subTest(medidas=medidas):
                validar_medidas_logo(imagen(*medidas))

    def test_rechaza_lo_que_se_pasa_y_dice_cuanto_mide(self):
        for medidas in ((201, 200), (200, 201), (500, 500)):
            with self.subTest(medidas=medidas):
                with self.assertRaises(ValidationError) as error:
                    validar_medidas_logo(imagen(*medidas))
                texto = error.exception.messages[0]
                self.assertIn("200 × 200", texto)
                self.assertIn(f"{medidas[0]} × {medidas[1]}", texto)

    def test_deja_el_archivo_listo_para_guardarse(self):
        archivo = imagen(100, 100)
        validar_medidas_logo(archivo)
        self.assertEqual(archivo.tell(), 0)


class MedidasDelBannerTests(SimpleTestCase):
    def test_acepta_el_rango(self):
        for medidas in ((1500, 200), (1600, 400), (1550, 300)):
            with self.subTest(medidas=medidas):
                validar_medidas_banner(imagen(*medidas))

    def test_rechaza_fuera_de_rango_en_cualquier_lado(self):
        for medidas in ((1499, 300), (1601, 300), (1550, 199), (1550, 401), (200, 200), (3000, 800)):
            with self.subTest(medidas=medidas):
                with self.assertRaises(ValidationError) as error:
                    validar_medidas_banner(imagen(*medidas))
                texto = error.exception.messages[0]
                self.assertIn("entre 1500 × 200 y 1600 × 400", texto)
                self.assertIn(f"{medidas[0]} × {medidas[1]}", texto)
