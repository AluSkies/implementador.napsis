"""Paso 1: datos de la empresa."""

from onboarding.tests.base import CUIT, BaseWizard, _url


class Paso1EmpresaTests(BaseWizard):
    DATOS = {"razon_social": "Empresa A S.A.", "cuits": "30500010912", "telefono": "011-1", "mail_contacto": "a@a.com"}

    def test_exige_razon_social_y_cuit(self):
        respuesta = self.client.post(_url(self.implementacion, 1), {"telefono": "011-1"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFormError(respuesta.context["form"], "razon_social", "Este campo es obligatorio.")
        self.assertFormError(respuesta.context["form"], "cuits", "Este campo es obligatorio.")

    def test_rechaza_un_cuit_mal_tipeado(self):
        respuesta = self.client.post(_url(self.implementacion, 1), {**self.DATOS, "cuits": "30-50001091-3"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].errors["cuits"])
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.cuits, "")

    def test_guarda_en_el_cliente_con_el_cuit_normalizado_y_avanza(self):
        respuesta = self.client.post(_url(self.implementacion, 1), self.DATOS)
        self.assertEqual(respuesta.status_code, 302)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.razon_social, "Empresa A S.A.")
        self.assertEqual(self.cliente.cuits, CUIT)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.telefono, "011-1")

    def test_si_el_implementador_ya_los_cargo_vienen_precargados(self):
        self.cliente.razon_social = "Ya Cargada S.A."
        self.cliente.cuits = CUIT
        self.cliente.save()
        respuesta = self.client.get(_url(self.implementacion, 1))
        self.assertContains(respuesta, "Ya Cargada S.A.")
        self.assertContains(respuesta, CUIT)
