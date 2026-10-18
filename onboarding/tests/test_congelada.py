"""La configuración congelada: la foto inmutable de lo que se aprobó para configurar (RT-06)."""

import hashlib
import json
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse

from automatizacion.actores import Actor
from automatizacion.congelada import VERSION_ESQUEMA, contenido_de, hash_de
from automatizacion.models import CongeladaInmutable, ConfiguracionCongelada, EventoImplementacion
from catalog.models import CampoDocumento, TipoDocumento
from clients.models import ImplementacionTipoDocumento
from onboarding import acciones, services
from onboarding.tests.test_rondas import EnviadaBase

ANA = Actor.implementador("ana")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CongelarAlValidarTests(EnviadaBase):
    def aprobar(self):
        resultado = acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertTrue(resultado.ok, resultado.avisos)
        self.implementacion.refresh_from_db()
        return self.implementacion.congeladas.order_by("-version").first()

    def test_al_validar_se_crea_la_version_1_con_su_evento(self):
        congelada = self.aprobar()
        self.assertEqual((congelada.version, congelada.version_esquema, congelada.creada_por), (1, VERSION_ESQUEMA, "ana"))
        self.assertEqual(congelada.implementacion_uuid, self.implementacion.uuid)
        self.assertEqual(len(congelada.hash), 64)
        evento = EventoImplementacion.objects.get(accion="estado.validada")
        self.assertEqual(evento.datos["congelada"], {"version": 1, "hash": congelada.hash})

    def test_el_contenido_usa_codigos_estables_y_los_datos_aprobados(self):
        contenido = self.aprobar().contenido
        self.assertEqual(contenido["esquema"], 1)
        self.assertEqual(contenido["modulos"], ["recibo_digital"])
        self.assertEqual(contenido["liquidaciones"], ["liquidacion_normal"])
        self.assertEqual(contenido["empresa"]["razon_social"], "Empresa A S.A.")
        self.assertEqual(contenido["empresa"]["cuits"], ["30-50001091-2"])
        self.assertEqual(contenido["implementacion"]["uuid"], str(self.implementacion.uuid))
        self.assertEqual([r["rol"] for r in contenido["roles"]], ["admin_rrhh", "apoderado", "liquidador"])
        self.assertEqual(contenido["firma"]["pagina"], "primera")
        self.assertEqual(set(contenido["firma"]["geometria"]), {"empresa", "conforme", "disconforme"})

    def test_cambiar_el_nombre_de_un_catalogo_no_cambia_el_contenido(self):
        antes = contenido_de(self.implementacion)
        self.liquidacion.nombre = "Liquidación mensual"
        self.liquidacion.save()
        self.assertEqual(contenido_de(self.implementacion), antes)

    def test_de_la_nomina_solo_van_las_cantidades(self):
        self.agregar_empleado("20999999990", "Extra", "Persona")
        contenido = self.aprobar().contenido
        self.assertEqual(contenido["nomina"], {"empleados": 3, "con_fecha_ingreso": 3})
        self.assertNotIn("20999999990", json.dumps(contenido))
        self.assertNotIn("Persona", json.dumps(contenido))

    def test_los_documentos_van_por_codigo_y_los_otros_con_su_definicion(self):
        dni = TipoDocumento.objects.create(nombre="DNI")
        propio = TipoDocumento.objects.create(nombre="Carnet de manejo", implementacion=self.implementacion, es_custom=True)
        CampoDocumento.objects.create(tipo_documento=propio, nombre="Vencimiento", obligatorio=True)
        for tipo in (dni, propio):
            ImplementacionTipoDocumento.objects.create(implementacion=self.implementacion, tipo_documento=tipo, activo=True)
        self.assertEqual(self.aprobar().contenido["documentos"], [
            {"codigo": "dni", "personalizado": False},
            {"codigo": None, "personalizado": True, "nombre": "Carnet de manejo",
             "campos": [{"nombre": "Vencimiento", "obligatorio": True}]},
        ])

    def test_se_copian_los_archivos_con_su_sha256(self):
        congelada = self.aprobar()
        archivos = {a["campo"]: a for a in congelada.archivos}
        self.assertEqual(set(archivos), {"modelo_recibo", "firma_imagen"})  # no hay logo ni banner
        modelo = archivos["modelo_recibo"]
        self.assertTrue(modelo["ruta"].startswith(f"congeladas/{self.implementacion.uuid}/v1/modelo_recibo"))
        self.assertTrue(modelo["ruta"].endswith(".pdf"))
        with default_storage.open(modelo["ruta"], "rb") as copia:
            datos = copia.read()
        self.assertEqual((hashlib.sha256(datos).hexdigest(), modelo["bytes"]), (modelo["sha256"], len(datos)))
        self.assertEqual(datos, b"%PDF-1.4")

    def test_la_copia_no_cambia_si_despues_se_reemplaza_el_archivo(self):
        congelada = self.aprobar()
        ruta = next(a["ruta"] for a in congelada.archivos if a["campo"] == "modelo_recibo")
        self.implementacion.modelo_recibo.save("otro.pdf", SimpleUploadedFile("otro.pdf", b"%PDF-1.4 distinto"))
        with default_storage.open(ruta, "rb") as copia:
            self.assertEqual(copia.read(), b"%PDF-1.4")

    def test_las_copias_quedan_fuera_del_alcance_de_un_cliente(self):
        congelada = self.aprobar()
        ruta = congelada.archivos[0]["ruta"]
        url = reverse("media", kwargs={"ruta": ruta})
        self.assertEqual(self.client.get(url).status_code, 404)  # el cliente dueño no las ve
        self.client.force_login(User.objects.create_user("ana", password="x", is_staff=True))
        self.assertEqual(self.client.get(url).status_code, 200)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VersionesTests(EnviadaBase):
    def aprobar(self):
        self.assertTrue(acciones.aprobar_para_configurar(ANA, self.implementacion).ok)
        return self.implementacion.congeladas.order_by("-version").first()

    def test_volver_a_aprobar_lo_mismo_da_otra_version_con_la_misma_huella(self):
        primera = self.aprobar()
        services.guardar_liquidaciones(self.implementacion, [], ANA)  # revoca la validación
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], ANA)
        segunda = self.aprobar()
        self.assertEqual((segunda.version, segunda.hash), (2, primera.hash))
        self.assertEqual(self.implementacion.congeladas.count(), 2)
        self.assertTrue(segunda.archivos[0]["ruta"].startswith(f"congeladas/{self.implementacion.uuid}/v2/"))

    def test_si_cambia_lo_aprobado_cambia_la_huella(self):
        primera = self.aprobar()
        self.implementacion.cliente.razon_social = "Nombre Nuevo S.A."
        self.implementacion.cliente.save()
        services.guardar_liquidaciones(self.implementacion, [], ANA)
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], ANA)
        self.assertNotEqual(self.aprobar().hash, primera.hash)

    def test_la_version_anterior_queda_intacta(self):
        primera = self.aprobar()
        contenido = json.loads(json.dumps(primera.contenido))
        services.guardar_liquidaciones(self.implementacion, [], ANA)
        self.implementacion.cliente.razon_social = "Otra"
        self.implementacion.cliente.save()
        services.guardar_liquidaciones(self.implementacion, [self.liquidacion], ANA)
        self.aprobar()
        self.assertEqual(ConfiguracionCongelada.objects.get(pk=primera.pk).contenido, contenido)

    def test_la_huella_depende_del_contenido_y_de_los_archivos_pero_no_de_las_rutas(self):
        contenido = {"a": 1}
        uno = [{"campo": "logo", "sha256": "aa", "ruta": "x/1"}]
        otro = [{"campo": "logo", "sha256": "aa", "ruta": "y/2"}]
        self.assertEqual(hash_de(contenido, uno), hash_de(contenido, otro))
        self.assertNotEqual(hash_de(contenido, uno), hash_de({"a": 2}, uno))
        self.assertNotEqual(hash_de(contenido, uno), hash_de(contenido, [{"campo": "logo", "sha256": "bb"}]))

    def test_el_orden_del_contenido_es_estable(self):
        self.agregar_empleado("20888888881", "A", "A")
        self.assertEqual(json.dumps(contenido_de(self.implementacion), sort_keys=True),
                         json.dumps(contenido_de(self.implementacion), sort_keys=True))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class InmutabilidadTests(EnviadaBase):
    def setUp(self):
        super().setUp()
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.congelada = self.implementacion.congeladas.get()

    def test_no_se_modifica(self):
        self.congelada.contenido = {}
        with self.assertRaises(CongeladaInmutable):
            self.congelada.save()
        with self.assertRaises(CongeladaInmutable):
            ConfiguracionCongelada.objects.update(hash="x")
        with self.assertRaises(CongeladaInmutable):
            ConfiguracionCongelada.objects.bulk_update([self.congelada], ["hash"])

    def test_no_se_borra(self):
        with self.assertRaises(CongeladaInmutable):
            self.congelada.delete()
        with self.assertRaises(CongeladaInmutable):
            ConfiguracionCongelada.objects.all().delete()

    def test_sobrevive_a_la_implementacion(self):
        uuid = self.implementacion.uuid
        self.implementacion.delete()
        self.assertEqual(ConfiguracionCongelada.objects.get(implementacion_uuid=uuid).version, 1)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SinCongelarTests(EnviadaBase):
    def test_si_falta_algo_no_se_valida_ni_se_congela(self):
        self.implementacion.empleados.all().delete()
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertFalse(self.implementacion.congeladas.exists())

    def test_si_un_archivo_no_se_puede_leer_no_se_valida_y_no_queda_nada_a_medias(self):
        Path(self.implementacion.modelo_recibo.path).unlink()
        resultado = acciones.aprobar_para_configurar(ANA, self.implementacion)
        self.assertIn("modelo_recibo", resultado.avisos[0].texto)
        self.implementacion.refresh_from_db()
        self.assertIsNone(self.implementacion.validada_en)
        self.assertFalse(self.implementacion.congeladas.exists())
        self.assertFalse(EventoImplementacion.objects.filter(accion="estado.validada").exists())

    def test_devolver_o_reabrir_no_borra_lo_ya_congelado(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        acciones.devolver_al_cliente(ANA, self.implementacion, "Revisá algo")
        acciones.reabrir(ANA, self.implementacion)
        self.assertEqual(self.implementacion.congeladas.count(), 1)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PanelTests(EnviadaBase):
    def setUp(self):
        super().setUp()
        self.ana = User.objects.create_user("ana", password="x", is_staff=True)
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_sin_aprobar_no_hay_seccion(self):
        self.client.force_login(self.ana)
        self.assertNotContains(self.client.get(self.url), "Configuración congelada")

    def test_la_ficha_muestra_la_version_vigente(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        congelada = self.implementacion.congeladas.get()
        self.client.force_login(self.ana)
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Configuración congelada")
        self.assertContains(pagina, "(vigente)")
        self.assertContains(pagina, congelada.hash[:12])
        self.assertContains(pagina, "Descargar .json")

    def test_si_se_pierde_la_validacion_ninguna_version_esta_vigente(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        services.guardar_liquidaciones(self.implementacion, [], ANA)
        self.client.force_login(self.ana)
        pagina = self.client.get(self.url)
        self.assertNotContains(pagina, "(vigente)")
        self.assertContains(pagina, "Ninguna versión está vigente")

    def test_el_equipo_descarga_el_json(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        congelada = self.implementacion.congeladas.get()
        self.client.force_login(self.ana)
        respuesta = self.client.get(reverse("dashboard:descargar_congelada", kwargs={"pk": self.implementacion.pk, "version": 1}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("attachment", respuesta["Content-Disposition"])
        datos = json.loads(respuesta.content)
        self.assertEqual((datos["version"], datos["hash"]), (1, congelada.hash))
        self.assertEqual(datos["contenido"]["modulos"], ["recibo_digital"])

    def test_un_cliente_no_puede_descargarla(self):
        acciones.aprobar_para_configurar(ANA, self.implementacion)
        url = reverse("dashboard:descargar_congelada", kwargs={"pk": self.implementacion.pk, "version": 1})
        self.assertEqual(self.client.get(url).status_code, 302)  # va al login

    def test_una_version_que_no_existe_da_404(self):
        self.client.force_login(self.ana)
        url = reverse("dashboard:descargar_congelada", kwargs={"pk": self.implementacion.pk, "version": 9})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_validar_desde_la_ficha_la_crea(self):
        self.client.force_login(self.ana)
        self.client.post(self.url, {"accion": "aprobar_para_configurar"})
        self.assertEqual(self.implementacion.congeladas.count(), 1)
        self.assertContains(self.client.get(self.url), "configuración congelada v1")
