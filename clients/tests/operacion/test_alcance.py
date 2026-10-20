"""Alcance del liquidador: grupos de la nómina + personas sueltas (la unión de las dos)."""

import json
from datetime import date

from django.test import SimpleTestCase, TestCase

from automatizacion.actores import Actor
from clients import alcance
from clients.models import AlcancePersona, AlcanceRegla, Cliente, Implementacion, PersonaRol
from employees.models import Empleado
from onboarding.forms import RolFormSet
from onboarding.services import guardar_roles

ANA = Actor.implementador("ana")


class NormalizarTests(SimpleTestCase):
    def test_vacio_es_ve_todo(self):
        for vacio in ("", None, {}, "{}", {"reglas": [], "cuils": []}):
            self.assertEqual(alcance.normalizar(vacio), {})

    def test_acepta_json_o_dict_y_normaliza_los_cuil(self):
        crudo = {"reglas": [{"campo": "puesto", "valor": " OPERARIO "}], "cuils": ["20-11111111-2", "20111111112"]}
        self.assertEqual(alcance.normalizar(json.dumps(crudo)), {
            "reglas": [{"campo": "puesto", "valor": "OPERARIO"}], "cuils": ["20111111112"],
        })

    def test_rechaza_campos_que_no_existen_y_reglas_incompletas(self):
        for mal in ({"reglas": [{"campo": "salario", "valor": "1"}]}, {"reglas": [{"campo": "puesto", "valor": ""}]},
                    {"reglas": ["x"]}, "no es json", [1]):
            with self.assertRaises(ValueError, msg=mal):
                alcance.normalizar(mal)

    def test_supervisor_solo_admite_si_o_no(self):
        self.assertEqual(alcance.normalizar({"reglas": [{"campo": "es_supervisor", "valor": "si"}]})["reglas"][0]["valor"], "SI")
        with self.assertRaises(ValueError):
            alcance.normalizar({"reglas": [{"campo": "es_supervisor", "valor": "tal vez"}]})

    def test_un_cuil_corto_se_rechaza(self):
        with self.assertRaises(ValueError):
            alcance.normalizar({"cuils": ["123"]})

    def test_describe_en_una_frase(self):
        self.assertEqual(alcance.describir({}), "Todos los recibos (sin segmentar)")
        texto = alcance.describir({"reglas": [{"campo": "puesto", "valor": "OPERARIO"}], "cuils": ["1", "2"]})
        self.assertEqual(texto, "Puesto: OPERARIO; 2 personas elegidas una por una")


class AlcanzadosTests(TestCase):
    def setUp(self):
        self.impl = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))
        def emp(cuil, **datos):
            return Empleado.objects.create(implementacion=self.impl, cuil=cuil, nombre="N", apellido=cuil, fecha_ingreso=date(2020, 1, 1), **datos)
        self.op = emp("20111111112", puesto="Operario", sector="Planta")
        self.sup = emp("20222222223", puesto="Supervisor", sector="Planta", es_supervisor=True)
        self.ger = emp("20333333334", puesto="Gerente", gerencia="Finanzas")
        self.adm = emp("20444444445", puesto="Administrativo", sector="Oficina")

    def cuils(self, valor):
        return set(alcance.alcanzados(self.impl, valor).values_list("cuil", flat=True))

    def test_sin_nada_llega_a_todos(self):
        self.assertEqual(len(self.cuils({})), 4)

    def test_un_grupo_por_puesto_ignora_mayusculas(self):
        self.assertEqual(self.cuils({"reglas": [{"campo": "puesto", "valor": "OPERARIO"}]}), {self.op.cuil})

    def test_el_sector_y_los_supervisores(self):
        regla = {"reglas": [{"campo": "sector", "valor": "Planta"}]}
        self.assertEqual(self.cuils(regla), {self.op.cuil, self.sup.cuil})
        self.assertEqual(self.cuils({"reglas": [{"campo": "es_supervisor", "valor": "SI"}]}), {self.sup.cuil})
        self.assertEqual(len(self.cuils({"reglas": [{"campo": "es_supervisor", "valor": "NO"}]})), 3)

    def test_es_la_union_de_los_grupos_y_las_personas_sueltas(self):
        valor = {"reglas": [{"campo": "puesto", "valor": "Operario"}], "cuils": [self.ger.cuil]}
        self.assertEqual(self.cuils(valor), {self.op.cuil, self.ger.cuil})

    def test_un_cuil_que_ya_no_esta_en_la_nomina_no_suma_a_nadie(self):
        self.assertEqual(self.cuils({"cuils": ["20999999999"]}), set())

    def test_las_opciones_salen_de_la_nomina(self):
        opciones = alcance.opciones_de_la_nomina(self.impl)
        self.assertEqual(opciones["puesto"], ["Administrativo", "Gerente", "Operario", "Supervisor"])
        self.assertEqual(opciones["gerencia"], ["Finanzas"])


