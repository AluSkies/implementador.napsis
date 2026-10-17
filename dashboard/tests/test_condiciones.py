from django.urls import reverse

from clients.models import Cliente, Implementacion

from . import test_asignado


class AltaConCondicionesTests(test_asignado.BasePanel):
    """Las condiciones se eligen al crear la implementación: lo que se completa queda fijo
    para el cliente y lo que se deja vacío lo decide él."""

    def test_sin_condiciones_queda_todo_en_manos_del_cliente(self):
        self.crear(nombre="Empresa Nueva")
        impl = Implementacion.objects.get()
        self.assertEqual(impl.max_roles, 6)
        self.assertTrue(impl.tipo_firma_editable and impl.nomenclatura_editable and impl.segmentacion_editable)

    def test_las_condiciones_elegidas_se_aplican_al_crear(self):
        self.crear(
            nombre="Empresa Nueva", tipo_firma="electronica",
            nomenclatura_pdf="recibo_{legajo}_{periodo}.pdf", area_unica="on", max_roles="4",
        )
        impl = Implementacion.objects.get()
        self.assertEqual(impl.max_roles, 4)
        self.assertEqual((impl.tipo_firma, impl.tipo_firma_editable), ("electronica", False))
        self.assertEqual((impl.nomenclatura_pdf, impl.nomenclatura_editable), ("recibo_{legajo}_{periodo}.pdf", False))
        self.assertEqual((impl.segmentacion_liquidador, impl.segmentacion_editable), ("AREA UNICA", False))

    def test_un_maximo_de_roles_invalido_no_crea_nada_y_avisa(self):
        for invalido in ("2", "9"):
            with self.subTest(max_roles=invalido):
                respuesta = self.crear(nombre="Empresa Nueva", max_roles=invalido)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, "Revisá las condiciones del proceso")
                self.assertFalse(Cliente.objects.exists())
                self.assertFalse(Implementacion.objects.exists())

    def test_el_formulario_de_alta_muestra_las_condiciones(self):
        respuesta = self.client.get(reverse("dashboard:home"))
        self.assertContains(respuesta, "Condiciones del proceso")
        for campo in ("tipo_firma", "nomenclatura_pdf", "area_unica", "max_roles"):
            self.assertContains(respuesta, f'name="{campo}"')

    def test_se_aplican_tambien_al_crear_para_una_empresa_existente(self):
        cliente = Cliente.objects.create(nombre="Ya existe")
        self.crear(cliente_id=str(cliente.pk), tipo_firma="digital", max_roles="3")
        impl = Implementacion.objects.get(cliente=cliente)
        self.assertEqual((impl.tipo_firma, impl.tipo_firma_editable, impl.max_roles), ("digital", False, 3))


class EdicionDeCondicionesTests(test_asignado.BasePanel):
    def setUp(self):
        super().setUp()
        self.implementacion = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="Empresa A"))
        self.url = reverse("dashboard:implementacion_detalle", kwargs={"pk": self.implementacion.pk})

    def test_se_pueden_modificar_desde_la_ficha(self):
        self.client.post(self.url, {
            "accion": "actualizar_condiciones", "tipo_firma": "digital", "max_roles": "5",
        })
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.tipo_firma, "digital")
        self.assertFalse(self.implementacion.tipo_firma_editable)
        self.assertEqual(self.implementacion.max_roles, 5)

    def test_queda_en_el_historial_con_el_estado_anterior(self):
        self.client.post(self.url, {"accion": "actualizar_condiciones", "max_roles": "4"})
        version = self.implementacion.versiones.get(seccion="condiciones")
        self.assertEqual(version.editado_por, "ana")
        self.assertEqual(version.datos["Tipo de firma"], "Que lo elija el cliente")
        self.assertEqual(version.datos["Máximo de personas con rol"], 6)

    def test_un_valor_invalido_no_guarda_y_reabre_la_seccion(self):
        respuesta = self.client.post(self.url, {"accion": "actualizar_condiciones", "max_roles": "1"})
        self.assertEqual(respuesta.status_code, 200)
        self.implementacion.refresh_from_db()
        self.assertEqual(self.implementacion.max_roles, 6)
        self.assertTrue(respuesta.context["condiciones_form"].errors)

    def test_la_ficha_muestra_que_esta_fijo_y_que_decide_el_cliente(self):
        self.implementacion.tipo_firma, self.implementacion.tipo_firma_editable = "digital", False
        self.implementacion.save()
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Condiciones del proceso")
        self.assertContains(pagina, "Digital")
        self.assertContains(pagina, "La define el cliente")  # la nomenclatura no se bloqueó

    def test_el_formulario_de_edicion_parte_de_lo_guardado(self):
        self.implementacion.nomenclatura_pdf, self.implementacion.nomenclatura_editable = "fija.pdf", False
        self.implementacion.save()
        formulario = self.client.get(self.url).context["condiciones_form"]
        self.assertEqual(formulario.initial["nomenclatura_pdf"], "fija.pdf")
        self.assertEqual(formulario.initial["tipo_firma"], "")
