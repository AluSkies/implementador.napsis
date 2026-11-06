"""La hoja compartida del portal (`static/portal.css`): las variables de marca viven en un solo lugar y las hojas de cada
pantalla las usan, para que el panel y el formulario del cliente no se separen de nuevo."""

import re

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

# Los colores de marca que no se repiten escritos a mano en las hojas de cada pantalla.
COLORES_DE_MARCA = ["#aa00ff", "#1c1699", "#0e0c5c", "#0a1543", "#6b6f8c", "#f2f2f5", "#dcdce6", "#ece9f6", "#faf9fd", "#f6ecff"]
HOJAS_DE_PANTALLA = ["wizard.css", "panel_filtros.css"]


def leer(nombre):
    with open(finders.find(nombre), encoding="utf-8") as hoja:
        return hoja.read()


class HojaCompartidaTests(SimpleTestCase):
    def test_define_las_variables_de_marca_formas_y_tipografias(self):
        portal = leer("portal.css")
        for variable in ("--primary", "--primary-dark", "--navy", "--surface-soft", "--tint", "--border-soft", "--on-dark",
                         "--radius", "--radius-lg", "--font-body"):
            self.assertRegex(portal, rf"{re.escape(variable)}:\s*[^;]+;", variable)

    def test_los_colores_de_marca_estan_escritos_una_sola_vez_en_el_bloque_de_variables(self):
        portal = leer("portal.css")
        bloque, resto = portal.split("/* ================= estilos base", 1)
        for color in COLORES_DE_MARCA:
            self.assertEqual(bloque.lower().count(color), 1, color)
            self.assertNotIn(color, resto.lower(), f"{color} escrito a mano en los estilos base")

    def test_las_hojas_de_cada_pantalla_usan_las_variables_y_no_repiten_los_colores_de_marca(self):
        for nombre in HOJAS_DE_PANTALLA:
            hoja = leer(nombre).lower()
            self.assertIn("var(--", hoja, nombre)
            for color in COLORES_DE_MARCA:
                self.assertNotIn(color, hoja, f"{nombre} repite {color}")

    def test_los_avisos_son_un_componente_de_la_hoja_compartida(self):
        portal = leer("portal.css")
        for regla in (".aviso {", ".aviso.warning {", ".aviso.info {"):
            self.assertIn(regla, portal, regla)
        self.assertRegex(portal, r"\.actions \{[^}]*flex-wrap: wrap")  # los botones bajan de renglón en vez de apretarse

    def test_la_barra_superior_es_azul_con_el_logo_en_blanco(self):
        portal = leer("portal.css")
        barra = re.search(r"header\.topbar \{(.*?)\}", portal, re.S).group(1)
        self.assertIn("background: var(--primary-dark)", barra)
        self.assertIn("filter: brightness(0) invert(1)", portal)
