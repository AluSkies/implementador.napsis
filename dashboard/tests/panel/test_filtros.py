"""El panel lateral de filtros del listado: qué ofrece a cada rol, cómo filtra y los chips de lo aplicado."""

from django.urls import reverse

from dashboard.tests.base import BaseGrupos

HOME = "dashboard:home"


class BaseFiltros(BaseGrupos):
    def listado(self, usuario, **params):
        self.client.force_login(usuario)
        return self.client.get(reverse(HOME), params)

    def empresas_del_listado(self, usuario, **params):
        return sorted(i.cliente.nombre for i in self.listado(usuario, **params).context["implementaciones"])

    def asignados_del_listado(self, usuario, **params):
        return sorted(i.asignado_nombre for i in self.listado(usuario, **params).context["implementaciones"])

    def nombres_de_empresas_ofrecidas(self, usuario):
        return [e["nombre"] for e in self.listado(usuario).context["filtros"]["empresas"]]


class OpcionesDelPanelTests(BaseFiltros):
    def test_el_implementador_no_ve_el_filtro_de_implementador(self):
        respuesta = self.listado(self.ana)
        self.assertIsNone(respuesta.context["filtros"]["implementadores"])
        self.assertNotContains(respuesta, 'name="implementador"')

    def test_el_supervisor_ve_mias_y_las_secciones_de_sus_grupos(self):
        filtros = self.listado(self.sol).context["filtros"]["implementadores"]
        self.assertEqual((filtros["mias"]["nombre"], filtros["mias"]["n"]), ("Mías", 1))
        self.assertEqual([s["nombre"] for s in filtros["secciones"]], ["Norte"])
        personas = {p["nombre"]: p["n"] for p in filtros["secciones"][0]["personas"]}
        self.assertEqual(personas, {"Ana Paz": 2, "Beto Ruiz": 1})
        self.assertIsNone(filtros["sin_asignar"])

    def test_el_supervisor_no_se_ofrece_a_si_mismo_dos_veces_ni_al_otro_equipo(self):
        secciones = self.listado(self.sol).context["filtros"]["implementadores"]["secciones"]
        nombres = [p["nombre"] for s in secciones for p in s["personas"]]
        self.assertNotIn("Sol Vega", nombres)
        self.assertNotIn("Diego Sosa", nombres)
        self.assertNotIn("Lucía Mora", nombres)

    def test_el_admin_ve_todos_los_grupos_con_sus_supervisores_sin_grupo_y_sin_asignar(self):
        filtros = self.listado(self.admin).context["filtros"]["implementadores"]
        secciones = {s["nombre"]: s["personas"] for s in filtros["secciones"]}
        self.assertEqual(set(secciones), {"Norte", "Sur", "Sin grupo"})
        self.assertIn(("Sol Vega", "supervisor"), [(p["nombre"], p["rol"]) for p in secciones["Norte"]])
        self.assertEqual([p["nombre"] for p in secciones["Sin grupo"]], ["Carla Gómez"])
        self.assertEqual(filtros["sin_asignar"]["n"], 1)

    def test_las_empresas_ofrecidas_son_las_que_se_ven(self):
        self.assertEqual(self.nombres_de_empresas_ofrecidas(self.sol), ["Empresa Mixta", "Empresa Norte"])
        self.assertEqual(self.nombres_de_empresas_ofrecidas(self.carla), ["Empresa Sur"])
        self.assertEqual(self.nombres_de_empresas_ofrecidas(self.admin), ["Empresa Mixta", "Empresa Norte", "Empresa Sur"])

    def test_las_cantidades_son_las_de_lo_que_se_ve(self):
        empresas = {e["nombre"]: e["n"] for e in self.listado(self.sol).context["filtros"]["empresas"]}
        self.assertEqual(empresas, {"Empresa Norte": 3, "Empresa Mixta": 1})

    def test_las_cantidades_por_estado(self):
        estados = {e["clave"]: e["n"] for e in self.listado(self.admin).context["filtros"]["estados"]}
        self.assertEqual(estados["a_completar"], 9)
        self.assertEqual(estados["completo"], 0)
        self.assertIn("sin_movimiento", estados)

    def test_el_resumen_dice_cuantas_se_muestran_de_cuantas_se_ven(self):
        respuesta = self.listado(self.sol, implementador=self.ana.pk)
        self.assertEqual((respuesta.context["mostrando"], respuesta.context["total_visibles"]), (2, 4))
        self.assertContains(respuesta, "Mostrando <strong>2</strong> de 4 implementaciones que podés ver.")

    def test_el_titulo_de_un_grupo_queda_marcado_si_estan_todos_sus_integrantes(self):
        sin_marcar = self.listado(self.sol).context["filtros"]["implementadores"]["secciones"][0]
        self.assertFalse(sin_marcar["todos"])
        todos = self.listado(self.sol, implementador=[self.ana.pk, self.beto.pk])
        self.assertTrue(todos.context["filtros"]["implementadores"]["secciones"][0]["todos"])


