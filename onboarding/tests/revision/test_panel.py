"""Validar y devolver desde la ficha, el listado y el reporte."""

from django.contrib.auth.models import User
from django.urls import reverse

from automatizacion.actores import Actor
from clients.models import Implementacion, RondaRevision
from onboarding import acciones
from onboarding.tests.base import EnviadaBase

ANA = Actor.implementador("ana")


class PanelTests(EnviadaBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_la_ficha_ofrece_validar_y_devolver(self):
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Validar documentación y dejar lista para configurar")
        self.assertContains(pagina, "Devolver al cliente")
        self.assertContains(pagina, 'name="obs_nomina"')

    def test_validar_desde_la_ficha(self):
        self.assertEqual(self.client.post(self.url, {"accion": "aprobar_para_configurar"}).status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_VALIDADA)
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Validada - Pendiente de configurar")
        self.assertNotContains(pagina, "Validar documentación y dejar lista")

    def test_devolver_desde_la_ficha_con_observaciones(self):
        self.client.post(self.url, {
            "accion": "devolver_al_cliente", "motivo": "Revisá la nómina.", "obs_nomina": "Faltan 3 personas.", "obs_roles": "",
        })
        ronda = RondaRevision.objects.get()
        self.assertEqual((ronda.motivo, ronda.observaciones, ronda.devuelta_por), ("Revisá la nómina.", {"nomina": "Faltan 3 personas."}, "ana"))
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Devuelta, ronda 1")
        self.assertContains(pagina, "Esperando al cliente")

    def test_devolver_sin_motivo_avisa_y_no_hace_nada(self):
        respuesta = self.client.post(self.url, {"accion": "devolver_al_cliente", "motivo": ""}, follow=True)
        self.assertContains(respuesta, "Contale al cliente qué tiene que corregir")
        self.assertEqual(RondaRevision.objects.count(), 0)

    def test_el_listado_filtra_por_validada_y_muestra_la_marca(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        home = reverse("dashboard:home")
        self.assertContains(self.client.get(home, {"estado": "validada"}), "Empresa A</a></td>")
        self.assertContains(self.client.get(home, {"estado": "completado_cliente"}), "No hay implementaciones que coincidan")
        acciones.devolver_al_cliente(ANA, self.implementacion, "Ajustar")
        self.assertContains(self.client.get(home), "Devuelta, ronda 1")

    def test_el_reporte_incluye_validacion_y_rondas(self):
        import openpyxl

        from dashboard.reportes import generar_reporte_implementaciones_xlsx

        acciones.devolver_al_cliente(ANA, self.implementacion, "Ajustar")
        hoja = openpyxl.load_workbook(generar_reporte_implementaciones_xlsx()).active
        fila = {hoja.cell(1, c).value: hoja.cell(2, c).value for c in range(1, hoja.max_column + 1)}
        self.assertEqual(fila["Estado"], "Devuelta, ronda 1")
        self.assertEqual(fila["Rondas de devolución"], 1)
