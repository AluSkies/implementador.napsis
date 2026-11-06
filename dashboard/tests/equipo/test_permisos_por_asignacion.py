"""Quién ve y quién puede actuar sobre cada implementación.

- El implementador ve y actúa solo sobre las que tiene asignadas.
- El supervisor ve las suyas y las de los integrantes de sus grupos, y actúa sobre todas las que ve. No ve las de
  otros supervisores ni las de sus equipos.
- El admin ve y puede todo, incluidas las implementaciones sin asignar.
Escenario compartido: `dashboard.tests.base.BaseGrupos`.
"""

import io
import json
import tempfile

import openpyxl
from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse

from automatizacion.actores import ADMIN, GRUPO_SUPERVISOR, IMPLEMENTADOR, SUPERVISOR, Actor
from automatizacion.models import ConfiguracionCongelada, EventoImplementacion
from clients.models import ComentarioInterno, Implementacion
from dashboard import permisos
from dashboard.models import GrupoDeTrabajo, Membresia
from dashboard.tests.base import BaseGrupos


class BaseEquipo(BaseGrupos):
    def comentar(self, usuario, implementacion, texto="una nota"):
        self.client.force_login(usuario)
        return self.client.post(self.url(implementacion), {"accion": "agregar_comentario", "texto": texto})

    def comentarios(self, implementacion):
        return ComentarioInterno.objects.filter(implementacion=implementacion).count()


class ActorTests(BaseEquipo):
    def test_el_tipo_de_actor_sigue_al_rol(self):
        self.assertEqual(Actor.de_usuario(self.admin).tipo, ADMIN)
        self.assertEqual(Actor.de_usuario(self.sol).tipo, SUPERVISOR)
        self.assertEqual(Actor.de_usuario(self.ana).tipo, IMPLEMENTADOR)

    def test_pertenecer_al_grupo_no_alcanza_si_no_es_staff(self):
        cliente = User.objects.create_user("cli", password="x")
        cliente.groups.add(Group.objects.get(name=GRUPO_SUPERVISOR))
        self.assertFalse(permisos.puede_asignar(cliente))
        self.assertFalse(permisos.implementaciones_visibles(cliente).exists())


