"""Pieza compartida por los tests del panel (y de otras apps que usan el panel)."""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from automatizacion.actores import GRUPO_SUPERVISOR


def crear_supervisor(username="ana", **extra):
    """Una cuenta de staff del grupo Supervisor: actúa sobre todas las implementaciones. Los tests del
    panel la usan como «quien opera» para no tener que asignarle cada implementación de prueba; lo que
    cambia según la asignación se prueba aparte (dashboard/tests/equipo/test_permisos_por_asignacion.py)."""
    usuario = User.objects.create_user(username=username, password="x", is_staff=True, **extra)
    usuario.groups.add(Group.objects.get_or_create(name=GRUPO_SUPERVISOR)[0])
    return usuario


class BasePanel(TestCase):
    """Un equipo con una supervisora (ana, que actúa sobre todo) y un administrador, con ana ya logueada."""

    def setUp(self):
        self.admin = User.objects.create_user(username="admin_t", password="x", is_staff=True, is_superuser=True)
        self.ana = crear_supervisor("ana", first_name="Ana", last_name="Paz")
        self.cliente_user = User.objects.create_user(username="cliente_t", password="x")
        self.client.force_login(self.ana)

    def crear(self, **datos):
        return self.client.post(reverse("dashboard:home"), {"accion": "crear_implementacion", **datos})
