"""Vacaciones como licencia automática."""

from catalog.models import TipoLicencia
from onboarding.forms import LicenciasNovedadesForm
from onboarding.tests.base import BaseWizard, _url


class VacacionesAutomaticasTests(BaseWizard):
    modulos = ["Novedades"]

    def setUp(self):
        super().setUp()
        self.vacaciones = TipoLicencia.objects.create(nombre="Vacaciones", automatica=True)
        self.otra = TipoLicencia.objects.create(nombre="Licencia por Mudanza")

    def formulario(self, datos=None):
        return LicenciasNovedadesForm(
            datos, licencias_qs=TipoLicencia.objects.all(), novedades_qs=[], estado_por_licencia={}, estado_por_novedad={},
        )

    def test_se_muestra_tildada_y_no_se_puede_cambiar(self):
        campo = self.formulario().fields[f"licencia_{self.vacaciones.id}_activo"]
        self.assertTrue(campo.disabled)
        self.assertTrue(campo.initial)

    def test_aunque_el_formulario_no_la_mande_queda_activa(self):
        formulario = self.formulario({f"licencia_{self.otra.id}_activo": "on"})
        self.assertTrue(formulario.is_valid())
        self.assertTrue(formulario.cleaned_data[f"licencia_{self.vacaciones.id}_activo"])

    def test_las_demas_siguen_siendo_opcionales(self):
        campo = self.formulario().fields[f"licencia_{self.otra.id}_activo"]
        self.assertFalse(campo.disabled)
        self.assertFalse(campo.initial)

    def test_el_paso_explica_que_se_crea_sola(self):
        self.assertContains(self.client.get(_url(self.implementacion, 8)), "Napsis la crea sola")

    def test_guardar_el_paso_la_deja_activa(self):
        self.client.post(_url(self.implementacion, 8), {f"licencia_{self.otra.id}_activo": "on"})
        self.assertTrue(self.implementacion.licencias.get(tipo_licencia=self.vacaciones).activo)
