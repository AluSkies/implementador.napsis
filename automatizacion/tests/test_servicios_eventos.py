import io
from datetime import date, datetime
from unittest.mock import patch

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from automatizacion.actores import Actor
from automatizacion.models import EventoImplementacion
from clients.models import Cliente, Implementacion, PersonaRol, Sucursal
from employees.forms import EmpleadoForm
from employees.models import Empleado
from onboarding import services
from onboarding.forms import CondicionesForm, EmpresaForm, RolFormSet, SucursalFormSet

ANA = Actor.implementador("ana")
CLIENTE = Actor.cliente("cliente_a")


def _implementacion(**extra):
    return Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa A"), **extra)


def _eventos(accion=None):
    consulta = EventoImplementacion.objects.all()
    return consulta.filter(accion=accion) if accion else consulta


class DatosDeContactoTests(TestCase):
    def setUp(self):
        self.implementacion = _implementacion(telefono="011-1", mail_contacto="a@a.com")
        self.datos = {"razon_social": "A S.A.", "cuits": "30-50001091-2", "telefono": "011-2", "mail_contacto": "a@a.com"}

    def guardar(self, actor):
        formulario = EmpresaForm(self.datos, instance=self.implementacion)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        services.guardar_datos_contacto(self.implementacion, formulario, actor)

    def test_registra_quien_guardo_y_que_cambio(self):
        self.guardar(CLIENTE)
        evento = _eventos("paso.guardado").get()
        self.assertEqual((evento.actor_tipo, evento.seccion), ("cliente", "datos_contacto"))
        self.assertEqual(evento.datos["cambios"]["Teléfono"], {"antes": "011-1", "despues": "011-2"})
        self.assertNotIn("Mail de contacto", evento.datos["cambios"])  # lo que no cambió no aparece
        self.assertIn("Razón social", evento.datos["cambios"])

    def test_guardar_sin_cambiar_nada_tambien_queda_registrado(self):
        self.guardar(CLIENTE)
        self.guardar(CLIENTE)  # el cliente confirma el paso sin tocar nada
        segundo = list(_eventos("paso.guardado"))[1]
        self.assertEqual(segundo.datos["cambios"], {})

    def test_el_equipo_despues_del_envio_queda_marcado_como_correccion(self):
        self.implementacion.enviado = timezone.now()
        self.implementacion.save()
        self.guardar(ANA)
        self.assertTrue(_eventos("paso.guardado").get().post_envio)

    def test_el_cliente_antes_del_envio_no_se_marca(self):
        self.guardar(CLIENTE)
        self.assertFalse(_eventos("paso.guardado").get().post_envio)

    def test_el_historial_de_versiones_sigue_igual(self):
        self.guardar(ANA)
        version = self.implementacion.versiones.get(seccion="datos_contacto")
        self.assertEqual((version.editado_por, version.datos["Teléfono"]), ("ana", "011-1"))

    def test_si_falla_el_registro_no_queda_ni_el_cambio_ni_la_version(self):
        with patch("clients.services.eventos.registrar", side_effect=RuntimeError("base")):
            with self.assertRaises(RuntimeError):
                self.guardar(ANA)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.telefono, "011-1")
        self.assertFalse(self.implementacion.versiones.exists())


