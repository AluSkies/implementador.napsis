import io
import tempfile
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import TipoLiquidacion
from clients.models import (
    Cliente, Implementacion, ImplementacionLiquidacion, ImplementacionModulo, Modulo, PersonaRol, UbicacionFirma,
)
from employees.models import Empleado

CUIT = "30-50001091-2"


def _url(implementacion, paso):
    return reverse("onboarding:wizard_step", kwargs={"token": implementacion.token, "step": paso})


class BaseWizard(TestCase):
    """Un cliente con su implementación y los módulos que pida cada test."""

    modulos = ["Recibo Digital"]

    def setUp(self):
        self.usuario = User.objects.create_user(username="cliente_a", password="x")
        self.cliente = Cliente.objects.create(nombre="Empresa A", usuario=self.usuario)
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)
        for nombre in self.modulos:
            modulo, _ = Modulo.objects.get_or_create(nombre=nombre)
            ImplementacionModulo.objects.create(implementacion=self.implementacion, modulo=modulo, activo=True)
        self.liquidacion = TipoLiquidacion.objects.create(nombre="Liquidación Normal")
        self.client.force_login(self.usuario)

    CUIL_APODERADO = "20111111112"
    CUIL_LIQUIDADOR = "20222222223"

    def agregar_empleado(self, cuil=CUIL_APODERADO, nombre="JUAN", apellido="PEREZ"):
        empleado, _ = Empleado.objects.get_or_create(
            implementacion=self.implementacion, cuil=cuil,
            defaults={"nombre": nombre, "apellido": apellido, "fecha_ingreso": date(2020, 1, 1)},  # obligatoria con Recibo Digital
        )
        return empleado

    def cargar_roles_completos(self):
        """Los tres roles. El Apoderado y el Liquidador salen de la nómina, así que se cargan sus empleados."""
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        for rol, nombre, cuil in (
            (PersonaRol.ROL_APODERADO, "Gomez, Ana", self.CUIL_APODERADO),
            (PersonaRol.ROL_LIQUIDADOR, "Ruiz, Luis", self.CUIL_LIQUIDADOR),
            (PersonaRol.ROL_ADMIN_RRHH, "Sosa, Eva", ""),
        ):
            PersonaRol.objects.create(implementacion=self.implementacion, rol=rol, apellido_nombre=nombre, cuil=cuil)

    def completar_todo(self):
        self.cliente.razon_social = "Empresa A S.A."
        self.cliente.cuits = CUIT
        self.cliente.save()
        self.cargar_roles_completos()
        ImplementacionLiquidacion.objects.update_or_create(
            implementacion=self.implementacion, tipo_liquidacion=self.liquidacion, defaults={"activo": True},
        )
        self.implementacion.modelo_recibo.save("m.pdf", SimpleUploadedFile("m.pdf", b"%PDF-1.4"))
        self.agregar_empleado()
        self.cargar_firma()

    def cargar_firma(self, estado=UbicacionFirma.ESTADO_VALIDADA):
        """La firma ya subida y ubicada (por defecto, también validada por el equipo)."""
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (300, 100), "white").save(buffer, format="PNG")
        firma = UbicacionFirma(implementacion=self.implementacion, estado=estado, propuesta_por="cliente_a")
        firma.imagen.save("firma.png", ContentFile(buffer.getvalue()), save=False)
        firma.save()
        return firma


class AccesoAlWizardTests(BaseWizard):
    """Un cliente solo puede ver y completar SUS implementaciones: es la regla de
    seguridad central del wizard (no hay contraseñas por link, el link es el token)."""

    def test_anonimo_va_al_login_y_vuelve_al_paso(self):
        self.client.logout()
        respuesta = self.client.get(_url(self.implementacion, 1))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)
        self.assertIn(self.implementacion.token, respuesta.url)

    def test_otro_cliente_recibe_403(self):
        ajeno = User.objects.create_user(username="cliente_b", password="x")
        Cliente.objects.create(nombre="Empresa B", usuario=ajeno)
        self.client.force_login(ajeno)
        self.assertEqual(self.client.get(_url(self.implementacion, 1)).status_code, 403)

    def test_una_cuenta_sin_empresa_recibe_403(self):
        sin_empresa = User.objects.create_user(username="suelto", password="x")
        self.client.force_login(sin_empresa)
        self.assertEqual(self.client.get(_url(self.implementacion, 1)).status_code, 403)

    def test_el_dueno_entra(self):
        self.assertEqual(self.client.get(_url(self.implementacion, 1)).status_code, 200)

    def test_una_implementacion_cancelada_no_se_puede_completar(self):
        self.implementacion.anular()
        respuesta = self.client.get(_url(self.implementacion, 1))
        self.assertTemplateUsed(respuesta, "onboarding/cancelada.html")

    def test_un_paso_que_no_corresponde_a_los_modulos_redirige(self):
        """Sucursales (paso 3) solo existe con el módulo Fichada."""
        respuesta = self.client.get(_url(self.implementacion, 3))
        self.assertEqual(respuesta.status_code, 302)
        self.assertNotIn("/paso/3/", respuesta.url)


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


