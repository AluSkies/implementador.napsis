"""Grupos de trabajo: los arma el Admin; definen qué ve cada supervisor."""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse

from dashboard import services as cuentas
from dashboard.models import EventoDeCuenta, GrupoDeTrabajo, Membresia
from dashboard.tests.base import BaseGrupos

LISTA = "dashboard:grupos"


class BaseABM(BaseGrupos):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def detalle(self, grupo):
        return reverse("dashboard:grupo_detalle", kwargs={"pk": grupo.pk})

    def guardar(self, grupo, **datos):
        base = {"accion": "guardar", "nombre": grupo.nombre, "supervisor": grupo.supervisor_id,
                "integrantes": list(grupo.membresias.values_list("usuario_id", flat=True))}
        return self.client.post(self.detalle(grupo), {**base, **datos}, follow=True)

    def integrantes(self, grupo):
        return set(grupo.membresias.values_list("usuario__username", flat=True))

    def eventos(self, accion):
        return EventoDeCuenta.objects.filter(accion=accion)


class QuienAdministraTests(BaseABM):
    def test_solo_el_admin_entra(self):
        for usuario in (self.sol, self.ana):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse(LISTA)).status_code, 403)
            self.assertEqual(self.client.get(self.detalle(self.norte)).status_code, 403)
            self.assertEqual(self.client.post(reverse(LISTA), {"nombre": "X", "supervisor": self.sol.pk}).status_code, 403)
            self.assertEqual(self.client.post(self.detalle(self.norte), {"accion": "borrar"}).status_code, 403)
        self.assertTrue(GrupoDeTrabajo.objects.filter(pk=self.norte.pk).exists())

    def test_el_anonimo_va_al_login(self):
        self.client.logout()
        self.assertIn(reverse("login"), self.client.get(reverse(LISTA)).url)

    def test_la_lista_muestra_supervisor_integrantes_e_implementaciones(self):
        grupos = {g.nombre: g for g in self.client.get(reverse(LISTA)).context["grupos"]}
        self.assertEqual((grupos["Norte"].integrantes, grupos["Norte"].implementaciones), (2, 3))
        self.assertEqual((grupos["Sur"].integrantes, grupos["Sur"].implementaciones), (1, 2))
        self.assertContains(self.client.get(reverse(LISTA)), "Sol Vega")