class GuardarRolesTests(TestCase):
    def setUp(self):
        self.impl = Implementacion.objects.create(cliente=Cliente.objects.create(nombre="A"))

    def enviar(self, *filas, con_alcance=True):
        datos = {"form-TOTAL_FORMS": str(len(filas)), "form-INITIAL_FORMS": "0", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "10"}
        for i, (rol, nombre, cuil, valor) in enumerate(filas):
            datos.update({f"form-{i}-rol": rol, f"form-{i}-apellido_nombre": nombre, f"form-{i}-cuil": cuil})
            if con_alcance:
                datos[f"form-{i}-alcance"] = json.dumps(valor) if valor else ""
        formset = RolFormSet(datos)
        self.assertTrue(formset.is_valid(), formset.errors)
        guardar_roles(self.impl, formset, ANA)

    def liquidador(self):
        return self.impl.roles.get(rol="liquidador")

    def test_guarda_el_alcance_en_tablas_propias(self):
        valor = {"reglas": [{"campo": "puesto", "valor": "Operario"}], "cuils": ["20333333334"]}
        self.enviar(("liquidador", "Ruiz, Luis", "20222222223", valor))
        self.assertEqual(alcance.alcance_de(self.liquidador()), valor)
        self.assertEqual((AlcanceRegla.objects.count(), AlcancePersona.objects.count()), (1, 1))

    def test_solo_el_liquidador_tiene_alcance(self):
        self.enviar(("apoderado", "Gómez, Ana", "20111111112", {"cuils": ["20333333334"]}))
        self.assertEqual(AlcancePersona.objects.count(), 0)

    def test_la_misma_persona_se_actualiza_en_el_lugar_y_conserva_su_alcance(self):
        self.enviar(("liquidador", "Ruiz, Luis", "20222222223", {"cuils": ["20333333334"]}))
        antes = self.liquidador().pk
        self.enviar(("liquidador", "Ruiz, Luis Alberto", "20222222223", None), con_alcance=False)
        self.assertEqual(self.liquidador().pk, antes)
        self.assertEqual(self.liquidador().apellido_nombre, "Ruiz, Luis Alberto")
        self.assertEqual(alcance.alcance_de(self.liquidador()), {"reglas": [], "cuils": ["20333333334"]})

    def test_un_formulario_que_manda_el_campo_vacio_lo_borra(self):
        self.enviar(("liquidador", "Ruiz, Luis", "20222222223", {"cuils": ["20333333334"]}))
        self.enviar(("liquidador", "Ruiz, Luis", "20222222223", None))
        self.assertEqual(alcance.alcance_de(self.liquidador()), {})

    def test_si_el_equipo_dejo_sin_segmentar_el_alcance_no_se_guarda(self):
        self.impl.segmentacion_editable = False
        self.impl.save()
        self.enviar(("liquidador", "Ruiz, Luis", "20222222223", {"cuils": ["20333333334"]}))
        self.assertEqual(alcance.alcance_de(self.liquidador()), {})

    def test_quitar_a_la_persona_borra_su_alcance(self):
        self.enviar(("liquidador", "Ruiz, Luis", "20222222223", {"cuils": ["20333333334"]}))
        self.enviar(("apoderado", "Gómez, Ana", "20111111112", None))
        self.assertEqual((PersonaRol.objects.filter(rol="liquidador").count(), AlcancePersona.objects.count()), (0, 0))
