from django.urls import reverse

from clients.models import Cliente, Implementacion, Modulo

from dashboard.tests.base import BasePanel


def _dialogo(respuesta):
    """Solo el HTML del modal de alta (lo de afuera no cuenta para estos chequeos)."""
    html = respuesta.content.decode()
    return html[html.index('<dialog id="modal-alta"'):html.index("</dialog>")]


class BotonYModalTests(BasePanel):
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

    def test_el_alta_es_un_dialog(self):
        self.assertContains(self.client.get(reverse("dashboard:home")), '<dialog id="modal-alta" class="modal"')

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
        from django.contrib.staticfiles import finders

        respuesta = self.client.get(reverse("dashboard:home"))
        self.assertContains(respuesta, "portal.css")  # los estilos base (el fondo oscuro del modal incluido) están en la hoja compartida
        with open(finders.find("portal.css"), encoding="utf-8") as hoja:
            self.assertIn("dialog.modal::backdrop", hoja.read())
        self.assertContains(respuesta, "data-cerrar-alta")


class ReaperturaConErroresTests(BasePanel):
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


class LiquidacionesEnElAltaTests(BasePanel):
    """El modal ofrece las liquidaciones disponibles y la opción de bloquearlas."""

    def setUp(self):
        super().setUp()
        from catalog.models import TipoLiquidacion

        self.normal = TipoLiquidacion.objects.create(nombre="Liquidación Normal")
        self.aguinaldo = TipoLiquidacion.objects.create(nombre="Aguinaldo", orden=1)

    def test_el_modal_las_ofrece_con_la_opcion_de_bloquear(self):
        modal = _dialogo(self.client.get(reverse("dashboard:home")))
        self.assertIn("Liquidaciones disponibles para el cliente", modal)
        self.assertIn('name="liquidaciones"', modal)
        self.assertIn("Aguinaldo", modal)
        self.assertIn('name="liquidaciones_bloquear"', modal)
        self.assertIn("Estas son las liquidaciones de las que vas a disponer en tu Napsis", modal)

    def test_crear_con_liquidaciones_bloqueadas(self):
        self.crear(nombre="Textil SA", liquidaciones=[self.aguinaldo.pk], liquidaciones_bloquear="on")
        implementacion = Implementacion.objects.get(cliente__nombre="Textil SA")
        self.assertFalse(implementacion.liquidaciones_editables_por_cliente)
        self.assertEqual(
            list(implementacion.liquidaciones.filter(activo=True).values_list("tipo_liquidacion__nombre", flat=True)),
            ["Aguinaldo"],
        )

    def test_sin_tildar_bloquear_el_cliente_puede_editarlas(self):
        self.crear(nombre="Textil SA", liquidaciones=[self.aguinaldo.pk])
        self.assertTrue(Implementacion.objects.get(cliente__nombre="Textil SA").liquidaciones_editables_por_cliente)

    def test_bloquear_sin_elegir_ninguna_reabre_el_modal_con_el_error(self):
        respuesta = self.crear(nombre="Textil SA", liquidaciones_bloquear="on")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("elegir al menos una", _dialogo(respuesta))
        self.assertFalse(Implementacion.objects.filter(cliente__nombre="Textil SA").exists())

    def test_la_ficha_permite_bloquear_y_desbloquear(self):
        self.crear(nombre="Textil SA", liquidaciones=[self.aguinaldo.pk])
        implementacion = Implementacion.objects.get(cliente__nombre="Textil SA")
        url = reverse("dashboard:implementacion_detalle", kwargs={"pk": implementacion.pk})
        datos = {"accion": "actualizar_liquidaciones", "tipos_liquidacion": [self.aguinaldo.pk]}
        self.client.post(url, {**datos, "liquidaciones_bloquear": "on"})
        implementacion.refresh_from_db()
        self.assertFalse(implementacion.liquidaciones_editables_por_cliente)
        self.assertContains(self.client.get(url), "El cliente no puede cambiar las liquidaciones")
        self.client.post(url, datos)
        implementacion.refresh_from_db()
        self.assertTrue(implementacion.liquidaciones_editables_por_cliente)


class MaximoDeDocumentosEnElAltaTests(BasePanel):
    """En las opciones avanzadas se fija cuántos documentos del legajo puede elegir el cliente."""

    def test_el_modal_ofrece_el_campo_con_su_ayuda(self):
        modal = _dialogo(self.client.get(reverse("dashboard:home")))
        self.assertIn('name="max_documentos"', modal)
        self.assertIn("0 = sin límite", modal)

    def test_crear_con_maximo(self):
        self.crear(nombre="Textil SA", max_documentos=3)
        self.assertEqual(Implementacion.objects.get(cliente__nombre="Textil SA").max_documentos, 3)

    def test_sin_completarlo_no_hay_limite(self):
        self.crear(nombre="Textil SA")
        self.assertEqual(Implementacion.objects.get(cliente__nombre="Textil SA").max_documentos, 0)


class SeleccionarTodasEnElAltaTests(BasePanel):
    def setUp(self):
        super().setUp()
        from clients.models import Modulo

        self.obligatorio = Modulo.objects.create(nombre="Recibo Digital")
        self.otro = Modulo.objects.create(nombre="Fichada")

    def test_modulos_y_liquidaciones_ofrecen_seleccionar_todas(self):
        modal = _dialogo(self.client.get(reverse("dashboard:home")))
        self.assertIn('data-seleccionable="todos"', modal)
        self.assertIn('data-seleccionable="todas"', modal)

    def test_el_modulo_obligatorio_queda_fuera_de_la_seleccion_masiva(self):
        modal = _dialogo(self.client.get(reverse("dashboard:home")))
        entrada = lambda modulo: modal.split(f'id="modulo_{modulo.id}"')[1].split(">")[0]  # noqa: E731
        self.assertIn("data-fijo", entrada(self.obligatorio))
        self.assertNotIn("data-fijo", entrada(self.otro))