class QueVeCadaRolTests(BaseEquipo):
    def test_el_admin_ve_todas_incluidas_las_sin_asignar(self):
        self.assertEqual(self.pks_en_el_listado(self.admin), set(Implementacion.objects.values_list("pk", flat=True)))
        self.assertEqual(self.client.get(self.url(self.sin_asignar)).status_code, 200)

    def test_el_supervisor_ve_las_suyas_y_las_de_su_grupo(self):
        self.assertEqual(
            self.pks_en_el_listado(self.sol),
            {self.de_sol.pk, self.de_ana.pk, self.de_beto.pk, self.mixta_de_ana.pk},
        )

    def test_el_supervisor_no_ve_las_de_otro_supervisor_ni_las_de_su_equipo_ni_las_sin_asignar(self):
        self.client.force_login(self.sol)
        for ajena in (self.de_lucia, self.de_diego, self.de_carla, self.sin_asignar, self.mixta_de_diego):
            self.assertEqual(self.client.get(self.url(ajena)).status_code, 404, ajena.pk)

    def test_cada_supervisor_ve_solo_su_equipo(self):
        self.assertEqual(
            self.pks_en_el_listado(self.lucia), {self.de_lucia.pk, self.de_diego.pk, self.mixta_de_diego.pk},
        )

    def test_el_implementador_ve_solo_las_suyas(self):
        self.assertEqual(self.pks_en_el_listado(self.ana), {self.de_ana.pk, self.mixta_de_ana.pk})

    def test_el_implementador_no_ve_las_de_su_companero_de_grupo_ni_las_de_su_supervisor(self):
        self.client.force_login(self.ana)
        for ajena in (self.de_beto, self.de_sol, self.de_diego, self.sin_asignar):
            self.assertEqual(self.client.get(self.url(ajena)).status_code, 404, ajena.pk)

    def test_quien_no_tiene_grupo_ve_solo_las_suyas(self):
        self.assertEqual(self.pks_en_el_listado(self.carla), {self.de_carla.pk})

    def test_un_supervisor_sin_grupos_ve_solo_las_suyas(self):
        solo = User.objects.create_user("solo", password="x", is_staff=True)
        solo.groups.add(Group.objects.get(name=GRUPO_SUPERVISOR))
        impl = Implementacion.objects.create(cliente=self.empresa_norte, implementador_asignado=solo)
        self.assertEqual(self.pks_en_el_listado(solo), {impl.pk})

    def test_un_supervisor_con_dos_grupos_ve_a_los_dos(self):
        GrupoDeTrabajo.objects.create(nombre="Extra", supervisor=self.sol)
        Membresia.objects.filter(usuario=self.diego).update(grupo=self.sol.grupos_a_cargo.get(nombre="Extra"))
        self.assertIn(self.de_diego.pk, self.pks_en_el_listado(self.sol))
        self.assertNotIn(self.de_diego.pk, self.pks_en_el_listado(self.lucia))

    def test_si_el_integrante_esta_de_baja_su_supervisor_sigue_viendo_lo_que_tenia(self):
        self.beto.is_active = False
        self.beto.save()
        self.assertIn(self.de_beto.pk, self.pks_en_el_listado(self.sol))

    def test_al_sacar_a_alguien_del_grupo_su_supervisor_deja_de_verlo(self):
        Membresia.objects.filter(usuario=self.ana).delete()
        visibles = self.pks_en_el_listado(self.sol)
        self.assertNotIn(self.de_ana.pk, visibles)
        self.assertIn(self.de_beto.pk, visibles)
        self.assertEqual(self.client.get(self.url(self.de_ana)).status_code, 404)

    def test_un_supervisor_promovido_a_admin_ve_todo(self):
        self.sol.is_superuser = True
        self.sol.save()
        self.assertEqual(self.pks_en_el_listado(self.sol), set(Implementacion.objects.values_list("pk", flat=True)))

    def test_el_filtro_del_listado_trabaja_sobre_lo_que_se_ve(self):
        self.client.force_login(self.sol)
        listado = self.client.get(reverse("dashboard:home"), {"cliente": "Empresa Sur"}).context["implementaciones"]
        self.assertEqual(len(listado), 0)


class DescargasTests(BaseEquipo):
    def congelar(self, implementacion):
        return ConfiguracionCongelada.objects.create(
            implementacion=implementacion, implementacion_uuid=implementacion.uuid, version=1,
            contenido={"modulos": []}, hash="h", creada_por="t",
        )

    def nomina(self, implementacion):
        return self.client.get(reverse("dashboard:descargar_nomina", kwargs={"pk": implementacion.pk}))

    def congelada(self, implementacion):
        return self.client.get(
            reverse("dashboard:descargar_congelada", kwargs={"pk": implementacion.pk, "version": 1}),
        )

    def test_la_nomina_se_descarga_solo_de_lo_que_se_ve(self):
        self.client.force_login(self.sol)
        self.assertEqual(self.nomina(self.de_ana).status_code, 200)
        self.assertEqual(self.nomina(self.de_diego).status_code, 404)
        self.client.force_login(self.ana)
        self.assertEqual(self.nomina(self.de_ana).status_code, 200)
        self.assertEqual(self.nomina(self.de_beto).status_code, 404)

    def test_la_congelada_se_descarga_solo_de_lo_que_se_ve(self):
        self.congelar(self.de_ana)
        self.congelar(self.de_diego)
        self.client.force_login(self.sol)
        self.assertEqual(json.loads(self.congelada(self.de_ana).content)["version"], 1)
        self.assertEqual(self.congelada(self.de_diego).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.congelada(self.de_diego).status_code, 200)

    def empresas_exportadas(self, usuario):
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("dashboard:exportar"))
        self.assertEqual(respuesta.status_code, 200)
        hoja = openpyxl.load_workbook(io.BytesIO(b"".join(respuesta.streaming_content))).active
        return sorted(fila[0] for fila in hoja.iter_rows(min_row=2, values_only=True))

    def test_la_exportacion_trae_solo_lo_que_se_ve(self):
        self.assertEqual(
            self.empresas_exportadas(self.sol),
            ["Empresa Mixta", "Empresa Norte", "Empresa Norte", "Empresa Norte"],
        )
        self.assertEqual(self.empresas_exportadas(self.carla), ["Empresa Sur"])
        self.assertEqual(len(self.empresas_exportadas(self.admin)), Implementacion.objects.count())