class PasoRolesTests(BaseWizard):
    """Apoderado/Firmante, Liquidador y Admin. de RRHH son elementales: sin los tres no se avanza."""

    def setUp(self):
        super().setUp()
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")

    def _post(self, filas):
        """Cada fila es (rol, nombre); el CUIL de cada rol sale de la nómina (el de Admin. de RRHH es opcional)."""
        cuils = {PersonaRol.ROL_APODERADO: self.CUIL_APODERADO, PersonaRol.ROL_LIQUIDADOR: self.CUIL_LIQUIDADOR}
        datos = {"form-TOTAL_FORMS": str(len(filas)), "form-INITIAL_FORMS": "0"}
        for i, (rol, nombre) in enumerate(filas):
            datos.update({
                f"form-{i}-rol": rol, f"form-{i}-apellido_nombre": nombre,
                f"form-{i}-cuil": cuils.get(rol, ""), f"form-{i}-mail": "",
            })
        return self.client.post(_url(self.implementacion, 5), datos)

    def test_sin_los_tres_roles_no_avanza_y_no_guarda(self):
        respuesta = self._post([(PersonaRol.ROL_APODERADO, "Gomez, Ana"), (PersonaRol.ROL_LIQUIDADOR, "Ruiz, Luis")])
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Admin. de RRHH")
        self.assertFalse(self.implementacion.roles.exists())

    def test_con_los_tres_roles_guarda_y_avanza(self):
        respuesta = self._post([
            (PersonaRol.ROL_APODERADO, "Gomez, Ana"), (PersonaRol.ROL_LIQUIDADOR, "Ruiz, Luis"),
            (PersonaRol.ROL_ADMIN_RRHH, "Sosa, Eva"),
        ])
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.implementacion.roles.count(), 3)

    def test_un_rol_con_la_fila_vacia_no_cuenta(self):
        respuesta = self._post([
            (PersonaRol.ROL_APODERADO, "Gomez, Ana"), (PersonaRol.ROL_LIQUIDADOR, "Ruiz, Luis"),
            (PersonaRol.ROL_ADMIN_RRHH, ""),
        ])
        self.assertEqual(respuesta.status_code, 200)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PasoConfiguracionModeloDeReciboTests(BaseWizard):
    def _post(self, archivo=None):
        datos = {"tipo_firma": "digital", "segmentacion_liquidador": "AREA UNICA", "tipos_liquidacion": [self.liquidacion.pk]}
        if archivo:
            datos["modelo_recibo"] = archivo
        return self.client.post(_url(self.implementacion, 6), datos)

    def test_el_modelo_de_recibo_es_obligatorio(self):
        respuesta = self._post()
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].errors["modelo_recibo"])

    def test_tiene_que_ser_un_pdf(self):
        respuesta = self._post(SimpleUploadedFile("recibo.docx", b"x"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].errors["modelo_recibo"])

    def test_con_un_pdf_guarda_y_avanza(self):
        respuesta = self._post(SimpleUploadedFile("recibo.pdf", b"%PDF-1.4"))
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertTrue(self.implementacion.modelo_recibo)

    def test_si_ya_hay_modelo_no_hace_falta_subirlo_de_nuevo(self):
        self.implementacion.modelo_recibo.save("viejo.pdf", SimpleUploadedFile("viejo.pdf", b"%PDF-1.4"))
        respuesta = self._post()
        self.assertEqual(respuesta.status_code, 302)


