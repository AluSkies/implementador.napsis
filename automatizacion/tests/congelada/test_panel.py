"""La configuración congelada en la ficha del panel."""

import json
import tempfile

from dashboard.tests.base import crear_supervisor
from django.test import override_settings
from django.urls import reverse

from automatizacion.actores import Actor
from onboarding import acciones, services
from onboarding.tests.base import EnviadaBase

ANA = Actor.implementador("ana")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PanelTests(EnviadaBase):
    def setUp(self):
        super().setUp()
        self.ana = crear_supervisor("ana")
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