class FichaDeLaEmpresaTests(BaseEquipo):
    def ficha(self, empresa):
        return reverse("dashboard:cliente_detalle", kwargs={"pk": empresa.pk})

    def test_la_ficha_muestra_solo_las_implementaciones_que_se_ven(self):
        self.client.force_login(self.sol)
        respuesta = self.client.get(self.ficha(self.empresa_mixta))
        self.assertEqual({i.pk for i in respuesta.context["implementaciones"]}, {self.mixta_de_ana.pk})
        self.assertNotContains(respuesta, self.url(self.mixta_de_diego))

    def test_una_empresa_que_solo_trabaja_otro_equipo_da_404(self):
        self.client.force_login(self.sol)
        self.assertEqual(self.client.get(self.ficha(self.empresa_sur)).status_code, 404)
        self.assertEqual(
            self.client.post(self.ficha(self.empresa_sur), {"accion": "regenerar_acceso", "username": "x"}).status_code, 404,
        )

    def test_el_admin_ve_todas_las_empresas(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.ficha(self.empresa_sur)).status_code, 200)

    def regenerar(self, usuario, empresa):
        self.client.force_login(usuario)
        return self.client.post(self.ficha(empresa), {"accion": "regenerar_acceso", "username": "empresa-x"})

    def test_quien_ve_alguna_implementacion_de_la_empresa_gestiona_su_acceso(self):
        for usuario in (self.ana, self.sol, self.admin):
            self.assertEqual(self.regenerar(usuario, self.empresa_norte).status_code, 302, usuario.username)

    def test_un_supervisor_de_otro_equipo_no_gestiona_su_acceso(self):
        self.assertEqual(self.regenerar(self.lucia, self.empresa_norte).status_code, 404)


class AccionarTests(BaseEquipo):
    def test_el_implementador_actua_sobre_la_suya(self):
        respuesta = self.comentar(self.ana, self.de_ana)
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.comentarios(self.de_ana), 1)

    def test_el_implementador_no_toca_las_ajenas_ni_las_sin_asignar(self):
        for implementacion in (self.de_beto, self.sin_asignar, self.de_sol):
            self.assertEqual(self.comentar(self.ana, implementacion).status_code, 404)
            self.assertEqual(self.comentarios(implementacion), 0)

    def test_el_supervisor_actua_sobre_todas_las_que_ve(self):
        for implementacion in (self.de_sol, self.de_ana, self.de_beto):
            self.assertEqual(self.comentar(self.sol, implementacion).status_code, 302)
        self.assertEqual(self.comentarios(self.de_ana), 1)

    def test_el_supervisor_no_actua_sobre_las_de_otro_equipo(self):
        for implementacion in (self.de_lucia, self.de_diego, self.sin_asignar):
            self.assertEqual(self.comentar(self.sol, implementacion).status_code, 404)
            self.assertEqual(self.comentarios(implementacion), 0)

    def test_el_admin_actua_sobre_todas(self):
        for implementacion in Implementacion.objects.all():
            self.assertEqual(self.comentar(self.admin, implementacion).status_code, 302, implementacion.pk)

    def test_cualquier_accion_de_la_ficha_esta_protegida(self):
        self.client.force_login(self.ana)
        for accion in ("actualizar_datos", "actualizar_roles", "anular", "aprobar_para_configurar", "importar_empleados"):
            self.assertEqual(self.client.post(self.url(self.de_beto), {"accion": accion}).status_code, 404, accion)

    def test_puede_accionar_distingue_ver_de_actuar(self):
        self.assertTrue(permisos.puede_ver(self.sol, self.de_ana))
        self.assertTrue(permisos.puede_accionar(self.sol, self.de_ana))
        self.assertFalse(permisos.puede_accionar(self.sol, self.de_diego))
        self.assertTrue(permisos.puede_accionar(self.ana, self.de_ana))
        self.assertFalse(permisos.puede_accionar(self.ana, self.de_beto))


