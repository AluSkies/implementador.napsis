from django.test import TestCase

from catalog.models import TipoDocumento, TipoLicencia, TipoNovedad
from clients.models import Cliente, Implementacion, ImplementacionModulo, Modulo, PersonaRol, Sucursal
from employees.forms import EmpleadoForm
from employees.models import Empleado
from onboarding import services


class PasosActivosTests(TestCase):
    """pasos_activos() decide qué pasos ve el cliente según los módulos contratados —
    romperlo manda al cliente a un paso que no le corresponde o lo salta de largo."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def _activar_modulo(self, nombre):
        modulo, _ = Modulo.objects.get_or_create(nombre=nombre)
        ImplementacionModulo.objects.update_or_create(
            implementacion=self.implementacion, modulo=modulo, defaults={"activo": True},
        )

    def test_sin_modulos_solo_los_pasos_universales(self):
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 4, 9])

    def test_fichada_activa_el_paso_de_sucursales(self):
        self._activar_modulo("Fichada")
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 3, 4, 9])

    def test_legajos_activa_roles_y_documentos_pero_no_configuracion(self):
        self._activar_modulo("Legajos")
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 4, 5, 8, 9])

    def test_novedades_activa_el_paso_de_licencias_y_novedades(self):
        self._activar_modulo("Novedades")
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 4, 7, 9])

    def test_recibo_digital_activa_roles_y_configuracion_pero_no_documentos(self):
        self._activar_modulo("Recibo Digital")
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 4, 5, 6, 9])


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

        services.guardar_datos_contacto(self.implementacion, form, "Test")

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
            self.implementacion, Modulo.objects.all(), {self.modulo_a.id}, "Test",
        )
        activos = set(
            self.implementacion.modulos.filter(activo=True).values_list("modulo__nombre", flat=True)
        )
        self.assertEqual(activos, {"Módulo A"})

    def test_guarda_version_antes_de_aplicar_el_cambio(self):
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), {self.modulo_a.id}, "Test")
        version = self.implementacion.versiones.get(seccion="modulos")
        # Ningún módulo estaba activo todavía en el momento del snapshot.
        self.assertEqual(version.datos, {})

    def test_es_idempotente_para_el_mismo_conjunto(self):
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), {self.modulo_a.id}, "Test")
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), {self.modulo_a.id}, "Test")
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

        services.guardar_roles(self.implementacion, formset, "Test")

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

        services.guardar_sucursales(self.implementacion, formset, "Test")

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
            self.implementacion, form, TipoLicencia.objects.all(), TipoNovedad.objects.all(), "Test",
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
            self.implementacion, form, services.tipos_documento_disponibles(self.implementacion), "Test",
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


class EmpleadosTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def test_agregar_empleado_guarda_version_antes_del_alta(self):
        form = EmpleadoForm(
            {"cuil": "20333333334", "nombre": "Ana", "apellido": "López"},
            implementacion=self.implementacion,
        )
        agregado = services.agregar_empleado(self.implementacion, form, "Test")

        self.assertTrue(agregado)
        self.assertEqual(self.implementacion.empleados.count(), 1)
        version = self.implementacion.versiones.get(seccion="empleados")
        self.assertEqual(version.datos, [])  # no había empleados al momento del snapshot

    def test_agregar_empleado_con_form_invalido_no_guarda_nada(self):
        form = EmpleadoForm({"cuil": ""}, implementacion=self.implementacion)
        agregado = services.agregar_empleado(self.implementacion, form, "Test")

        self.assertFalse(agregado)
        self.assertEqual(self.implementacion.empleados.count(), 0)
        self.assertFalse(self.implementacion.versiones.filter(seccion="empleados").exists())

    def test_eliminar_empleado_con_id_valido(self):
        form = EmpleadoForm(
            {"cuil": "20333333334", "nombre": "Ana", "apellido": "López"},
            implementacion=self.implementacion,
        )
        services.agregar_empleado(self.implementacion, form, "Test")
        empleado_id = self.implementacion.empleados.get().id

        services.eliminar_empleado(self.implementacion, str(empleado_id), "Test")

        self.assertEqual(self.implementacion.empleados.count(), 0)

    def test_eliminar_empleado_con_id_no_numerico_no_rompe(self):
        """Regresión: esto tiraba ValueError sin capturar (500) antes del fix."""
        try:
            services.eliminar_empleado(self.implementacion, "no-es-un-id", "Test")
        except ValueError:
            self.fail("eliminar_empleado no debería propagar ValueError ante un id inválido")

    def test_eliminar_empleado_con_id_no_numerico_no_guarda_version(self):
        services.eliminar_empleado(self.implementacion, "abc", "Test")
        self.assertFalse(self.implementacion.versiones.filter(seccion="empleados").exists())


class PendientesDeEnvioTests(TestCase):
    """Qué falta para poder enviar depende de los módulos contratados: sin Recibo Digital
    no se pide el modelo de recibo, y sin Recibo Digital ni Legajos no se piden roles."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Empresa de Prueba")
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)

    def _activar(self, *nombres):
        for nombre in nombres:
            modulo, _ = Modulo.objects.get_or_create(nombre=nombre)
            ImplementacionModulo.objects.create(implementacion=self.implementacion, modulo=modulo, activo=True)

    def _pasos(self):
        return [p["paso"] for p in services.pendientes_de_envio(self.implementacion)]

    def test_sin_modulos_solo_pide_empresa_y_nomina(self):
        self.assertEqual(self._pasos(), [1, 4])

    def test_con_recibo_digital_pide_tambien_roles_y_modelo_de_recibo(self):
        self._activar("Recibo Digital")
        self.assertEqual(self._pasos(), [1, 4, 5, 6])

    def test_con_legajos_pide_roles_pero_no_modelo_de_recibo(self):
        self._activar("Legajos")
        self.assertEqual(self._pasos(), [1, 4, 5])

    def test_con_fichada_no_pide_nada_extra(self):
        self._activar("Fichada")
        self.assertEqual(self._pasos(), [1, 4])

    def test_la_razon_social_sola_no_alcanza_hace_falta_el_cuit(self):
        self.cliente.razon_social = "Empresa S.A."
        self.cliente.save()
        self.assertIn(1, self._pasos())

    def test_todo_completo_no_deja_pendientes(self):
        self.cliente.razon_social = "Empresa S.A."
        self.cliente.cuits = "30-50001091-2"
        self.cliente.save()
        Empleado.objects.create(implementacion=self.implementacion, cuil="20111111112", nombre="A", apellido="B")
        self.assertEqual(services.pendientes_de_envio(self.implementacion), [])

    def test_un_rol_sin_nombre_no_cuenta(self):
        self._activar("Legajos")
        for rol in (PersonaRol.ROL_APODERADO, PersonaRol.ROL_LIQUIDADOR):
            PersonaRol.objects.create(implementacion=self.implementacion, rol=rol, apellido_nombre="X, Y")
        PersonaRol.objects.create(implementacion=self.implementacion, rol=PersonaRol.ROL_ADMIN_RRHH, apellido_nombre="")
        self.assertIn(5, self._pasos())