class AltaDeGruposTests(BaseABM):
    def crear(self, **datos):
        base = {"nombre": "Oeste", "supervisor": self.sol.pk, "integrantes": [self.carla.pk]}
        return self.client.post(reverse(LISTA), {**base, **datos}, follow=True)

    def test_el_admin_crea_un_grupo_con_su_supervisor_e_integrantes(self):
        self.crear()
        grupo = GrupoDeTrabajo.objects.get(nombre="Oeste")
        self.assertEqual((grupo.supervisor, self.integrantes(grupo)), (self.sol, {"carla"}))

    def test_el_supervisor_pasa_a_ver_lo_del_nuevo_integrante(self):
        self.crear()
        self.assertIn(self.de_carla.pk, self.pks_en_el_listado(self.sol))

    def test_el_alta_deja_un_evento(self):
        self.crear()
        evento = self.eventos("grupo.creado").get()
        self.assertEqual((evento.actor, evento.sujeto), ("admin_t", "Oeste"))
        self.assertEqual((evento.datos["supervisor"], evento.datos["integrantes"]), ("sol", ["carla"]))

    def test_un_grupo_puede_empezar_vacio(self):
        self.crear(integrantes=[])
        self.assertEqual(GrupoDeTrabajo.objects.get(nombre="Oeste").membresias.count(), 0)

    def test_el_nombre_no_se_repite_ni_cambiando_mayusculas(self):
        respuesta = self.crear(nombre="norte")
        self.assertContains(respuesta, "Ya hay un grupo con ese nombre")
        self.assertEqual(GrupoDeTrabajo.objects.count(), 2)

    def test_el_supervisor_tiene_que_tener_ese_rol(self):
        for no_supervisor in (self.ana, self.admin, self.carla):
            self.crear(supervisor=no_supervisor.pk)
        self.assertFalse(GrupoDeTrabajo.objects.filter(nombre="Oeste").exists())

    def test_un_supervisor_dado_de_baja_no_se_ofrece(self):
        self.lucia.is_active = False
        self.lucia.save()
        self.crear(supervisor=self.lucia.pk)
        self.assertFalse(GrupoDeTrabajo.objects.filter(nombre="Oeste").exists())

    def test_los_integrantes_tienen_que_ser_implementadores(self):
        for no_implementador in (self.sol, self.admin):
            self.crear(integrantes=[no_implementador.pk])
        self.assertFalse(GrupoDeTrabajo.objects.filter(nombre="Oeste").exists())

    def test_un_implementador_en_otro_grupo_se_mueve_y_queda_registrado(self):
        self.crear(integrantes=[self.ana.pk])
        self.assertEqual(self.integrantes(GrupoDeTrabajo.objects.get(nombre="Oeste")), {"ana"})
        self.assertEqual(self.integrantes(self.norte), {"beto"})
        self.assertEqual(self.eventos("grupo.creado").get().datos["vienen_de"], {"ana": "Norte"})
        self.assertEqual(Membresia.objects.filter(usuario=self.ana).count(), 1)

    def test_los_integrantes_van_en_una_tabla_con_nombre_grupo_y_estado(self):
        respuesta = self.client.get(reverse(LISTA))
        filas = {f["nombre"]: f for f in respuesta.context["form"].filas_de_integrantes()}
        self.assertEqual(set(filas), {"Ana Paz", "Beto Ruiz", "Diego Sosa", "Carla Gómez"})
        self.assertEqual((filas["Ana Paz"]["grupo"], filas["Diego Sosa"]["grupo"], filas["Carla Gómez"]["grupo"]), ("Norte", "Sur", ""))
        pagina = respuesta.content.decode()
        self.assertIn("<th>Nombre</th><th>Grupo</th><th>Estado</th>", pagina)
        self.assertNotIn("hoy en", pagina)  # nada de frases: el grupo es solo su nombre en la columna Grupo
        self.assertNotIn("(ana)", pagina)

    def test_nadie_viene_tildado_en_un_grupo_nuevo(self):
        filas = self.client.get(reverse(LISTA)).context["form"].filas_de_integrantes()
        self.assertFalse(any(f["marcado"] for f in filas))

    def test_si_el_alta_vuelve_con_un_error_no_se_pierde_lo_tildado(self):
        respuesta = self.crear(nombre="norte", integrantes=[self.carla.pk, self.diego.pk])
        tildados = {f["nombre"] for f in respuesta.context["form"].filas_de_integrantes() if f["marcado"]}
        self.assertEqual(tildados, {"Carla Gómez", "Diego Sosa"})
        self.assertContains(respuesta, f'value="{self.carla.pk}" id="integrante-{self.carla.pk}" checked')

    def test_el_supervisor_se_elige_con_nombre_y_sin_texto_en_ingles(self):
        pagina = self.client.get(reverse(LISTA)).content.decode()
        self.assertIn("Elegir supervisor", pagina)
        self.assertNotIn("Select an option", pagina)


class EdicionDeGruposTests(BaseABM):
    def test_se_renombra_y_se_cambia_el_supervisor(self):
        self.guardar(self.norte, nombre="Norte 2", supervisor=self.lucia.pk)
        self.norte.refresh_from_db()
        self.assertEqual((self.norte.nombre, self.norte.supervisor), ("Norte 2", self.lucia))
        self.assertEqual(self.eventos("grupo.modificado").get().datos["supervisor"], {"antes": "sol", "despues": "lucia"})

    def test_al_cambiar_de_supervisor_cambia_quien_ve(self):
        self.guardar(self.norte, supervisor=self.lucia.pk)
        self.assertIn(self.de_ana.pk, self.pks_en_el_listado(self.lucia))
        self.assertNotIn(self.de_ana.pk, self.pks_en_el_listado(self.sol))

    def test_la_tabla_de_un_grupo_pone_primero_a_sus_integrantes_y_marca_las_bajas(self):
        self.beto.is_active = False
        self.beto.save()
        filas = self.client.get(self.detalle(self.norte)).context["form"].filas_de_integrantes()
        self.assertEqual([(f["nombre"], f["marcado"], f["de_baja"]) for f in filas], [
            ("Ana Paz", True, False), ("Beto Ruiz", True, True), ("Carla Gómez", False, False), ("Diego Sosa", False, False),
        ])
        self.assertContains(self.client.get(self.detalle(self.norte)), "De baja")

    def test_se_suma_un_integrante(self):
        self.guardar(self.norte, integrantes=[self.ana.pk, self.beto.pk, self.carla.pk])
        self.assertEqual(self.integrantes(self.norte), {"ana", "beto", "carla"})
        self.assertEqual(self.eventos("grupo.modificado").get().datos["entran"], ["carla"])

    def test_sacar_a_un_integrante_avisa_cuantas_implementaciones_deja_de_ver_el_supervisor(self):
        respuesta = self.guardar(self.norte, integrantes=[self.beto.pk])
        self.assertEqual(self.integrantes(self.norte), {"beto"})
        self.assertContains(respuesta, "2 implementación(es) dejó(aron) de verse")
        self.assertNotIn(self.de_ana.pk, self.pks_en_el_listado(self.sol))
        self.assertEqual(self.eventos("grupo.modificado").get().datos["salen"], ["ana"])

    def test_el_admin_sigue_viendo_lo_de_quien_salio_y_puede_reasignarlo(self):
        self.guardar(self.norte, integrantes=[self.beto.pk])
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url(self.de_ana)).status_code, 200)
        self.client.post(self.url(self.de_ana), {"accion": "reasignar", "implementador_id": self.beto.pk})
        self.de_ana.refresh_from_db()
        self.assertEqual(self.de_ana.implementador_asignado, self.beto)  # vuelve a la vista del supervisor
        self.assertIn(self.de_ana.pk, self.pks_en_el_listado(self.sol))

    def test_sin_cambios_no_hay_evento(self):
        self.guardar(self.norte)
        self.assertFalse(self.eventos("grupo.modificado").exists())

    def test_mover_a_alguien_de_otro_grupo_lo_saca_del_anterior(self):
        self.guardar(self.sur, integrantes=[self.diego.pk, self.ana.pk])
        self.assertEqual(self.integrantes(self.sur), {"diego", "ana"})
        self.assertEqual(self.integrantes(self.norte), {"beto"})
        self.assertEqual(self.eventos("grupo.modificado").get().datos["vienen_de"], {"ana": "Norte"})

    def test_el_supervisor_actual_sigue_valiendo_aunque_este_de_baja(self):
        self.sol.is_active = False
        self.sol.save()
        respuesta = self.guardar(self.norte, nombre="Norte 3")
        self.norte.refresh_from_db()
        self.assertEqual((self.norte.nombre, self.norte.supervisor), ("Norte 3", self.sol))
        self.assertNotContains(respuesta, "errorlist")

    def test_el_nombre_propio_no_cuenta_como_repetido(self):
        respuesta = self.guardar(self.norte, nombre="NORTE")
        self.norte.refresh_from_db()
        self.assertEqual(self.norte.nombre, "NORTE")
        self.assertNotContains(respuesta, "Ya hay un grupo")