class PasoNominaTests(BaseWizard):
    def test_no_se_puede_continuar_sin_empleados(self):
        respuesta = self.client.post(_url(self.implementacion, 4), {"accion": "continuar"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "al menos un empleado")

    def test_con_un_empleado_continua(self):
        self.agregar_empleado()
        respuesta = self.client.post(_url(self.implementacion, 4), {"accion": "continuar"})
        self.assertEqual(respuesta.status_code, 302)


class Paso9EnvioTests(BaseWizard):
    def _enviar(self):
        return self.client.post(_url(self.implementacion, 10), {"accion": "enviar"})

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_con_pendientes_no_se_envia_y_se_los_muestra(self):
        respuesta = self._enviar()
        self.assertEqual(respuesta.status_code, 200)
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)
        self.assertContains(respuesta, "razón social y el CUIT")
        self.assertContains(respuesta, "nómina")

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_saltar_de_paso_por_la_url_no_evita_las_validaciones(self):
        """Los pasos no son secuenciales: ir directo al 9 no debe permitir enviar a medias."""
        self.agregar_empleado()
        self.assertIsNone(self.implementacion.enviado)
        self._enviar()
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_completo_se_envia_pero_no_queda_cumplida(self):
        self.completar_todo()
        respuesta = self._enviar()
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)
        # Que el cliente envíe no significa que Napsis ya implementó: sigue pendiente.
        self.assertEqual(self.implementacion.estado, Implementacion.ESTADO_PENDIENTE)
        self.assertEqual(self.implementacion.estado_visual, Implementacion.VISUAL_COMPLETADO_CLIENTE)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_si_falla_el_mail_el_cliente_igual_queda_enviado(self):
        self.completar_todo()
        with patch("onboarding.acciones.notificaciones.notificar_implementacion_completa", side_effect=OSError("SMTP caído")):
            with self.assertLogs("onboarding.acciones", level="ERROR"):
                respuesta = self._enviar()
        self.assertEqual(respuesta.status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertIsNotNone(self.implementacion.enviado)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Paso9FechaDeImplementacionTests(BaseWizard):
    """El cliente puede pedir fecha de implementación (opcional), pero no antes del mínimo de
    días hábiles. El equipo puede poner cualquier fecha desde el panel."""

    def setUp(self):
        super().setUp()
        self.completar_todo()
        from onboarding import services

        self.minima = services.fecha_minima_para_cliente()

    def _enviar_con_fecha(self, fecha):
        return self.client.post(
            _url(self.implementacion, 10), {"accion": "enviar", "fecha_salida_productivo": fecha.isoformat() if fecha else ""},
        )

    def test_es_opcional(self):
        self.assertEqual(self._enviar_con_fecha(None).status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.fecha_salida_productivo)
        self.assertIsNotNone(self.implementacion.enviado)

    def test_antes_del_minimo_se_rechaza_y_no_se_envia(self):
        from datetime import timedelta

        respuesta = self._enviar_con_fecha(self.minima - timedelta(days=1))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, f"{self.minima:%d/%m/%Y}")
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.enviado)
        self.assertIsNone(self.implementacion.fecha_salida_productivo)

    def test_pedir_manana_o_hoy_tambien_se_rechaza(self):
        from datetime import timedelta
        from django.utils import timezone

        for dias in (0, 1):
            with self.subTest(dias=dias):
                respuesta = self._enviar_con_fecha(timezone.localdate() + timedelta(days=dias))
                self.assertEqual(respuesta.status_code, 200)

    def test_desde_el_minimo_se_acepta_y_queda_en_el_historial(self):
        self._enviar_con_fecha(self.minima)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.fecha_salida_productivo, self.minima)
        self.assertIsNotNone(self.implementacion.enviado)
        version = self.implementacion.versiones.get(seccion="fecha_implementacion")
        self.assertEqual(version.editado_por, "Cliente")

    def test_la_fecha_que_puso_el_equipo_se_acepta_aunque_sea_anterior_al_minimo(self):
        from datetime import timedelta

        fecha_del_equipo = self.minima - timedelta(days=5)
        self.implementacion.fecha_salida_productivo = fecha_del_equipo
        self.implementacion.save()
        self.assertEqual(self._enviar_con_fecha(fecha_del_equipo).status_code, 302)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.fecha_salida_productivo, fecha_del_equipo)

    def test_viene_precargada_con_la_fecha_ya_definida(self):
        self.implementacion.fecha_salida_productivo = self.minima
        self.implementacion.save()
        self.assertContains(self.client.get(_url(self.implementacion, 10)), self.minima.isoformat())

    def test_el_campo_avisa_cual_es_la_fecha_minima(self):
        self.assertContains(self.client.get(_url(self.implementacion, 10)), f'min="{self.minima.isoformat()}"')
