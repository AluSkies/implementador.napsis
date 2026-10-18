"""Qué se congela al validar y la copia de archivos."""

import hashlib
import json
import tempfile

from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from automatizacion.actores import Actor
from automatizacion.congelada import VERSION_ESQUEMA, contenido_de
from automatizacion.models import EventoImplementacion
from catalog.models import CampoDocumento, TipoDocumento
from clients.models import ImplementacionTipoDocumento
from onboarding import acciones
from onboarding.tests.base import EnviadaBase

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