class AsignarTests(BaseEquipo):
    def reasignar(self, usuario, implementacion, a):
        self.client.force_login(usuario)
        return self.client.post(self.url(implementacion), {"accion": "reasignar", "implementador_id": a.pk})

    def asignado(self, implementacion):
        implementacion.refresh_from_db()
        return implementacion.implementador_asignado

    def test_el_supervisor_reparte_dentro_de_su_equipo(self):
        self.assertEqual(self.reasignar(self.sol, self.de_ana, self.beto).status_code, 302)
        self.assertEqual(self.asignado(self.de_ana), self.beto)
        self.reasignar(self.sol, self.de_ana, self.sol)
        self.assertEqual(self.asignado(self.de_ana), self.sol)

    def test_el_supervisor_no_puede_asignar_a_alguien_de_otro_equipo(self):
        self.reasignar(self.sol, self.de_ana, self.diego)
        self.assertEqual(self.asignado(self.de_ana), self.ana)
        self.reasignar(self.sol, self.de_ana, self.lucia)
        self.assertEqual(self.asignado(self.de_ana), self.ana)

    def test_el_admin_asigna_a_cualquiera_y_tambien_las_sin_asignar(self):
        self.reasignar(self.admin, self.sin_asignar, self.ana)
        self.assertEqual(self.asignado(self.sin_asignar), self.ana)
        self.reasignar(self.admin, self.de_ana, self.diego)
        self.assertEqual(self.asignado(self.de_ana), self.diego)

    def test_si_el_admin_se_la_pasa_a_otro_equipo_deja_de_verla_el_supervisor(self):
        self.reasignar(self.admin, self.de_ana, self.diego)
        self.client.force_login(self.sol)
        self.assertEqual(self.client.get(self.url(self.de_ana)).status_code, 404)

    def test_el_evento_dice_que_lo_hizo_un_supervisor(self):
        self.reasignar(self.sol, self.de_ana, self.beto)
        evento = EventoImplementacion.objects.get(accion="implementacion.reasignada")
        self.assertEqual((evento.actor_tipo, evento.actor_ref), ("supervisor", "sol"))

    def test_el_implementador_no_puede_asignar_ni_la_suya(self):
        self.assertEqual(self.reasignar(self.ana, self.de_ana, self.beto).status_code, 403)
        self.assertEqual(self.asignado(self.de_ana), self.ana)

    def test_solo_quien_asigna_ve_el_selector_y_solo_con_su_equipo(self):
        self.client.force_login(self.ana)
        self.assertNotIn('value="reasignar"', self.client.get(self.url(self.de_ana)).content.decode())
        self.client.force_login(self.sol)
        respuesta = self.client.get(self.url(self.de_ana))
        self.assertIn('value="reasignar"', respuesta.content.decode())
        self.assertEqual({u.username for u in respuesta.context["asignables"]}, {"sol", "ana", "beto"})
        self.client.force_login(self.admin)
        todos = {u.username for u in self.client.get(self.url(self.de_ana)).context["asignables"]}
        self.assertEqual(todos, {"admin_t", "sol", "lucia", "ana", "beto", "diego", "carla"})