class BajaDeGruposTests(BaseABM):
    def borrar(self, grupo):
        return self.client.post(self.detalle(grupo), {"accion": "borrar"}, follow=True)

    def test_borrar_un_grupo_conserva_las_cuentas_y_sus_implementaciones(self):
        respuesta = self.borrar(self.norte)
        self.assertFalse(GrupoDeTrabajo.objects.filter(nombre="Norte").exists())
        self.assertEqual(User.objects.filter(username__in=["sol", "ana", "beto"]).count(), 3)
        self.assertFalse(Membresia.objects.filter(usuario__in=[self.ana, self.beto]).exists())
        self.assertContains(respuesta, "3 implementación(es) dejó(aron) de verse")

    def test_el_supervisor_deja_de_ver_las_de_los_integrantes_y_conserva_las_suyas(self):
        self.borrar(self.norte)
        self.assertEqual(self.pks_en_el_listado(self.sol), {self.de_sol.pk})

    def test_el_borrado_deja_un_evento_con_lo_que_habia(self):
        self.borrar(self.norte)
        evento = self.eventos("grupo.borrado").get()
        self.assertEqual(evento.sujeto, "Norte")
        self.assertEqual((evento.datos["supervisor"], evento.datos["integrantes"]), ("sol", ["ana", "beto"]))
        self.assertEqual(evento.datos["implementaciones_afectadas"], 3)

    def test_un_grupo_vacio_se_borra_sin_aviso_de_implementaciones(self):
        grupo = cuentas.crear_grupo("Vacío", self.sol, [])
        self.assertNotContains(self.borrar(grupo), "dejó(aron) de verse")


class IntegridadTests(BaseABM):
    def test_un_implementador_no_puede_estar_en_dos_grupos(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membresia.objects.create(usuario=self.ana, grupo=self.sur)

    def test_no_se_borra_una_cuenta_que_tiene_grupos_a_cargo(self):
        with self.assertRaises(ProtectedError):
            self.sol.delete()

    def test_borrar_la_cuenta_de_un_integrante_lo_saca_del_grupo(self):
        self.ana.delete()
        self.assertEqual(self.integrantes(self.norte), {"beto"})

    def test_asignables_del_supervisor_es_su_equipo_activo(self):
        self.beto.is_active = False
        self.beto.save()
        self.assertEqual({u.username for u in cuentas.asignables(self.sol)}, {"sol", "ana"})
        self.assertEqual({u.username for u in cuentas.asignables(self.ana)}, {"ana"})
        self.assertEqual(
            {u.username for u in cuentas.asignables(self.admin)}, {"admin_t", "sol", "lucia", "ana", "diego", "carla"},
        )