class OtrasSeccionesTests(TestCase):
    def setUp(self):
        self.implementacion = _implementacion()

    def test_los_roles_registran_la_lista_completa_antes_y_despues(self):
        PersonaRol.objects.create(implementacion=self.implementacion, rol=PersonaRol.ROL_APODERADO, apellido_nombre="Viejo, Rol")
        formset = RolFormSet({
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "0", "form-0-rol": PersonaRol.ROL_LIQUIDADOR,
            "form-0-apellido_nombre": "Gómez, Ana", "form-0-cuil": "", "form-0-mail": "",
        })
        self.assertTrue(formset.is_valid())
        services.guardar_roles(self.implementacion, formset, CLIENTE)
        cambio = _eventos("paso.guardado").get().datos["cambios"]["lista"]
        self.assertEqual(cambio["antes"][0]["Apellido y Nombre"], "Viejo, Rol")
        self.assertEqual(cambio["despues"][0]["Apellido y Nombre"], "Gómez, Ana")

    def test_las_sucursales_se_registran(self):
        formset = SucursalFormSet({
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "0", "form-0-nombre": "Central", "form-0-calle": "Mitre",
            "form-0-altura": "", "form-0-piso_depto": "", "form-0-codigo_postal": "", "form-0-localidad": "",
            "form-0-entre_calles": "", "form-0-observaciones": "",
        })
        self.assertTrue(formset.is_valid())
        services.guardar_sucursales(self.implementacion, formset, CLIENTE)
        evento = _eventos("paso.guardado").get()
        self.assertEqual(evento.seccion, "sucursales")
        self.assertEqual(evento.datos["cambios"]["lista"]["despues"][0]["Nombre"], "Central")
        self.assertEqual(Sucursal.objects.count(), 1)

    def test_los_modulos_muestran_cual_se_activo(self):
        from clients.models import Modulo

        modulo = Modulo.objects.create(nombre="Fichada")
        services.guardar_modulos(self.implementacion, Modulo.objects.all(), {modulo.id}, ANA)
        self.assertEqual(
            _eventos("paso.guardado").get().datos["cambios"], {"Fichada": {"antes": None, "despues": True}},
        )

    def test_las_condiciones_tienen_su_propia_accion(self):
        formulario = CondicionesForm({"tipo_firma": "digital", "max_roles": "4"})
        self.assertTrue(formulario.is_valid())
        services.guardar_condiciones(self.implementacion, formulario, ANA)
        evento = _eventos("implementacion.condiciones_actualizadas").get()
        self.assertEqual(evento.datos["cambios"]["Máximo de personas con rol"], {"antes": 6, "despues": 4})

    def test_la_fecha_tiene_su_propia_accion(self):
        services.guardar_fecha_implementacion(self.implementacion, date(2026, 12, 1), ANA)
        evento = _eventos("implementacion.fecha_cambiada").get()
        self.assertEqual(
            evento.datos["cambios"]["Fecha estimada de salida en productivo"], {"antes": None, "despues": "2026-12-01"},
        )

    def test_las_licencias_y_documentos_se_registran_con_el_camino_del_grupo(self):
        from catalog.models import TipoLicencia
        from onboarding.forms import LicenciasNovedadesForm

        licencia = TipoLicencia.objects.create(nombre="Vacaciones")
        formulario = LicenciasNovedadesForm(
            {f"licencia_{licencia.id}_activo": "on"}, licencias_qs=TipoLicencia.objects.all(), novedades_qs=[],
            estado_por_licencia={}, estado_por_novedad={},
        )
        self.assertTrue(formulario.is_valid())
        services.guardar_licencias_y_novedades(self.implementacion, formulario, TipoLicencia.objects.all(), [], ANA)
        self.assertEqual(
            _eventos("paso.guardado").get().datos["cambios"], {"Licencias › Vacaciones": {"antes": None, "despues": True}},
        )


class EmpleadosTests(TestCase):
    def setUp(self):
        self.implementacion = _implementacion()

    def _form(self, **extra):
        datos = {"cuil": "20-11111111-2", "nombre": "juan", "apellido": "pérez", **extra}
        return EmpleadoForm(datos, implementacion=self.implementacion)

    def test_agregar_registra_solo_el_id(self):
        services.agregar_empleado(self.implementacion, self._form(), CLIENTE)
        evento = _eventos("empleado.agregado").get()
        self.assertEqual(evento.datos, {"empleado_id": Empleado.objects.get().pk})  # nada de datos personales

    def test_editar_registra_el_antes_y_el_despues_de_lo_que_cambio(self):
        services.agregar_empleado(self.implementacion, self._form(puesto="Analista"), CLIENTE)
        empleado = Empleado.objects.get()
        formulario = EmpleadoForm(
            {"cuil": "20111111112", "nombre": "JUAN", "apellido": "PEREZ", "puesto": "Gerente"},
            instance=empleado, implementacion=self.implementacion,
        )
        self.assertTrue(services.editar_empleado(self.implementacion, formulario, ANA))
        cambios = _eventos("empleado.editado").get().datos["cambios"]
        self.assertEqual(cambios, {"puesto": {"antes": "Analista", "despues": "Gerente"}})

    def test_eliminar_guarda_la_foto_de_lo_que_se_borra(self):
        services.agregar_empleado(self.implementacion, self._form(puesto="Analista"), CLIENTE)
        empleado = Empleado.objects.get()
        services.eliminar_empleado(self.implementacion, str(empleado.pk), ANA)
        evento = _eventos("empleado.eliminado").get()
        self.assertEqual((evento.datos["empleado_id"], evento.datos["foto"]["cuil"], evento.datos["foto"]["puesto"]),
                         (empleado.pk, "20111111112", "Analista"))
        self.assertFalse(Empleado.objects.exists())

    def test_eliminar_algo_que_no_existe_no_registra_nada(self):
        services.eliminar_empleado(self.implementacion, "99999", ANA)
        self.assertFalse(_eventos().exists())

    def test_un_alta_que_choca_en_la_base_no_deja_evento(self):
        primero, segundo = self._form(), self._form()
        self.assertTrue(primero.is_valid() and segundo.is_valid())
        services.agregar_empleado(self.implementacion, primero, CLIENTE)
        services.agregar_empleado(self.implementacion, segundo, CLIENTE)
        self.assertEqual(_eventos("empleado.agregado").count(), 1)


