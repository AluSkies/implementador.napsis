"""La pantalla de inicio del cliente: «Mis implementaciones»."""

from django.urls import reverse

from onboarding.tests.base import BaseWizard


class MisImplementacionesTests(BaseWizard):
    def pagina(self):
        return self.client.get(reverse("onboarding:mis_implementaciones"))

    def test_tiene_un_epigrafe_que_explica_como_entrar_a_una_implementacion(self):
        pagina = self.pagina()
        self.assertContains(pagina, "Acá podés ver tus implementaciones con Napsis.")
        self.assertContains(pagina, "«Ver más»")
        self.assertContains(pagina, 'class="epigrafe"')

    def test_el_link_de_cada_implementacion_dice_ver_mas_y_lleva_a_ella(self):
        self.assertContains(self.pagina(), f'<a href="{self.implementacion.get_absolute_url()}">Ver más</a>', html=True)
