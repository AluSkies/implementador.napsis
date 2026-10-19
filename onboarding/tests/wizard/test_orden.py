"""Orden y pasos del wizard."""

from onboarding import services
from onboarding.tests.base import BaseWizard, _url


class OrdenDelWizardTests(BaseWizard):
    """Nómina antes que roles (para elegir de ahí a las personas) y sucursales antes que la
    nómina (para asignar a cada empleado la suya)."""

    modulos = ["Recibo Digital", "Fichada", "Novedades", "Legajos"]

    def test_el_orden_de_los_pasos(self):
        self.assertEqual(
            (services.PASO_DATOS, services.PASO_MODULOS, services.PASO_SUCURSALES, services.PASO_NOMINA,
             services.PASO_ROLES, services.PASO_CONFIGURACION, services.PASO_FIRMA, services.PASO_LICENCIAS,
             services.PASO_DOCUMENTOS, services.PASO_REVISION),
            tuple(range(1, 11)),
        )
        self.assertEqual(services.pasos_activos(self.implementacion), list(range(1, 11)))

    def test_la_nomina_viene_antes_que_los_roles_y_las_sucursales_antes_que_la_nomina(self):
        self.assertLess(services.PASO_NOMINA, services.PASO_ROLES)
        self.assertLess(services.PASO_SUCURSALES, services.PASO_NOMINA)

    def test_cada_paso_muestra_su_titulo(self):
        titulos = {4: "Carga de empleados", 5: "Apoderado/s, Liquidador y Admin. de RRHH", 3: "Sucursales"}
        for paso, titulo in titulos.items():
            with self.subTest(paso=paso):
                self.assertContains(self.client.get(_url(self.implementacion, paso)), titulo)

    def test_al_guardar_las_sucursales_se_sigue_con_la_nomina(self):
        datos = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "0", "form-MIN_NUM_FORMS": "0",
                 "form-MAX_NUM_FORMS": "1000", "form-0-nombre": "Central", "form-0-calle": "Mitre"}
        respuesta = self.client.post(_url(self.implementacion, 3), datos)
        self.assertRedirects(respuesta, _url(self.implementacion, 4), fetch_redirect_response=False)

    def test_al_continuar_la_nomina_se_sigue_con_los_roles(self):
        self.agregar_empleado()
        respuesta = self.client.post(_url(self.implementacion, 4), {"accion": "continuar"})
        self.assertRedirects(respuesta, _url(self.implementacion, 5), fetch_redirect_response=False)

    def test_los_pendientes_de_envio_apuntan_al_paso_correcto(self):
        pendientes = [(p["paso"], p["mensaje"]) for p in services.pendientes_de_envio(self.implementacion)]
        for paso, texto in ((4, "Cargar la nómina"), (5, "rol"), (6, "modelo de recibo"), (6, "tipo de liquidación")):
            with self.subTest(texto=texto):
                self.assertTrue(any(p == paso and texto in m for p, m in pendientes), pendientes)
