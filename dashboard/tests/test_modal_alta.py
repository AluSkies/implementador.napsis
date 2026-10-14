from django.urls import reverse

from clients.models import Cliente, Implementacion, Modulo

from . import test_asignado


def _dialogo(respuesta):
    """Solo el HTML del modal de alta (lo de afuera no cuenta para estos chequeos)."""
    html = respuesta.content.decode()
    return html[html.index('<dialog id="modal-alta"'):html.index("</dialog>")]


class BotonYModalTests(test_asignado.BasePanel):
    """'Nueva implementación' es un botón verde que abre el alta en un modal."""

    def setUp(self):
        super().setUp()
        Modulo.objects.create(nombre="Módulo X")  # la base de test arranca sin catálogo

    def test_hay_un_boton_verde_con_el_icono_que_abre_el_modal(self):
        html = self.client.get(reverse("dashboard:home")).content.decode()
        boton = html[html.index("data-abrir-alta") - 80:html.index("data-abrir-alta") + 700]
        self.assertIn("btn success icono", boton)
        self.assertIn("<svg", boton)  # el cuadradito con la pluma
        self.assertIn("Nueva implementación", boton)

    def test_el_alta_es_un_dialog_y_no_una_tarjeta_fija(self):
        respuesta = self.client.get(reverse("dashboard:home"))
        self.assertContains(respuesta, '<dialog id="modal-alta" class="modal"')
        self.assertNotContains(respuesta, "dashboard-alta")

    def test_el_formulario_esta_dentro_del_modal(self):
        dialogo = _dialogo(self.client.get(reverse("dashboard:home")))
        for contenido in ('name="accion" value="crear_implementacion"', 'name="nombre"', 'name="cliente_id"',
                          'name="implementador_id"', 'name="max_roles"', 'name="modulos"', "Cancelar"):
            self.assertIn(contenido, dialogo)

    def test_las_condiciones_estan_plegadas_bajo_opciones_avanzadas(self):
        dialogo = _dialogo(self.client.get(reverse("dashboard:home")))
        self.assertIn('<details class="opciones-avanzadas" >', dialogo)
        self.assertIn("Opciones avanzadas", dialogo)
        self.assertLess(dialogo.index("Opciones avanzadas"), dialogo.index('name="max_roles"'))
        self.assertNotIn('name="tipo_empresa"', dialogo)

    def test_no_se_abre_solo_al_cargar_la_pagina(self):
        self.assertNotContains(self.client.get(reverse("dashboard:home")), "data-abrir=")

    def test_tiene_el_fondo_oscuro_y_se_puede_cerrar(self):
        respuesta = self.client.get(reverse("dashboard:home"))
        self.assertContains(respuesta, "dialog.modal::backdrop")
        self.assertContains(respuesta, "data-cerrar-alta")


class ReaperturaConErroresTests(test_asignado.BasePanel):
    """Si el alta falla, el modal vuelve a abrirse mostrando el motivo y sin perder lo
    que ya se había escrito (los errores van adentro: afuera los taparía el fondo oscuro)."""

    def setUp(self):
        super().setUp()
        self.modulo = Modulo.objects.create(nombre="Módulo X")

    def test_un_cuit_invalido_reabre_el_modal_con_el_error_adentro(self):
        respuesta = self.crear(nombre="Mi Empresa", cuits="30-50001091-3")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'data-abrir="1"')
        self.assertIn("no es válido", _dialogo(respuesta))
        self.assertFalse(Cliente.objects.exists())

    def test_conserva_lo_que_se_habia_escrito(self):
        respuesta = self.crear(
            nombre="Mi Empresa", razon_social="Mi Empresa S.A.", cuits="30-50001091-3", username="mi-usuario",
            implementador_id=str(self.admin.pk), modulos=[str(self.modulo.pk)], tipo_firma="digital", max_roles="4",
        )
        dialogo = _dialogo(respuesta)
        self.assertIn('value="Mi Empresa"', dialogo)
        self.assertIn('value="Mi Empresa S.A."', dialogo)
        self.assertIn('value="mi-usuario"', dialogo)
        self.assertIn('value="30-50001091-3"', dialogo)
        self.assertRegex(dialogo, rf'<option value="{self.admin.pk}" selected>')
        self.assertRegex(dialogo, rf'id="modulo_{self.modulo.pk}" checked')
        self.assertRegex(dialogo, r'<option value="digital" selected>')
        self.assertIn('value="4"', dialogo)

    def test_los_modulos_que_no_se_tildaron_siguen_sin_tildar(self):
        respuesta = self.crear(nombre="Mi Empresa", cuits="30-50001091-3")
        self.assertNotRegex(_dialogo(respuesta), rf'id="modulo_{self.modulo.pk}" checked')

    def test_sin_cliente_ni_nombre_avisa_en_vez_de_no_hacer_nada(self):
        respuesta = self.crear()
        self.assertContains(respuesta, 'data-abrir="1"')
        self.assertIn("Elegí un cliente existente o completá el nombre", _dialogo(respuesta))

    def test_un_cliente_existente_inexistente_tambien_avisa(self):
        respuesta = self.crear(cliente_id="999999")
        self.assertIn("Elegí un cliente existente", _dialogo(respuesta))

    def test_un_alta_exitosa_redirige_y_no_reabre_nada(self):
        respuesta = self.crear(nombre="Mi Empresa", cuits="30-50001091-2")
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Implementacion.objects.count(), 1)

    def test_los_errores_de_las_condiciones_tambien_van_dentro_del_modal(self):
        respuesta = self.crear(nombre="Mi Empresa", max_roles="9")
        dialogo = _dialogo(respuesta)
        self.assertIn("Revisá las condiciones del proceso", dialogo)
        self.assertIn('<details class="opciones-avanzadas" open>', dialogo)  # abierto para ver el error
