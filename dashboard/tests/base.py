"""Pieza compartida por los tests del panel (y de otras apps que usan el panel)."""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from automatizacion.actores import GRUPO_SUPERVISOR


def crear_supervisor(username="sol", **extra):
    """Una cuenta de staff del grupo Supervisor: ve y actúa sobre las suyas y las de los integrantes de sus grupos."""
    usuario = User.objects.create_user(username=username, password="x", is_staff=True, **extra)
    usuario.groups.add(Group.objects.get_or_create(name=GRUPO_SUPERVISOR)[0])
    return usuario


def crear_operador(username="ana", **extra):
    """Una cuenta Admin: ve y actúa sobre todas las implementaciones, también las que no tienen asignado. Los tests
    del panel la usan como «quien opera» para no tener que asignarle cada implementación de prueba; lo que cambia
    según el rol y el grupo se prueba aparte (dashboard/tests/equipo/test_permisos_por_asignacion.py)."""
    return User.objects.create_user(username=username, password="x", is_staff=True, is_superuser=True, **extra)


class BasePanel(TestCase):
    """Un equipo con una cuenta que ve y opera todo (ana, Admin) y otro administrador, con ana ya logueada."""

    def setUp(self):
        self.admin = User.objects.create_user(username="admin_t", password="x", is_staff=True, is_superuser=True)
        self.ana = crear_operador("ana", first_name="Ana", last_name="Paz")
        self.cliente_user = User.objects.create_user(username="cliente_t", password="x")
        self.client.force_login(self.ana)

    def crear(self, **datos):
        return self.client.post(reverse("dashboard:home"), {"accion": "crear_implementacion", **datos})


class BaseGrupos(TestCase):
    """Un equipo con dos supervisores y sus grupos, para probar quién ve qué.

    - `sol` supervisa el grupo Norte (ana y beto); `lucia` supervisa el grupo Sur (diego); `carla` no tiene grupo.
    - Hay una implementación asignada a cada uno, una sin asignar y una empresa con implementaciones de dos grupos.
    """

    def setUp(self):
        from clients.models import Cliente, Implementacion
        from dashboard.models import GrupoDeTrabajo, Membresia

        self.admin = User.objects.create_user("admin_t", password="x", is_staff=True, is_superuser=True)
        self.sol = crear_supervisor("sol", first_name="Sol", last_name="Vega")
        self.lucia = crear_supervisor("lucia", first_name="Lucía", last_name="Mora")
        self.ana = User.objects.create_user("ana", password="x", is_staff=True, first_name="Ana", last_name="Paz")
        self.beto = User.objects.create_user("beto", password="x", is_staff=True, first_name="Beto", last_name="Ruiz")
        self.diego = User.objects.create_user("diego", password="x", is_staff=True, first_name="Diego", last_name="Sosa")
        self.carla = User.objects.create_user("carla", password="x", is_staff=True, first_name="Carla", last_name="Gómez")
        self.norte = GrupoDeTrabajo.objects.create(nombre="Norte", supervisor=self.sol)
        self.sur = GrupoDeTrabajo.objects.create(nombre="Sur", supervisor=self.lucia)
        for usuario in (self.ana, self.beto):
            Membresia.objects.create(usuario=usuario, grupo=self.norte)
        Membresia.objects.create(usuario=self.diego, grupo=self.sur)

        self.empresa_norte = Cliente.objects.create(nombre="Empresa Norte")
        self.empresa_sur = Cliente.objects.create(nombre="Empresa Sur")
        self.empresa_mixta = Cliente.objects.create(nombre="Empresa Mixta")

        def crear_impl(cliente, asignado):
            return Implementacion.objects.create(cliente=cliente, implementador_asignado=asignado)

        self.de_ana = crear_impl(self.empresa_norte, self.ana)
        self.de_beto = crear_impl(self.empresa_norte, self.beto)
        self.de_sol = crear_impl(self.empresa_norte, self.sol)
        self.de_diego = crear_impl(self.empresa_sur, self.diego)
        self.de_lucia = crear_impl(self.empresa_sur, self.lucia)
        self.de_carla = crear_impl(self.empresa_sur, self.carla)
        self.sin_asignar = crear_impl(self.empresa_sur, None)
        self.mixta_de_ana = crear_impl(self.empresa_mixta, self.ana)
        self.mixta_de_diego = crear_impl(self.empresa_mixta, self.diego)

    def url(self, implementacion):
        return reverse("dashboard:implementacion_detalle", kwargs={"pk": implementacion.pk})

    def pks_en_el_listado(self, usuario):
        """Los pk de las implementaciones que el panel le lista a ese usuario."""
        self.client.force_login(usuario)
        return {i.pk for i in self.client.get(reverse("dashboard:home")).context["implementaciones"]}
