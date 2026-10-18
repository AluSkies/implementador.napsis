import uuid

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from clients.models import Cliente, Implementacion


def _nueva(**extra):
    return Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa"), **extra)


class UuidTests(TestCase):
    def test_cada_implementacion_tiene_su_uuid(self):
        a, b = _nueva(), _nueva()
        self.assertIsInstance(a.uuid, uuid.UUID)
        self.assertNotEqual(a.uuid, b.uuid)

    def test_no_se_confunde_con_el_token_secreto_del_link(self):
        implementacion = _nueva()
        self.assertNotIn(str(implementacion.uuid), implementacion.token)
        self.assertNotIn(implementacion.token, str(implementacion.uuid))

    def test_no_cambia_al_volver_a_guardar(self):
        implementacion = _nueva()
        original = implementacion.uuid
        implementacion.paso_actual = 3
        implementacion.save()
        implementacion.refresh_from_db()
        self.assertEqual(implementacion.uuid, original)


class OrigenEIdExternoTests(TestCase):
    def test_por_defecto_nace_en_el_portal_sin_id_externo(self):
        implementacion = _nueva()
        self.assertEqual((implementacion.origen, implementacion.id_externo), (Implementacion.ORIGEN_PORTAL, None))

    def test_varios_casos_sin_id_externo_conviven(self):
        _nueva(), _nueva(), _nueva()
        self.assertEqual(Implementacion.objects.count(), 3)

    def test_el_mismo_id_externo_del_mismo_origen_no_se_puede_repetir(self):
        _nueva(origen=Implementacion.ORIGEN_HUBSPOT, id_externo="deal-123")
        with self.assertRaises(IntegrityError), transaction.atomic():
            _nueva(origen=Implementacion.ORIGEN_HUBSPOT, id_externo="deal-123")

    def test_el_mismo_id_en_otro_origen_si_se_puede(self):
        _nueva(origen=Implementacion.ORIGEN_HUBSPOT, id_externo="123")
        _nueva(origen=Implementacion.ORIGEN_API, id_externo="123")
        self.assertEqual(Implementacion.objects.filter(id_externo="123").count(), 2)

    def test_se_busca_por_origen_e_id_externo(self):
        esperada = _nueva(origen=Implementacion.ORIGEN_HUBSPOT, id_externo="deal-9")
        self.assertEqual(Implementacion.objects.get(origen="hubspot", id_externo="deal-9"), esperada)


class MigracionDeIdentificadoresTests(TransactionTestCase):
    """Las implementaciones que ya existían reciben un uuid cada una (no el mismo para todas)."""

    def test_asigna_un_uuid_distinto_a_cada_una(self):
        ejecutor = MigrationExecutor(connection)
        antes = [("clients", "0012_codigos_estables")]
        ejecutor.migrate(antes)
        viejas = ejecutor.loader.project_state(antes).apps
        Cliente_ = viejas.get_model("clients", "Cliente")
        Implementacion_ = viejas.get_model("clients", "Implementacion")
        for i in range(3):
            Implementacion_.objects.create(cliente=Cliente_.objects.create(nombre=f"E{i}"), token=f"token-{i}")

        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())
        nuevas = ejecutor.loader.project_state(ejecutor.loader.graph.leaf_nodes()).apps
        uuids = list(nuevas.get_model("clients", "Implementacion").objects.values_list("uuid", flat=True))
        self.assertEqual((len(uuids), len(set(uuids))), (3, 3))
        self.assertTrue(all(u is not None for u in uuids))
