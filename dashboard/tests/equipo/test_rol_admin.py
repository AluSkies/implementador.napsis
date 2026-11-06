"""Cuentas del equipo: alta, cambio de rol (el de Admin incluido), guardas y registro de cambios."""

from django.contrib.auth.models import User
from django.urls import reverse

from automatizacion.actores import ADMIN, IMPLEMENTADOR, SUPERVISOR, Actor
from automatizacion.models import EventoInmutable
from clients.models import Implementacion
from dashboard import permisos
from dashboard import services as cuentas
from dashboard.models import EventoDeCuenta, Membresia
from dashboard.tests.base import BaseGrupos

LISTA = "dashboard:implementadores"
ALTA = {"username": "lucia2", "first_name": "Lucía", "last_name": "Ramos", "email": "l@napsislatam.com"}
DATOS = {"accion": "guardar", "first_name": "Ana", "last_name": "Paz", "email": "a@napsislatam.com"}


class BaseCuentas(BaseGrupos):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def detalle(self, usuario):
        return reverse("dashboard:implementador_detalle", kwargs={"pk": usuario.pk})

    def cambiar_rol(self, usuario, rol, **extra):
        return self.client.post(self.detalle(usuario), {**DATOS, "rol": rol, **extra}, follow=True)

    def eventos(self, accion=None):
        consulta = EventoDeCuenta.objects.all()
        return consulta.filter(accion=accion) if accion else consulta


class AltaDeCuentasTests(BaseCuentas):
    def alta(self, **extra):
        return self.client.post(reverse(LISTA), {**ALTA, **extra})

    def test_el_admin_crea_un_supervisor(self):
        self.alta(rol="supervisor")
        usuario = User.objects.get(username="lucia2")
        self.assertTrue(usuario.is_staff and not usuario.is_superuser)
        self.assertEqual(Actor.de_usuario(usuario).tipo, SUPERVISOR)
        self.assertTrue(permisos.puede_asignar(usuario))

    def test_el_admin_crea_un_implementador_comun(self):
        self.alta(rol="implementador")
        usuario = User.objects.get(username="lucia2")
        self.assertEqual(Actor.de_usuario(usuario).tipo, IMPLEMENTADOR)
        self.assertFalse(permisos.puede_asignar(usuario))

    def test_el_admin_crea_otro_admin(self):
        self.alta(rol="admin")
        usuario = User.objects.get(username="lucia2")
        self.assertTrue(usuario.is_staff and usuario.is_superuser)
        self.assertEqual(Actor.de_usuario(usuario).tipo, ADMIN)
        self.assertEqual(permisos.implementaciones_visibles(usuario).count(), Implementacion.objects.count())

    def test_el_rol_es_obligatorio_y_solo_admite_los_tres(self):
        for rol in ({}, {"rol": "dios"}, {"rol": "superusuario"}):
            self.alta(**rol)
            self.assertFalse(User.objects.filter(username="lucia2").exists(), rol)

    def test_un_campo_de_mas_no_da_privilegios(self):
        self.alta(rol="implementador", is_superuser="on")
        self.assertFalse(User.objects.get(username="lucia2").is_superuser)

    def test_el_alta_deja_un_evento(self):
        self.alta(rol="supervisor")
        evento = self.eventos("cuenta.creada").get()
        self.assertEqual((evento.actor, evento.sujeto, evento.datos), ("admin_t", "lucia2", {"rol": "supervisor"}))


