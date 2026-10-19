"""Pasos activos y días hábiles."""

from django.test import TestCase

from clients.models import Cliente, Implementacion, ImplementacionModulo, Modulo
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
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 4, 10])

    def test_fichada_activa_el_paso_de_sucursales(self):
        self._activar_modulo("Fichada")
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 3, 4, 10])

    def test_legajos_activa_roles_y_documentos_pero_no_configuracion(self):
        self._activar_modulo("Legajos")
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 4, 5, 9, 10])

    def test_novedades_activa_el_paso_de_licencias_y_novedades(self):
        self._activar_modulo("Novedades")
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 4, 8, 10])

    def test_recibo_digital_activa_roles_y_configuracion_pero_no_documentos(self):
        self._activar_modulo("Recibo Digital")
        self.assertEqual(services.pasos_activos(self.implementacion), [1, 2, 4, 5, 6, 7, 10])


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