class DiasHabilesTests(TestCase):
    """El mínimo para el cliente se cuenta en días hábiles: lunes a viernes, sin descontar
    feriados (decisión del negocio)."""

    def test_diez_dias_habiles_desde_un_miercoles_son_dos_semanas(self):
        from datetime import date

        self.assertEqual(services.sumar_dias_habiles(date(2026, 10, 14), 10), date(2026, 10, 28))

    def test_desde_un_viernes_el_primer_dia_habil_es_el_lunes(self):
        from datetime import date

        self.assertEqual(services.sumar_dias_habiles(date(2026, 10, 16), 1), date(2026, 10, 19))

    def test_desde_un_fin_de_semana_cuenta_desde_el_lunes(self):
        from datetime import date

        self.assertEqual(services.sumar_dias_habiles(date(2026, 10, 17), 1), date(2026, 10, 19))  # sábado
        self.assertEqual(services.sumar_dias_habiles(date(2026, 10, 18), 10), date(2026, 10, 30))  # domingo

    def test_cero_dias_es_la_misma_fecha(self):
        from datetime import date

        self.assertEqual(services.sumar_dias_habiles(date(2026, 10, 14), 0), date(2026, 10, 14))

    def test_la_fecha_minima_del_cliente_son_diez_dias_habiles_desde_hoy(self):
        from datetime import date

        self.assertEqual(services.fecha_minima_para_cliente(date(2026, 10, 14)), date(2026, 10, 28))

    def test_el_mismo_resultado_cae_siempre_en_dia_habil(self):
        from datetime import date, timedelta

        for i in range(14):
            self.assertLess(services.sumar_dias_habiles(date(2026, 10, 1) + timedelta(days=i), 10).weekday(), 5)
