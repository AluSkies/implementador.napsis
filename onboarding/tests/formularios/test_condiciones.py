"""Formulario de condiciones del proceso."""

from django.test import TestCase

from clients.models import Cliente, Implementacion
from onboarding.forms import CondicionesForm


def _form(**datos):
    return CondicionesForm(datos)


class CondicionesFormTests(TestCase):
    """Cada condición se bloquea al completarla; vacía, la decide el cliente."""

    def setUp(self):
        self.implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa"))

    def _aplicar(self, **datos):
        form = _form(**datos)
        self.assertTrue(form.is_valid(), form.errors)
        form.aplicar(self.implementacion)
        return self.implementacion

    def test_vacio_deja_todo_en_manos_del_cliente(self):
        impl = self._aplicar()
        self.assertEqual(impl.max_roles, 6)
        self.assertTrue(impl.tipo_firma_editable and impl.nomenclatura_editable and impl.segmentacion_editable)

    def test_elegir_la_firma_la_bloquea_con_ese_valor(self):
        impl = self._aplicar(tipo_firma="electronica")
        self.assertFalse(impl.tipo_firma_editable)
        self.assertEqual(impl.tipo_firma, "electronica")

    def test_completar_la_nomenclatura_la_bloquea(self):
        impl = self._aplicar(nomenclatura_pdf="  recibo_{legajo}.pdf ")
        self.assertFalse(impl.nomenclatura_editable)
        self.assertEqual(impl.nomenclatura_pdf, "recibo_{legajo}.pdf")

    def test_area_unica_bloquea_la_segmentacion_en_area_unica(self):
        self.implementacion.segmentacion_liquidador = "POR SUCURSAL"
        impl = self._aplicar(area_unica="on")
        self.assertFalse(impl.segmentacion_editable)
        self.assertEqual(impl.segmentacion_liquidador, "AREA UNICA")

    def test_maximo_de_roles(self):
        self.assertEqual(self._aplicar(max_roles="4").max_roles, 4)

    def test_el_maximo_de_roles_tiene_que_alcanzar_para_los_tres_obligatorios(self):
        for invalido in ("2", "0", "7", "abc"):
            with self.subTest(max_roles=invalido):
                self.assertFalse(_form(max_roles=invalido).is_valid())
        for valido in ("3", "6"):
            with self.subTest(max_roles=valido):
                self.assertTrue(_form(max_roles=valido).is_valid())

    def test_al_editar_muestra_lo_bloqueado_y_deja_vacio_lo_libre(self):
        self._aplicar(tipo_firma="digital", area_unica="on")
        self.implementacion.save()
        inicial = CondicionesForm(implementacion=self.implementacion).initial
        self.assertEqual(inicial["tipo_firma"], "digital")
        self.assertTrue(inicial["area_unica"])
        self.assertEqual(inicial["nomenclatura_pdf"], "")  # esa quedó libre

    def test_desbloquear_devuelve_la_decision_al_cliente(self):
        self._aplicar(tipo_firma="digital")
        self._aplicar(tipo_firma="")
        self.assertTrue(self.implementacion.tipo_firma_editable)