def _xlsx(filas, cabecera=("CUIL", "Nombre", "Apellido", "Puesto")):
    libro = openpyxl.Workbook()
    libro.active.append(list(cabecera))
    for fila in filas:
        libro.active.append(fila)
    buffer = io.BytesIO()
    libro.save(buffer)
    return SimpleUploadedFile("nomina.xlsx", buffer.getvalue())


class ImportacionDeNominaTests(TestCase):
    def setUp(self):
        self.implementacion = _implementacion()

    def importar(self, filas, actor=CLIENTE, **extra):
        return services.importar_archivo_empleados(self.implementacion, _xlsx(filas, **extra), actor)

    def test_la_primera_carga_registra_un_resumen_sin_copiar_a_los_empleados(self):
        self.importar([[20111111112, "Juan", "Pérez", "Analista"], [20222222223, "Ana", "Gómez", "Gerente"], ["12", "Mal", "Cuil", ""]])
        datos = _eventos("nomina.importada").get().datos
        self.assertEqual((datos["archivo"], datos["filas_leidas"], datos["nuevos"], datos["actualizados"], datos["filas_con_error"]),
                         ("nomina.xlsx", 3, 2, 0, 1))
        self.assertEqual(datos["correcciones"], [])
        texto = str(datos)
        self.assertNotIn("PEREZ", texto)  # los empleados nuevos ya quedan en Empleado: no se duplican
        self.assertNotIn("20111111112", texto)

    def test_reimportar_con_cambios_registra_el_antes_y_el_despues(self):
        self.importar([[20111111112, "Juan", "Pérez", "Analista"]])
        self.importar([[20111111112, "Juan", "Pérez", "Gerente"]], actor=ANA)
        datos = list(_eventos("nomina.importada"))[1].datos
        self.assertEqual((datos["nuevos"], datos["actualizados"]), (0, 1))
        correccion = datos["correcciones"][0]
        self.assertEqual(correccion["empleado_id"], Empleado.objects.get().pk)
        self.assertEqual(correccion["cambios"], {"puesto": {"antes": "Analista", "despues": "Gerente"}})

    def test_las_fechas_de_las_correcciones_son_json(self):
        cabecera = ("CUIL", "Nombre", "Apellido", "Fecha Ingreso (DD/MM/AAAA)")
        self.importar([[20111111112, "Juan", "Pérez", datetime(2020, 3, 15)]], cabecera=cabecera)
        self.importar([[20111111112, "Juan", "Pérez", datetime(2021, 1, 1)]], cabecera=cabecera)
        cambios = list(_eventos("nomina.importada"))[1].datos["correcciones"][0]["cambios"]
        self.assertEqual(cambios["fecha_ingreso"], {"antes": "2020-03-15", "despues": "2021-01-01"})

    def test_la_misma_planilla_dos_veces_no_registra_correcciones(self):
        self.importar([[20111111112, "Juan", "Pérez", "Analista"]])
        self.importar([[20111111112, "Juan", "Pérez", "Analista"]])
        self.assertEqual(list(_eventos("nomina.importada"))[1].datos["correcciones"], [])

    def test_el_detalle_tiene_tope(self):
        with patch("onboarding.services.nomina.MAX_CORRECCIONES_EN_EVENTO", 2):
            self.importar([[20000000000 + i, "J", "P", "A"] for i in range(5)])
            self.importar([[20000000000 + i, "J", "P", "B"] for i in range(5)])
        datos = list(_eventos("nomina.importada"))[1].datos
        self.assertEqual((len(datos["correcciones"]), datos["correcciones_truncadas"], datos["actualizados"]), (2, True, 5))

    def test_un_archivo_invalido_no_deja_evento(self):
        from employees.services import ArchivoInvalido

        with self.assertRaises(ArchivoInvalido):
            services.importar_archivo_empleados(self.implementacion, SimpleUploadedFile("x.xlsx", b"roto"), ANA)
        self.assertFalse(_eventos().exists())

    def test_si_algo_falla_a_mitad_no_queda_evento_ni_empleados(self):
        with patch("onboarding.services.nomina._resolver_jerarquia_importada", side_effect=RuntimeError("base")):
            with self.assertRaises(RuntimeError):
                self.importar([[20111111112, "Juan", "Pérez", "A"]])
        self.assertFalse(_eventos().exists())
        self.assertFalse(Empleado.objects.exists())