class AltaTests(BaseEquipo):
    def crear(self, usuario, **extra):
        self.client.force_login(usuario)
        return self.client.post(reverse("dashboard:home"), {
            "accion": "crear_implementacion", "nombre": "Nueva SA", "modulos": [], **extra,
        })

    def asignada(self):
        return Implementacion.objects.get(cliente__nombre="Nueva SA").implementador_asignado

    def test_un_implementador_puede_crear_pero_se_la_asigna_a_si_mismo(self):
        self.crear(self.ana, implementador_id=self.beto.pk)
        self.assertEqual(self.asignada(), self.ana)

    def test_el_supervisor_se_la_asigna_a_un_integrante_de_su_grupo(self):
        self.crear(self.sol, implementador_id=self.beto.pk)
        self.assertEqual(self.asignada(), self.beto)

    def test_si_el_supervisor_elige_a_alguien_de_otro_equipo_queda_asignada_a_el(self):
        self.crear(self.sol, implementador_id=self.diego.pk)
        self.assertEqual(self.asignada(), self.sol)

    def test_el_admin_la_asigna_a_cualquiera(self):
        self.crear(self.admin, implementador_id=self.diego.pk)
        self.assertEqual(self.asignada(), self.diego)

    def test_el_modal_solo_ofrece_elegir_a_quien_puede_asignar_y_a_su_equipo(self):
        self.client.force_login(self.ana)
        self.assertContains(self.client.get(reverse("dashboard:home")), "Se asigna a vos")
        self.client.force_login(self.sol)
        respuesta = self.client.get(reverse("dashboard:home"))
        self.assertNotContains(respuesta, "Se asigna a vos")
        self.assertEqual({u.username for u in respuesta.context["asignables"]}, {"sol", "ana", "beto"})