class FiltrarTests(BaseFiltros):
    def test_por_implementador(self):
        self.assertEqual(self.asignados_del_listado(self.sol, implementador=self.beto.pk), ["Beto Ruiz"])
        self.assertEqual(
            self.asignados_del_listado(self.sol, implementador=[self.ana.pk, self.beto.pk]),
            ["Ana Paz", "Ana Paz", "Beto Ruiz"],
        )

    def test_mias(self):
        self.assertEqual(self.asignados_del_listado(self.sol, implementador=self.sol.pk), ["Sol Vega"])

    def test_sin_asignar_solo_lo_encuentra_el_admin(self):
        self.assertEqual(self.empresas_del_listado(self.admin, implementador="sin"), ["Empresa Sur"])
        self.assertEqual(self.empresas_del_listado(self.sol, implementador="sin"), [])

    def test_un_implementador_ajeno_a_mi_vista_no_devuelve_nada(self):
        self.assertEqual(self.empresas_del_listado(self.sol, implementador=self.diego.pk), [])
        self.assertEqual(self.empresas_del_listado(self.ana, implementador=self.beto.pk), [])

    def test_por_empresa(self):
        self.assertEqual(self.empresas_del_listado(self.sol, empresa=self.empresa_mixta.pk), ["Empresa Mixta"])
        self.assertEqual(
            self.empresas_del_listado(self.admin, empresa=[self.empresa_mixta.pk, self.empresa_sur.pk]),
            ["Empresa Mixta", "Empresa Mixta", "Empresa Sur", "Empresa Sur", "Empresa Sur", "Empresa Sur"],
        )

    def test_una_empresa_que_no_se_ve_no_se_cuela_por_la_url(self):
        self.assertEqual(self.empresas_del_listado(self.sol, empresa=self.empresa_sur.pk), [])

    def test_por_varios_estados(self):
        self.assertEqual(len(self.empresas_del_listado(self.admin, estado=["a_completar", "completo"])), 9)
        self.assertEqual(self.empresas_del_listado(self.admin, estado="completo"), [])

    def test_los_filtros_se_combinan(self):
        self.assertEqual(
            self.empresas_del_listado(self.admin, empresa=self.empresa_mixta.pk, implementador=self.diego.pk),
            ["Empresa Mixta"],
        )

    def test_el_texto_de_busqueda_sigue_funcionando(self):
        self.assertEqual(self.empresas_del_listado(self.admin, cliente="mixta"), ["Empresa Mixta", "Empresa Mixta"])

    def test_una_marca_en_la_url_que_no_es_un_numero_se_ignora(self):
        self.assertEqual(len(self.empresas_del_listado(self.admin, empresa="x", implementador="y")), 9)


