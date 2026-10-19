"""Guardado de cada sección con su historial."""

from django.test import TestCase

from automatizacion.actores import Actor
from catalog.models import TipoDocumento, TipoLicencia, TipoNovedad
from clients.models import Cliente, Implementacion, Modulo, PersonaRol, Sucursal
from onboarding import services

TEST = Actor.implementador("Test")


class GuardarDatosContactoTests(TestCase):
    """Regresión de un bug real: ModelForm._post_clean() muta la instancia en
    memoria durante is_valid(), ANTES del .save(). Si guardar_datos_contacto no
    releyera la implementación desde la base, el snapshot capturaría el valor
    NUEVO en vez del anterior."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(
            cliente=self.cliente, telefono="011-0000-0000",
        )

    def test_snapshot_guarda_el_valor_anterior_no_el_nuevo(self):
        from onboarding.forms import EmpresaForm

        form = EmpresaForm(
            {
                "razon_social": "Empresa de Prueba S.A.", "cuits": "30-50001091-2",
                "telefono": "011-9999-9999", "mail_contacto": "nuevo@example.com",
            },
            instance=self.implementacion,
        )
        self.assertTrue(form.is_valid())
        # A esta altura form.instance (== self.implementacion) ya está mutado en memoria.
        self.assertEqual(self.implementacion.telefono, "011-9999-9999")

        services.guardar_datos_contacto(self.implementacion, form, TEST)

        version = self.implementacion.versiones.get(seccion="datos_contacto")
        self.assertEqual(version.datos["Teléfono"], "011-0000-0000")

        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.telefono, "011-9999-9999")


class GuardarModulosTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)
        self.modulo_a = Modulo.objects.create(nombre="Módulo A")
        self.modulo_b = Modulo.objects.create(nombre="Módulo B")

    def test_activa_solo_los_seleccionados(self):
        services.guardar_modulos(
            self.implementacion, Modulo.objects.all(), {self.modulo_a.id}, TEST,
        )
        activos = set(
            self.implementacion.modulos.filter(activo=True).values_list("modulo__nombre", flat=True)
        )
        self.assertEqual(activos, {"Módulo A"})

    def test_guarda_version_antes_de_aplicar_el_cambio(self):
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), {self.modulo_a.id}, TEST)
        version = self.implementacion.versiones.get(seccion="modulos")
        # Ningún módulo estaba activo todavía en el momento del snapshot.
        self.assertEqual(version.datos, {})

    def test_es_idempotente_para_el_mismo_conjunto(self):
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), {self.modulo_a.id}, TEST)
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), {self.modulo_a.id}, TEST)
        self.assertEqual(self.implementacion.modulos.filter(activo=True).count(), 1)


class GuardarRolesYSucursalesTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def test_guardar_roles_reemplaza_los_existentes(self):
        from onboarding.forms import RolFormSet

        PersonaRol.objects.create(
            implementacion=self.implementacion, rol=PersonaRol.ROL_APODERADO, apellido_nombre="Viejo, Rol",
        )
        formset = RolFormSet({
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "0",
            "form-0-rol": PersonaRol.ROL_LIQUIDADOR,
            "form-0-apellido_nombre": "Gómez, Ana",
            "form-0-cuil": "20222222223",
            "form-0-mail": "ana@example.com",
        })
        self.assertTrue(formset.is_valid())

        services.guardar_roles(self.implementacion, formset, TEST)

        roles = list(self.implementacion.roles.all())
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0].apellido_nombre, "Gómez, Ana")

    def test_guardar_sucursales_ignora_filas_vacias(self):
        from onboarding.forms import SucursalFormSet

        formset = SucursalFormSet({
            "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "0",
            "form-0-nombre": "Casa Central", "form-0-calle": "", "form-0-altura": "",
            "form-0-piso_depto": "", "form-0-codigo_postal": "", "form-0-localidad": "CABA",
            "form-0-entre_calles": "", "form-0-observaciones": "",
            "form-1-nombre": "", "form-1-calle": "", "form-1-altura": "",
            "form-1-piso_depto": "", "form-1-codigo_postal": "", "form-1-localidad": "",
            "form-1-entre_calles": "", "form-1-observaciones": "",
        })
        self.assertTrue(formset.is_valid())

        services.guardar_sucursales(self.implementacion, formset, TEST)

        self.assertEqual(Sucursal.objects.filter(implementacion=self.implementacion).count(), 1)


class GuardarLicenciasNovedadesYDocumentosTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)
        self.licencia = TipoLicencia.objects.create(nombre="Licencia de Prueba")
        self.novedad = TipoNovedad.objects.create(nombre="Ausencia")
        self.tipo_documento = TipoDocumento.objects.create(nombre="Documento de Prueba")

    def test_guardar_licencias_y_novedades_activa_lo_marcado(self):
        from onboarding.forms import LicenciasNovedadesForm

        form = LicenciasNovedadesForm(
            {f"licencia_{self.licencia.id}_activo": "on"},
            licencias_qs=TipoLicencia.objects.all(), novedades_qs=TipoNovedad.objects.all(),
        )
        self.assertTrue(form.is_valid())

        services.guardar_licencias_y_novedades(
            self.implementacion, form, TipoLicencia.objects.all(), TipoNovedad.objects.all(), TEST,
        )

        self.assertTrue(self.implementacion.licencias.get(tipo_licencia=self.licencia).activo)
        self.assertFalse(self.implementacion.novedades.get(tipo_novedad=self.novedad).activo)

    def test_guardar_documentos_crea_tipos_otros_con_sus_campos(self):
        from onboarding.forms import DocumentosLegajoForm

        form = DocumentosLegajoForm(
            {"otros_documentos": "Certificado de matrimonio: Fecha de emisión, Adjunto"},
            tipos_qs=services.tipos_documento_disponibles(self.implementacion),
        )
        self.assertTrue(form.is_valid())

        services.guardar_documentos(
            self.implementacion, form, services.tipos_documento_disponibles(self.implementacion), TEST,
        )

        nuevo = TipoDocumento.objects.get(implementacion=self.implementacion, es_custom=True)
        self.assertEqual(nuevo.nombre, "Certificado de matrimonio")
        self.assertEqual(list(nuevo.campos.values_list("nombre", flat=True)), ["Fecha de emisión", "Adjunto"])
        self.assertTrue(self.implementacion.documentos_legajo.get(tipo_documento=nuevo).activo)

    def test_tipos_documento_disponibles_solo_incluye_los_custom_de_esta_implementacion(self):
        otra_implementacion = Implementacion.objects.create(cliente=self.cliente)
        TipoDocumento.objects.create(implementacion=otra_implementacion, nombre="Otro de otro cliente", es_custom=True)

        disponibles = services.tipos_documento_disponibles(self.implementacion)
        nombres = {t.nombre for t in disponibles}

        self.assertIn("Documento de Prueba", nombres)
        self.assertNotIn("Otro de otro cliente", nombres)