class EmpresasEnElAltaTests(BaseEquipo):
    """La lista de empresas es global (para no duplicarlas), pero de las que trabaja otro equipo no se ve el contacto."""

    def setUp(self):
        super().setUp()
        # El contacto de una empresa sale de su implementación más reciente (la última que se creó).
        self.sin_asignar.mail_contacto, self.sin_asignar.telefono = "contacto@sur.com", "1155550000"
        self.sin_asignar.save()
        self.de_sol.mail_contacto, self.de_sol.telefono = "contacto@norte.com", "1166660000"
        self.de_sol.save()
        self.empresa_sur.usuario = User.objects.create_user("cli_sur", password="x")
        self.empresa_sur.razon_social = "Sur SA"
        self.empresa_sur.save()

    def datos(self, usuario):
        self.client.force_login(usuario)
        return self.client.get(reverse("dashboard:home")).context["datos_de_clientes"]

    def test_el_supervisor_ve_el_contacto_de_las_suyas_y_no_el_de_las_ajenas(self):
        datos = self.datos(self.sol)
        propia, ajena = datos[self.empresa_norte.pk], datos[self.empresa_sur.pk]
        self.assertEqual((propia["mail"], propia["telefono"], propia["ajena"]), ("contacto@norte.com", "1166660000", False))
        self.assertEqual(ajena["nombre"], "Empresa Sur")
        self.assertEqual(ajena["razon_social"], "Sur SA")
        self.assertEqual((ajena["mail"], ajena["telefono"], ajena["usuario"], ajena["implementaciones"]), ("", "", "", 0))
        self.assertTrue(ajena["ajena"])

    def test_el_contacto_de_la_empresa_mixta_sale_solo_de_lo_que_se_ve(self):
        datos = self.datos(self.sol)[self.empresa_mixta.pk]
        self.assertEqual(datos["implementaciones"], 1)

    def test_el_admin_lo_ve_todo(self):
        datos = self.datos(self.admin)
        self.assertEqual(datos[self.empresa_sur.pk]["mail"], "contacto@sur.com")
        self.assertFalse(datos[self.empresa_sur.pk]["ajena"])

    def test_crear_para_una_empresa_ajena_no_hereda_el_contacto_ni_toca_sus_datos(self):
        self.client.force_login(self.sol)
        self.client.post(reverse("dashboard:home"), {
            "accion": "crear_implementacion", "cliente_id": self.empresa_sur.pk, "nombre": "Empresa Sur",
            "razon_social": "Razón pisada", "cuits": "30-71234567-5", "mail_cliente": "", "modulos": [],
        })
        nueva = Implementacion.objects.filter(cliente=self.empresa_sur).order_by("-pk").first()
        self.assertEqual(nueva.implementador_asignado, self.sol)
        self.assertEqual((nueva.mail_contacto, nueva.telefono), ("", ""))
        self.empresa_sur.refresh_from_db()
        self.assertEqual((self.empresa_sur.razon_social, self.empresa_sur.cuits), ("Sur SA", ""))

    def test_crear_para_una_empresa_propia_si_hereda_el_contacto(self):
        self.client.force_login(self.sol)
        self.client.post(reverse("dashboard:home"), {
            "accion": "crear_implementacion", "cliente_id": self.empresa_norte.pk, "nombre": "Empresa Norte", "modulos": [],
        })
        nueva = Implementacion.objects.filter(cliente=self.empresa_norte).order_by("-pk").first()
        self.assertEqual((nueva.mail_contacto, nueva.telefono), ("contacto@norte.com", "1166660000"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ArchivosTests(BaseEquipo):
    """Los archivos subidos (banner, firma, copias congeladas) los ve quien ve su implementación: conocer la URL no basta."""

    def setUp(self):
        super().setUp()
        self.de_ana.banner.save("banner.png", ContentFile(b"banner-de-ana"))
        self.de_diego.banner.save("banner.png", ContentFile(b"banner-de-diego"))
        self.copia = default_storage.save(f"congeladas/{self.de_ana.uuid}/v1/modelo_recibo.pdf", ContentFile(b"copia-de-ana"))

    def estado(self, usuario, ruta):
        self.client.force_login(usuario)
        return self.client.get(reverse("media", kwargs={"ruta": ruta})).status_code

    def test_el_implementador_abre_los_de_su_implementacion_y_no_los_ajenos(self):
        self.assertEqual(self.estado(self.ana, self.de_ana.banner.name), 200)
        self.assertEqual(self.estado(self.ana, self.de_diego.banner.name), 404)
        self.assertEqual(self.estado(self.beto, self.de_ana.banner.name), 404)

    def test_el_supervisor_abre_los_de_su_equipo_y_no_los_de_otro(self):
        self.assertEqual(self.estado(self.sol, self.de_ana.banner.name), 200)
        self.assertEqual(self.estado(self.sol, self.de_diego.banner.name), 404)
        self.assertEqual(self.estado(self.lucia, self.de_diego.banner.name), 200)

    def test_el_admin_abre_todos(self):
        self.assertEqual(self.estado(self.admin, self.de_ana.banner.name), 200)
        self.assertEqual(self.estado(self.admin, self.de_diego.banner.name), 200)

    def test_las_copias_de_la_configuracion_congelada_siguen_a_su_implementacion(self):
        self.assertEqual(self.estado(self.sol, self.copia), 200)
        self.assertEqual(self.estado(self.lucia, self.copia), 404)

    def test_un_archivo_que_no_es_de_ninguna_implementacion_solo_lo_abre_el_admin(self):
        suelto = default_storage.save("implementaciones/otros/suelto.txt", ContentFile(b"x"))
        self.assertEqual(self.estado(self.sol, suelto), 404)
        self.assertEqual(self.estado(self.admin, suelto), 200)

    def test_una_ruta_de_congelada_mal_formada_da_404_y_no_error(self):
        malformada = default_storage.save("congeladas/no-es-un-uuid/v1/x.pdf", ContentFile(b"x"))
        self.assertEqual(self.estado(self.sol, malformada), 404)