class ChipsTests(BaseFiltros):
    def chips(self, usuario, **params):
        return self.listado(usuario, **params).context["filtros"]["chips"]

    def test_sin_filtros_no_hay_chips_ni_enlace_para_limpiar(self):
        respuesta = self.listado(self.sol)
        self.assertEqual(respuesta.context["filtros"]["chips"], [])
        self.assertNotContains(respuesta, "Limpiar todo")

    def test_cada_filtro_tiene_su_chip_y_el_enlace_que_lo_quita(self):
        chips = self.chips(self.admin, implementador=self.ana.pk, empresa=self.empresa_norte.pk, estado="a_completar")
        self.assertEqual(
            [c["texto"] for c in chips],
            ["Empresa: Empresa Norte", "Implementador: Ana Paz", "Estado: Pendiente - A completar por cliente"],
        )
        sin_empresa = chips[0]["quitar"]
        self.assertNotIn("empresa=", sin_empresa)
        self.assertIn(f"implementador={self.ana.pk}", sin_empresa)
        self.assertIn("estado=a_completar", sin_empresa)

    def test_quitar_un_solo_valor_deja_los_otros_del_mismo_filtro(self):
        chips = self.chips(self.sol, implementador=[self.ana.pk, self.beto.pk])
        self.assertEqual([c["texto"] for c in chips], ["Implementador: Ana Paz", "Implementador: Beto Ruiz"])
        self.assertEqual(chips[0]["quitar"], f"{reverse(HOME)}?implementador={self.beto.pk}")
        self.assertEqual(chips[1]["quitar"], f"{reverse(HOME)}?implementador={self.ana.pk}")

    def test_quitar_el_ultimo_filtro_vuelve_al_listado_limpio(self):
        self.assertEqual(self.chips(self.sol, empresa=self.empresa_norte.pk)[0]["quitar"], reverse(HOME))

    def test_los_chips_conservan_el_orden_elegido(self):
        chip = self.chips(self.sol, empresa=self.empresa_norte.pk, ordenar="cliente", direccion="asc")[0]
        self.assertIn("ordenar=cliente", chip["quitar"])
        self.assertIn("direccion=asc", chip["quitar"])

    def test_el_rango_de_fechas_es_un_solo_chip(self):
        chips = self.chips(self.sol, creado_desde="2026-10-01", creado_hasta="2026-10-31")
        self.assertEqual([c["texto"] for c in chips], ["Carga: 01/10/2026 a 31/10/2026"])
        self.assertEqual(chips[0]["quitar"], reverse(HOME))

    def test_el_chip_de_busqueda_por_texto(self):
        self.assertEqual(self.chips(self.admin, cliente="mixta")[0]["texto"], "Empresa que contiene «mixta»")

    def test_sin_asignar_tiene_chip(self):
        self.assertEqual(self.chips(self.admin, implementador="sin")[0]["texto"], "Implementador: Sin asignar")


class PaginaTests(BaseFiltros):
    def test_el_formulario_es_un_get_y_conserva_el_orden(self):
        pagina = self.listado(self.sol, ordenar="cliente", direccion="asc").content.decode()
        self.assertIn('<form method="get" class="filtros-form" id="form-filtros">', pagina)
        self.assertIn('<input type="hidden" name="ordenar" value="cliente">', pagina)
        self.assertIn('<input type="hidden" name="direccion" value="asc">', pagina)

    def test_lo_marcado_vuelve_tildado(self):
        pagina = self.listado(
            self.sol, implementador=self.ana.pk, empresa=self.empresa_norte.pk, estado="a_completar",
        ).content.decode()
        self.assertIn(f'name="implementador" value="{self.ana.pk}" data-del-grupo checked', pagina)
        self.assertIn(f'name="empresa" value="{self.empresa_norte.pk}" checked', pagina)
        self.assertIn('name="estado" value="a_completar" checked', pagina)
        self.assertNotIn(f'name="implementador" value="{self.beto.pk}" data-del-grupo checked', pagina)

    def test_las_fechas_vuelven_cargadas(self):
        pagina = self.listado(self.sol, fecha_impl_desde="2026-11-01").content.decode()
        self.assertIn('name="fecha_impl_desde" id="fecha_impl_desde" value="2026-11-01"', pagina)

    def test_carga_el_script_y_el_estilo_de_los_filtros(self):
        pagina = self.listado(self.sol).content.decode()
        self.assertIn("panel_filtros.js", pagina)
        self.assertIn("panel_filtros.css", pagina)

    def test_el_orden_por_columna_conserva_los_filtros(self):
        enlace = self.listado(self.sol, empresa=self.empresa_norte.pk).context["sort_links"]["cliente"]["url"]
        self.assertIn(f"empresa={self.empresa_norte.pk}", enlace)
