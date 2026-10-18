import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from clients.models import Cliente, Implementacion
from onboarding.forms import CondicionesForm

from . import test_wizard


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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ConfiguracionRespetaLosBloqueosTests(test_wizard.BaseWizard):
    """Lo que el implementador dejó fijo no se puede cambiar desde el wizard, ni siquiera
    editando el formulario a mano."""

    def _post(self, **extra):
        datos = {
            "tipo_firma": "electronica", "nomenclatura_pdf": "mi_formato.pdf",
            "segmentacion_liquidador": "POR SUCURSAL",
            "modelo_recibo": SimpleUploadedFile("m.pdf", b"%PDF-1.4"),
            **extra,
        }
        return self.client.post(reverse("onboarding:wizard_step", kwargs={"token": self.implementacion.token, "step": 6}), datos)

    def bloquear(self):
        self.implementacion.tipo_firma, self.implementacion.tipo_firma_editable = "digital", False
        self.implementacion.nomenclatura_pdf, self.implementacion.nomenclatura_editable = "recibo_{legajo}.pdf", False
        self.implementacion.segmentacion_liquidador, self.implementacion.segmentacion_editable = "AREA UNICA", False
        self.implementacion.save()

    def test_sin_bloqueos_el_cliente_decide_todo(self):
        self.assertEqual(self._post().status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.tipo_firma, "electronica")
        self.assertEqual(self.implementacion.nomenclatura_pdf, "mi_formato.pdf")
        self.assertEqual(self.implementacion.segmentacion_liquidador, "POR SUCURSAL")

    def test_lo_bloqueado_ignora_lo_que_mande_el_cliente(self):
        self.bloquear()
        self.assertEqual(self._post().status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.tipo_firma, "digital")
        self.assertEqual(self.implementacion.nomenclatura_pdf, "recibo_{legajo}.pdf")
        self.assertEqual(self.implementacion.segmentacion_liquidador, "AREA UNICA")

    def test_lo_bloqueado_se_muestra_deshabilitado_con_el_valor_fijo(self):
        self.bloquear()
        respuesta = self.client.get(reverse("onboarding:wizard_step", kwargs={"token": self.implementacion.token, "step": 6}))
        formulario = respuesta.context["form"]
        for campo in ("tipo_firma", "nomenclatura_pdf", "segmentacion_liquidador"):
            self.assertTrue(formulario.fields[campo].disabled, campo)
        self.assertContains(respuesta, "recibo_{legajo}.pdf")
        self.assertContains(respuesta, "Lo definió Napsis")

    def test_bloquear_solo_una_no_afecta_a_las_demas(self):
        self.implementacion.tipo_firma, self.implementacion.tipo_firma_editable = "digital", False
        self.implementacion.save()
        self._post()
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.tipo_firma, "digital")
        self.assertEqual(self.implementacion.nomenclatura_pdf, "mi_formato.pdf")


class RolesMaximoDePersonasTests(test_wizard.BaseWizard):
    def _url(self):
        return reverse("onboarding:wizard_step", kwargs={"token": self.implementacion.token, "step": 5})

    def _post(self, cantidad):
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        roles = ["apoderado", "liquidador", "admin_rrhh"] + ["apoderado"] * 3
        cuils = {"apoderado": self.CUIL_APODERADO, "liquidador": self.CUIL_LIQUIDADOR, "admin_rrhh": ""}
        datos = {"form-TOTAL_FORMS": str(cantidad), "form-INITIAL_FORMS": "0"}
        for i in range(cantidad):
            datos.update({
                f"form-{i}-rol": roles[i], f"form-{i}-apellido_nombre": f"Persona {i}, Nombre",
                f"form-{i}-cuil": cuils[roles[i]], f"form-{i}-mail": "",
            })
        return self.client.post(self._url(), datos)

    def test_por_defecto_muestra_seis_filas(self):
        self.assertEqual(self.client.get(self._url()).context["formset"].total_form_count(), 6)

    def test_muestra_tantas_filas_como_el_maximo_de_la_implementacion(self):
        for maximo in (3, 4, 5):
            with self.subTest(maximo=maximo):
                self.implementacion.max_roles = maximo
                self.implementacion.save()
                respuesta = self.client.get(self._url())
                self.assertEqual(respuesta.context["formset"].total_form_count(), maximo)
                self.assertContains(respuesta, f"hasta {maximo} personas")

    def test_no_acepta_mas_personas_que_el_maximo(self):
        self.implementacion.max_roles = 4
        self.implementacion.save()
        respuesta = self._post(5)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(self.implementacion.roles.exists())

    def test_con_el_maximo_justo_guarda_y_avanza(self):
        self.implementacion.max_roles = 3
        self.implementacion.save()
        self.assertEqual(self._post(3).status_code, 302)
        self.assertEqual(self.implementacion.roles.count(), 3)
