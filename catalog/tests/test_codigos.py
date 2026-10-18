from io import StringIO

from django.contrib import admin
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase

from catalog.codigos import codigo_desde_nombre
from catalog.models import TipoDocumento, TipoLicencia, TipoNovedad
from clients.models import Cliente, Implementacion, ImplementacionModulo, Modulo
from onboarding import services


class CodigoDesdeNombreTests(TestCase):
    def test_sin_tildes_en_minusculas_y_con_guiones_bajos(self):
        self.assertEqual(codigo_desde_nombre("Recibo Digital"), "recibo_digital")
        self.assertEqual(codigo_desde_nombre("Comunicación"), "comunicacion")
        self.assertEqual(codigo_desde_nombre("Licencia por Accidente de Trabajo (ART)"), "licencia_por_accidente_de_trabajo_art")
        self.assertEqual(codigo_desde_nombre("Horas Extra al 50%"), "horas_extra_al_50")

    def test_un_nombre_sin_letras_ni_numeros_igual_da_un_codigo(self):
        self.assertEqual(codigo_desde_nombre("???"), "item")


class CodigoDeLosCatalogosTests(TestCase):
    def test_se_genera_solo_al_crear(self):
        self.assertEqual(Modulo.objects.create(nombre="Recibo Digital").codigo, Modulo.RECIBO_DIGITAL)
        self.assertEqual(TipoLicencia.objects.create(nombre="Día de Cumpleaños").codigo, "dia_de_cumpleanos")
        self.assertEqual(TipoNovedad.objects.create(nombre="SUBE").codigo, "sube")

    def test_si_se_repite_se_le_agrega_un_sufijo(self):
        TipoNovedad.objects.create(nombre="Gimnasio")
        self.assertEqual(TipoNovedad.objects.create(nombre="gimnasio ").codigo, "gimnasio_2")

    def test_no_cambia_al_renombrar(self):
        modulo = Modulo.objects.create(nombre="Fichada")
        modulo.nombre = "Control de asistencia"
        modulo.save()
        modulo.refresh_from_db()
        self.assertEqual(modulo.codigo, Modulo.FICHADA)

    def test_los_tipos_otros_de_una_implementacion_no_llevan_codigo(self):
        implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
        propio = TipoDocumento.objects.create(nombre="Carnet", implementacion=implementacion, es_custom=True)
        global_ = TipoDocumento.objects.create(nombre="DNI")
        self.assertIsNone(propio.codigo)
        self.assertEqual(global_.codigo, "dni")

    def test_en_el_admin_el_codigo_es_de_solo_lectura_al_editar_pero_no_al_crear(self):
        modelo_admin = admin.site._registry[Modulo]
        pedido = RequestFactory().get("/admin/")
        modulo = Modulo.objects.create(nombre="Legajos")
        self.assertIn("codigo", modelo_admin.get_readonly_fields(pedido, modulo))
        self.assertNotIn("codigo", modelo_admin.get_readonly_fields(pedido, None))
        for modelo in (TipoLicencia, TipoNovedad, TipoDocumento):
            self.assertIn("codigo", admin.site._registry[modelo].get_readonly_fields(pedido, modelo(nombre="x", codigo="x")))


class RenombrarUnModuloNoRompeLosPasosTests(TestCase):
    """Antes los pasos dependían del nombre: corregirlo en el admin hacía desaparecer pasos sin avisar."""

    def test_los_pasos_siguen_a_pesar_del_nombre(self):
        implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
        fichada = Modulo.objects.create(nombre="Fichada")
        ImplementacionModulo.objects.create(implementacion=implementacion, modulo=fichada, activo=True)
        self.assertIn(services.PASO_SUCURSALES, services.pasos_activos(implementacion))

        fichada.nombre = "Control de asistencia (corregido)"
        fichada.save()
        self.assertIn(services.PASO_SUCURSALES, services.pasos_activos(implementacion))


class SemillasPorCodigoTests(TestCase):
    def test_corregir_un_nombre_y_completar_no_duplica(self):
        call_command("seed_catalogos", stdout=StringIO())
        TipoNovedad.objects.filter(codigo="prestamo").update(nombre="Préstamo")
        call_command("seed_catalogos", "--completar", stdout=StringIO())
        self.assertEqual(TipoNovedad.objects.count(), 10)
        self.assertEqual(TipoNovedad.objects.get(codigo="prestamo").nombre, "Préstamo")

    def test_los_modulos_se_siembran_con_su_codigo(self):
        call_command("seed_modulos", stdout=StringIO())
        self.assertEqual(
            set(Modulo.objects.values_list("codigo", flat=True)),
            {Modulo.RECIBO_DIGITAL, Modulo.COMUNICACION, Modulo.FICHADA, Modulo.LEGAJOS, Modulo.NOVEDADES},
        )

    def test_un_modulo_ya_corregido_no_se_duplica_ni_se_pisa(self):
        call_command("seed_modulos", stdout=StringIO())
        Modulo.objects.filter(codigo=Modulo.FICHADA).update(nombre="Control de asistencia", orden=9)
        call_command("seed_modulos", stdout=StringIO())
        self.assertEqual(Modulo.objects.count(), 5)
        modulo = Modulo.objects.get(codigo=Modulo.FICHADA)
        self.assertEqual((modulo.nombre, modulo.orden), ("Control de asistencia", 9))

    def test_un_modulo_anterior_a_los_codigos_adopta_el_codigo_en_vez_de_duplicarse(self):
        Modulo.objects.bulk_create([Modulo(nombre="Fichada", orden=2)])  # sin pasar por save(): sin código
        self.assertIsNone(Modulo.objects.get().codigo)
        call_command("seed_modulos", stdout=StringIO())
        self.assertEqual(Modulo.objects.filter(nombre="Fichada").count(), 1)
        self.assertEqual(Modulo.objects.get(nombre="Fichada").codigo, Modulo.FICHADA)


class MigracionDeCodigosTests(TransactionTestCase):
    """Lo que ya estaba cargado antes de los códigos los recibe a partir del nombre."""

    def test_asigna_codigos_a_lo_existente(self):
        ejecutor = MigrationExecutor(connection)
        antes = [("clients", "0011_condiciones_del_proceso"), ("catalog", "0002_seed_catalogos")]
        ejecutor.migrate(antes)
        viejas = ejecutor.loader.project_state(antes).apps
        viejas.get_model("clients", "Modulo").objects.create(nombre="Recibo Digital")
        viejas.get_model("clients", "Modulo").objects.create(nombre="Recibo  Digital!")  # mismo código base
        viejas.get_model("catalog", "TipoLicencia").objects.create(nombre="Vacaciones")
        viejas.get_model("catalog", "TipoDocumento").objects.create(nombre="DNI")
        viejas.get_model("catalog", "TipoDocumento").objects.create(nombre="Mi tipo", es_custom=True)

        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())
        nuevas = ejecutor.loader.project_state(ejecutor.loader.graph.leaf_nodes()).apps

        codigos = set(nuevas.get_model("clients", "Modulo").objects.values_list("codigo", flat=True))
        self.assertEqual(codigos, {"recibo_digital", "recibo_digital_2"})
        self.assertEqual(nuevas.get_model("catalog", "TipoLicencia").objects.get().codigo, "vacaciones")
        Documento = nuevas.get_model("catalog", "TipoDocumento")
        self.assertEqual(Documento.objects.get(nombre="DNI").codigo, "dni")
        self.assertIsNone(Documento.objects.get(nombre="Mi tipo").codigo)