class DarRolAdminTests(BaseCuentas):
    def test_el_admin_le_da_el_rol_a_un_implementador(self):
        self.cambiar_rol(self.carla, "admin")
        self.carla.refresh_from_db()
        self.assertTrue(self.carla.is_superuser)
        self.assertEqual(Actor.de_usuario(self.carla).tipo, ADMIN)

    def test_quien_recibe_el_rol_ve_todo_y_administra_las_cuentas(self):
        self.cambiar_rol(self.carla, "admin")
        self.client.force_login(self.carla)
        self.assertEqual(self.client.get(reverse(LISTA)).status_code, 200)
        self.assertEqual(self.client.get(self.url(self.sin_asignar)).status_code, 200)

    def test_el_cambio_de_rol_deja_un_evento_con_el_antes_y_el_despues(self):
        self.cambiar_rol(self.carla, "admin")
        evento = self.eventos("cuenta.rol_cambiado").get()
        self.assertEqual((evento.actor, evento.sujeto), ("admin_t", "carla"))
        self.assertEqual((evento.datos["de"], evento.datos["a"]), ("implementador", "admin"))

    def test_sin_cambios_de_rol_no_hay_evento(self):
        self.cambiar_rol(self.carla, "implementador")
        self.assertFalse(self.eventos("cuenta.rol_cambiado").exists())

    def test_un_admin_puede_dejar_de_serlo_si_queda_otro(self):
        otro = User.objects.create_user("admin_2", password="x", is_staff=True, is_superuser=True)
        self.cambiar_rol(otro, "implementador")
        otro.refresh_from_db()
        self.assertFalse(otro.is_superuser)
        self.assertEqual(Actor.de_usuario(otro).tipo, IMPLEMENTADOR)

    def test_un_supervisor_o_un_implementador_no_otorga_el_rol(self):
        for quien in (self.sol, self.carla):
            self.client.force_login(quien)
            respuesta = self.client.post(self.detalle(self.ana), {**DATOS, "rol": "admin"})
            self.assertEqual(respuesta.status_code, 403)
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.is_superuser)

    def test_nadie_puede_cambiarse_su_propio_rol(self):
        otro = User.objects.create_user("admin_2", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(otro)
        self.client.post(self.detalle(otro), {**DATOS, "rol": "implementador"})
        otro.refresh_from_db()
        self.assertTrue(otro.is_superuser)
        pagina = self.client.get(self.detalle(otro))
        self.assertTrue(pagina.context["form"].fields["rol"].disabled)

    def test_el_servicio_tampoco_deja_cambiar_el_propio_rol(self):
        with self.assertRaises(cuentas.CambioNoPermitido):
            cuentas.asignar_rol(self.admin, cuentas.ROL_IMPLEMENTADOR, por=self.admin)

    def test_nunca_se_deja_al_portal_sin_admin(self):
        with self.assertRaisesMessage(cuentas.CambioNoPermitido, "al menos un admin"):
            cuentas.asignar_rol(self.admin, cuentas.ROL_SUPERVISOR, por=self.sol)
        with self.assertRaisesMessage(cuentas.CambioNoPermitido, "al menos un admin"):
            cuentas.dar_de_baja(self.admin, por=self.sol)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser and self.admin.is_active)

    def test_un_admin_dado_de_baja_no_cuenta_como_admin_activo(self):
        otro = User.objects.create_user("admin_2", password="x", is_staff=True, is_superuser=True, is_active=False)
        self.assertEqual(list(cuentas.admins_activos()), [self.admin])
        with self.assertRaises(cuentas.CambioNoPermitido):
            cuentas.dar_de_baja(self.admin, por=otro)

    def test_no_se_puede_dar_de_baja_a_uno_mismo(self):
        otro = User.objects.create_user("admin_2", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(otro)
        respuesta = self.client.post(self.detalle(otro), {"accion": "dar_de_baja"}, follow=True)
        otro.refresh_from_db()
        self.assertTrue(otro.is_active)
        self.assertContains(respuesta, "No podés darte de baja a vos mismo")

    def test_un_admin_da_de_baja_a_otro(self):
        otro = User.objects.create_user("admin_2", password="x", is_staff=True, is_superuser=True)
        self.client.post(self.detalle(otro), {"accion": "dar_de_baja"})
        otro.refresh_from_db()
        self.assertFalse(otro.is_active)


class RolesYGruposTests(BaseCuentas):
    def test_el_cambio_de_rol_de_un_supervisor_con_grupos_se_frena(self):
        respuesta = self.cambiar_rol(self.sol, "implementador")
        self.assertContains(respuesta, "Tiene grupos a cargo")
        self.assertContains(self.cambiar_rol(self.sol, "admin"), "Tiene grupos a cargo")
        self.assertEqual(cuentas.rol_de(User.objects.get(pk=self.sol.pk)), "supervisor")

    def test_con_los_grupos_reasignados_si_se_puede(self):
        self.norte.supervisor = self.lucia
        self.norte.save()
        self.cambiar_rol(self.sol, "implementador")
        self.assertEqual(cuentas.rol_de(User.objects.get(pk=self.sol.pk)), "implementador")

    def test_promover_a_un_integrante_lo_saca_del_grupo_y_avisa(self):
        respuesta = self.cambiar_rol(self.ana, "supervisor")
        self.assertFalse(Membresia.objects.filter(usuario=self.ana).exists())
        self.assertContains(respuesta, "salió del grupo «Norte»")
        self.assertEqual(self.eventos("cuenta.rol_cambiado").get().datos["sale_del_grupo"], "Norte")

    def test_al_pasar_a_admin_tambien_sale_del_grupo(self):
        self.cambiar_rol(self.ana, "admin")
        self.assertFalse(Membresia.objects.filter(usuario=self.ana).exists())

    def test_la_lista_muestra_el_rol_y_el_grupo_de_cada_cuenta(self):
        pagina = self.client.get(reverse(LISTA)).content.decode()
        fila = lambda usuario: [f for f in pagina.split("<tr>") if f"<strong>{usuario}</strong>" in f][0]
        self.assertIn("Admin", fila("admin_t"))
        self.assertIn("Supervisor", fila("sol"))
        self.assertIn("A cargo de Norte", fila("sol"))
        self.assertIn("Implementador", fila("ana"))
        self.assertIn("Norte", fila("ana"))

    def test_el_encabezado_muestra_el_rol(self):
        self.client.force_login(self.sol)
        self.assertContains(self.client.get(reverse("dashboard:home")), "(Supervisor)")
        self.client.force_login(self.ana)
        self.assertContains(self.client.get(reverse("dashboard:home")), "(Implementador)")

    def test_un_supervisor_no_administra_cuentas_ni_grupos(self):
        self.client.force_login(self.sol)
        for nombre in (LISTA, "dashboard:grupos"):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403)


