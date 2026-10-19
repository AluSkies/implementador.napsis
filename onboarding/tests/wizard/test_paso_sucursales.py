"""Paso de sucursales: el epígrafe, la tarjeta única y el botón para agregar todas las que hagan falta."""

import tempfile

from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse

from clients.models import Sucursal
from onboarding.services import PASO_SUCURSALES
from onboarding.tests.base import BaseWizard, _url


def datos_de_sucursales(*sucursales, existentes=0):
    """El POST del formset: una fila por sucursal ({campo: valor})."""
    datos = {
        "form-TOTAL_FORMS": str(len(sucursales)), "form-INITIAL_FORMS": str(existentes),
        "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
    }
    for i, sucursal in enumerate(sucursales):
        for campo, valor in sucursal.items():
            datos[f"form-{i}-{campo}"] = valor
    return datos


def tarjetas_visibles(pagina):
    """Cuántas tarjetas trae la página (sin contar la plantilla escondida del botón)."""
    return pagina.split("<template")[0].count('class="sucursal-tarjeta" data-tarjeta')


class SucursalesBase(BaseWizard):
    modulos = ["Recibo Digital", "Fichada"]

    def pagina(self):
        return self.client.get(_url(self.implementacion, PASO_SUCURSALES)).content.decode()

    def enviar(self, *sucursales, existentes=0):
        return self.client.post(_url(self.implementacion, PASO_SUCURSALES), datos_de_sucursales(*sucursales, existentes=existentes))


class EpigrafeTests(SucursalesBase):
    def test_explica_para_que_sirve_en_terminos_de_napsis_fichada(self):
        pagina = self.pagina()
        self.assertIn("¿Para qué sirve este paso?", pagina)
        self.assertIn("Napsis Fichada", pagina)
        self.assertIn("lugar de trabajo desde donde el personal registra su fichada", pagina)
        self.assertIn("La fichada se hace por ubicación", pagina)

    def test_dice_que_hay_que_cargar_una_por_lugar_fisico_y_con_direccion_completa(self):
        pagina = self.pagina()
        self.assertIn("una sucursal por cada lugar físico distinto", pagina)
        self.assertIn("dirección completa", pagina)

    def test_avisa_que_a_cada_empleado_se_le_asigna_la_suya(self):
        self.assertIn("cada persona se le asigna la sucursal", self.pagina())

    def test_aclara_que_si_se_ficha_desde_un_solo_lugar_alcanza_con_una(self):
        self.assertIn("una sola sucursal", self.pagina())


class FormularioTests(SucursalesBase):
    def test_sin_sucursales_cargadas_hay_una_sola_tarjeta(self):
        self.assertEqual(tarjetas_visibles(self.pagina()), 1)

    def test_con_sucursales_cargadas_se_ven_esas_mas_una_en_blanco(self):
        Sucursal.objects.create(implementacion=self.implementacion, nombre="Casa central", calle="Mitre")
        Sucursal.objects.create(implementacion=self.implementacion, nombre="Planta", calle="Ruta 9")
        self.assertEqual(tarjetas_visibles(self.pagina()), 3)

    def test_tiene_el_boton_verde_de_agregar_sucursal(self):
        pagina = self.pagina()
        self.assertIn("data-agregar", pagina)
        self.assertIn("btn success icono", pagina)
        self.assertIn("Agregar sucursal", pagina)

    def test_trae_la_plantilla_escondida_para_las_nuevas_con_el_numero_por_reemplazar(self):
        plantilla = self.pagina().split("<template data-vacia>")[1].split("</template>")[0]
        self.assertIn("form-__prefix__-nombre", plantilla)

    def test_la_casilla_de_eliminar_no_se_muestra_como_un_campo_mas(self):
        pagina = self.pagina().split("<template")[0]
        self.assertNotIn("Delete:", pagina)
        self.assertIn('<span hidden><input type="checkbox" name="form-0-DELETE"', pagina)

    def test_el_script_que_suma_tarjetas_se_incluye(self):
        self.assertIn("sucursales_formset.js", self.pagina())

    def test_tambien_se_usa_en_la_ficha_del_equipo(self):
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        ficha = self.client.get(reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})).content.decode()
        self.assertIn("data-sucursales", ficha)
        self.assertIn("Agregar sucursal", ficha)


class GuardadoTests(SucursalesBase):
    def test_guarda_un_numero_cualquiera_de_sucursales(self):
        nuevas = [{"nombre": f"Sucursal {i}", "calle": "Calle", "altura": str(i), "localidad": "CABA"} for i in range(1, 13)]
        respuesta = self.enviar(*nuevas)
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.implementacion.sucursales.count(), 12)

    def test_las_tarjetas_en_blanco_se_ignoran(self):
        self.enviar({"nombre": "Casa central", "calle": "Mitre"}, {}, {"nombre": "", "calle": ""})
        self.assertEqual(list(self.implementacion.sucursales.values_list("nombre", flat=True)), ["Casa central"])

    def test_quitar_una_existente_la_elimina_y_conserva_las_otras(self):
        Sucursal.objects.create(implementacion=self.implementacion, nombre="Casa central", calle="Mitre")
        Sucursal.objects.create(implementacion=self.implementacion, nombre="Planta", calle="Ruta 9")
        self.enviar({"nombre": "Casa central", "calle": "Mitre"}, {"nombre": "Planta", "calle": "Ruta 9", "DELETE": "on"}, existentes=2)
        self.assertEqual(list(self.implementacion.sucursales.values_list("nombre", flat=True)), ["Casa central"])

    def test_agregar_una_a_las_existentes_conserva_las_anteriores(self):
        Sucursal.objects.create(implementacion=self.implementacion, nombre="Casa central", calle="Mitre")
        self.enviar({"nombre": "Casa central", "calle": "Mitre"}, {"nombre": "Depósito", "calle": "Ruta 3"}, existentes=1)
        self.assertEqual(self.implementacion.sucursales.count(), 2)

    def test_una_quitada_no_reaparece_escondida_al_volver_a_mostrar_la_pagina_con_errores(self):
        respuesta = self.enviar({"nombre": "A", "calle": "x", "DELETE": "on"}, {"nombre": "B", "calle": "y", "codigo_postal": "x" * 50})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(" hidden>", respuesta.content.decode().split("<template")[0])

    def test_con_fichada_pide_al_menos_una_sucursal_con_nombre_para_poder_enviar(self):
        from onboarding.services import pendientes_de_envio

        mensajes = [p["mensaje"] for p in pendientes_de_envio(self.implementacion)]
        self.assertTrue(any("al menos una sucursal" in m for m in mensajes))
        self.enviar({"nombre": "Casa central", "calle": "Mitre"})
        mensajes = [p["mensaje"] for p in pendientes_de_envio(self.implementacion)]
        self.assertFalse(any("al menos una sucursal" in m for m in mensajes))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SinFichadaTests(BaseWizard):
    def test_sin_fichada_el_paso_no_existe(self):
        respuesta = self.client.get(_url(self.implementacion, PASO_SUCURSALES))
        self.assertEqual(respuesta.status_code, 302)
