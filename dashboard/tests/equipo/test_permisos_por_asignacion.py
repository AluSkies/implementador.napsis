"""Quién puede ver y quién puede actuar sobre cada implementación.

- El implementador ve todas, pero solo actúa sobre las que tiene asignadas.
- El supervisor y el admin actúan sobre todas, y solo ellos las asignan.
- El admin crea las cuentas de supervisor (y puede cambiar el rol de cada cuenta).
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from automatizacion.actores import GRUPO_SUPERVISOR, SUPERVISOR, IMPLEMENTADOR, ADMIN, Actor
from automatizacion.models import EventoImplementacion
from clients.models import ComentarioInterno, Cliente, Implementacion
from dashboard import permisos
from dashboard.tests.base import crear_supervisor


class BaseEquipo(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin_t", password="x", is_staff=True, is_superuser=True)
        self.super = crear_supervisor("sol")
        self.ana = User.objects.create_user("ana", password="x", is_staff=True, first_name="Ana")
        self.beto = User.objects.create_user("beto", password="x", is_staff=True, first_name="Beto")
        self.cliente = Cliente.objects.create(nombre="Empresa A")
        self.de_ana = Implementacion.objects.create(cliente=self.cliente, implementador_asignado=self.ana)
        self.sin_asignar = Implementacion.objects.create(cliente=self.cliente)

    def url(self, implementacion):
        return reverse("dashboard:implementacion_detalle", kwargs={"pk": implementacion.pk})

    def comentar(self, usuario, implementacion, texto="una nota"):
        self.client.force_login(usuario)
        return self.client.post(self.url(implementacion), {"accion": "agregar_comentario", "texto": texto})

    def comentarios(self, implementacion):
        return ComentarioInterno.objects.filter(implementacion=implementacion).count()


class ActorTests(BaseEquipo):
    def test_el_tipo_de_actor_sigue_al_rol(self):
        self.assertEqual(Actor.de_usuario(self.admin).tipo, ADMIN)
        self.assertEqual(Actor.de_usuario(self.super).tipo, SUPERVISOR)
        self.assertEqual(Actor.de_usuario(self.ana).tipo, IMPLEMENTADOR)

    def test_el_supervisor_es_del_equipo(self):
        self.assertTrue(Actor.de_usuario(self.super).es_del_equipo)

    def test_pertenecer_al_grupo_no_alcanza_si_no_es_staff(self):
        cliente = User.objects.create_user("cli", password="x")
        cliente.groups.add(Group.objects.get(name=GRUPO_SUPERVISOR))
        self.assertFalse(permisos.puede_asignar(cliente))


class VerTodasTests(BaseEquipo):
    def test_el_implementador_ve_las_de_los_demas(self):
        self.client.force_login(self.beto)
        self.assertEqual(self.client.get(self.url(self.de_ana)).status_code, 200)
        self.assertEqual(self.client.get(self.url(self.sin_asignar)).status_code, 200)
        listado = self.client.get(reverse("dashboard:home"))
        self.assertEqual(len(listado.context["implementaciones"]), 2)

    def test_la_ficha_ajena_se_ve_en_solo_lectura(self):
        self.client.force_login(self.beto)
        pagina = self.client.get(self.url(self.de_ana)).content.decode()
        self.assertIn("Solo lectura", pagina)
        self.assertIn('class="solo-lectura"', pagina)

    def test_la_propia_no_tiene_el_aviso(self):
        self.client.force_login(self.ana)
        pagina = self.client.get(self.url(self.de_ana)).content.decode()
        self.assertNotIn("Solo lectura", pagina)
        self.assertNotIn('class="solo-lectura"', pagina)


class AccionarTests(BaseEquipo):
    def test_el_implementador_actua_sobre_la_suya(self):
        respuesta = self.comentar(self.ana, self.de_ana)
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.comentarios(self.de_ana), 1)

    def test_el_implementador_no_actua_sobre_la_de_otro_ni_sobre_una_sin_asignar(self):
        for implementacion in (self.de_ana, self.sin_asignar):
            self.assertEqual(self.comentar(self.beto, implementacion).status_code, 403)
            self.assertEqual(self.comentarios(implementacion), 0)

    def test_el_supervisor_y_el_admin_actuan_sobre_todas(self):
        for usuario in (self.super, self.admin):
            for implementacion in (self.de_ana, self.sin_asignar):
                self.assertEqual(self.comentar(usuario, implementacion).status_code, 302)
        self.assertEqual(self.comentarios(self.de_ana) + self.comentarios(self.sin_asignar), 4)

    def test_cualquier_accion_de_la_ficha_esta_protegida(self):
        self.client.force_login(self.beto)
        for accion in ("actualizar_datos", "actualizar_roles", "anular", "aprobar_para_configurar", "importar_empleados"):
            self.assertEqual(self.client.post(self.url(self.de_ana), {"accion": accion}).status_code, 403, accion)

    def test_al_reasignarla_cambia_quien_puede_actuar(self):
        self.client.force_login(self.super)
        self.client.post(self.url(self.de_ana), {"accion": "reasignar", "implementador_id": self.beto.pk})
        self.assertEqual(self.comentar(self.beto, self.de_ana).status_code, 302)
        self.assertEqual(self.comentar(self.ana, self.de_ana).status_code, 403)


class AsignarTests(BaseEquipo):
    def reasignar(self, usuario, implementacion, a):
        self.client.force_login(usuario)
        return self.client.post(self.url(implementacion), {"accion": "reasignar", "implementador_id": a.pk})

    def test_el_supervisor_y_el_admin_asignan(self):
        self.assertEqual(self.reasignar(self.super, self.sin_asignar, self.beto).status_code, 302)
        self.sin_asignar.refresh_from_db()
        self.assertEqual(self.sin_asignar.implementador_asignado, self.beto)
        self.reasignar(self.admin, self.sin_asignar, self.ana)
        self.sin_asignar.refresh_from_db()
        self.assertEqual(self.sin_asignar.implementador_asignado, self.ana)

    def test_el_evento_dice_que_lo_hizo_un_supervisor(self):
        self.reasignar(self.super, self.sin_asignar, self.beto)
        evento = EventoImplementacion.objects.get(accion="implementacion.reasignada")
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("supervisor", "sol"))

    def test_el_implementador_no_puede_asignar_ni_la_suya(self):
        self.assertEqual(self.reasignar(self.ana, self.de_ana, self.beto).status_code, 403)
        self.de_ana.refresh_from_db()
        self.assertEqual(self.de_ana.implementador_asignado, self.ana)

    def test_solo_quien_asigna_ve_el_selector_de_reasignar(self):
        self.client.force_login(self.ana)
        self.assertNotIn('value="reasignar"', self.client.get(self.url(self.de_ana)).content.decode())
        self.client.force_login(self.super)
        self.assertIn('value="reasignar"', self.client.get(self.url(self.de_ana)).content.decode())


class AltaTests(BaseEquipo):
    def crear(self, usuario, **extra):
        self.client.force_login(usuario)
        return self.client.post(reverse("dashboard:home"), {
            "accion": "crear_implementacion", "nombre": "Nueva SA", "modulos": [], **extra,
        })

    def test_un_implementador_puede_crear_pero_se_la_asigna_a_si_mismo(self):
        self.crear(self.ana, implementador_id=self.beto.pk)
        self.assertEqual(Implementacion.objects.get(cliente__nombre="Nueva SA").implementador_asignado, self.ana)

    def test_el_supervisor_puede_asignarla_a_otro_al_crearla(self):
        self.crear(self.super, implementador_id=self.beto.pk)
        self.assertEqual(Implementacion.objects.get(cliente__nombre="Nueva SA").implementador_asignado, self.beto)

    def test_el_modal_solo_ofrece_elegir_a_quien_puede_asignar(self):
        self.client.force_login(self.ana)
        self.assertContains(self.client.get(reverse("dashboard:home")), "Se asigna a vos")
        self.client.force_login(self.super)
        self.assertNotContains(self.client.get(reverse("dashboard:home")), "Se asigna a vos")


class FichaDeLaEmpresaTests(BaseEquipo):
    def regenerar(self, usuario):
        self.client.force_login(usuario)
        return self.client.post(
            reverse("dashboard:cliente_detalle", kwargs={"pk": self.cliente.pk}),
            {"accion": "regenerar_acceso", "username": "empresa-a"},
        )

    def test_quien_lleva_alguna_implementacion_de_la_empresa_gestiona_su_acceso(self):
        self.assertEqual(self.regenerar(self.ana).status_code, 302)

    def test_un_implementador_ajeno_a_la_empresa_no(self):
        self.assertEqual(self.regenerar(self.beto).status_code, 403)

    def test_el_supervisor_si(self):
        self.assertEqual(self.regenerar(self.super).status_code, 302)


class DescargasTests(BaseEquipo):
    def test_ver_y_descargar_es_para_todo_el_equipo(self):
        self.client.force_login(self.beto)
        self.assertEqual(self.client.get(reverse("dashboard:descargar_nomina", kwargs={"pk": self.de_ana.pk})).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:exportar")).status_code, 200)


class AbmDelAdminTests(BaseEquipo):
    ALTA = {"username": "lucia", "first_name": "Lucía", "last_name": "Ramos", "email": "l@napsislatam.com"}

    def alta(self, **extra):
        self.client.force_login(self.admin)
        return self.client.post(reverse("dashboard:implementadores"), {**self.ALTA, **extra})

    def test_el_admin_crea_un_supervisor(self):
        self.alta(rol="supervisor")
        usuario = User.objects.get(username="lucia")
        self.assertTrue(usuario.is_staff and not usuario.is_superuser)
        self.assertEqual(Actor.de_usuario(usuario).tipo, SUPERVISOR)
        self.assertTrue(permisos.puede_asignar(usuario))

    def test_el_admin_crea_un_implementador_comun(self):
        self.alta(rol="implementador")
        usuario = User.objects.get(username="lucia")
        self.assertEqual(Actor.de_usuario(usuario).tipo, IMPLEMENTADOR)
        self.assertFalse(permisos.puede_asignar(usuario))

    def test_el_rol_es_obligatorio_y_solo_admite_los_dos(self):
        for rol in ({}, {"rol": "admin"}, {"rol": "dios"}):
            self.alta(**rol)
            self.assertFalse(User.objects.filter(username="lucia").exists(), rol)

    def test_el_admin_cambia_el_rol_de_una_cuenta(self):
        self.client.force_login(self.admin)
        detalle = reverse("dashboard:implementador_detalle", kwargs={"pk": self.ana.pk})
        datos = {"accion": "guardar", "first_name": "Ana", "last_name": "Paz", "email": "a@napsislatam.com"}
        self.client.post(detalle, {**datos, "rol": "supervisor"})
        self.assertEqual(Actor.de_usuario(self.ana).tipo, SUPERVISOR)
        self.client.post(detalle, {**datos, "rol": "implementador"})
        self.assertEqual(Actor.de_usuario(self.ana).tipo, IMPLEMENTADOR)

    def test_la_lista_muestra_el_rol_de_cada_cuenta(self):
        self.client.force_login(self.admin)
        pagina = self.client.get(reverse("dashboard:implementadores")).content.decode()
        fila_sol = [f for f in pagina.split("<tr>") if "<td>sol</td>" in f][0]
        fila_ana = [f for f in pagina.split("<tr>") if "<td>ana</td>" in f][0]
        self.assertIn("Supervisor", fila_sol)
        self.assertIn("Implementador", fila_ana)

    def test_un_supervisor_no_administra_cuentas(self):
        self.client.force_login(self.super)
        self.assertEqual(self.client.get(reverse("dashboard:implementadores")).status_code, 403)

    def test_el_encabezado_muestra_el_rol(self):
        self.client.force_login(self.super)
        self.assertContains(self.client.get(reverse("dashboard:home")), "(Supervisor)")
        self.client.force_login(self.ana)
        self.assertContains(self.client.get(reverse("dashboard:home")), "(Implementador)")