class RegistroDeCuentasTests(BaseCuentas):
    def test_baja_reactivacion_y_reinicio_de_clave_dejan_evento(self):
        self.client.post(self.detalle(self.carla), {"accion": "dar_de_baja"})
        self.client.post(self.detalle(self.carla), {"accion": "reactivar"})
        self.client.post(self.detalle(self.carla), {"accion": "resetear_password"})
        acciones = list(self.eventos().filter(sujeto="carla").order_by("id").values_list("accion", flat=True))
        self.assertEqual(acciones, ["cuenta.baja", "cuenta.reactivada", "cuenta.password_reiniciada"])

    def test_el_evento_no_guarda_la_contrasena(self):
        self.client.post(self.detalle(self.carla), {"accion": "resetear_password"})
        evento = self.eventos("cuenta.password_reiniciada").get()
        self.assertEqual(evento.datos, {})

    def test_el_registro_es_de_solo_agregado(self):
        self.client.post(self.detalle(self.carla), {"accion": "dar_de_baja"})
        evento = self.eventos().get()
        evento.sujeto = "otro"
        with self.assertRaises(EventoInmutable):
            evento.save()
        with self.assertRaises(EventoInmutable):
            evento.delete()
        with self.assertRaises(EventoInmutable):
            EventoDeCuenta.objects.all().delete()
        with self.assertRaises(EventoInmutable):
            EventoDeCuenta.objects.all().update(sujeto="x")

    def test_sobrevive_aunque_se_borre_la_cuenta(self):
        self.client.post(self.detalle(self.carla), {"accion": "dar_de_baja"})
        self.carla.delete()
        self.assertEqual(self.eventos("cuenta.baja").get().sujeto, "carla")
