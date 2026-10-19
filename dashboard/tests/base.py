"""Pieza compartida por los tests del panel (y de otras apps que usan el panel)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class BasePanel(TestCase):
    """Un equipo con un implementador (ana) y un administrador, con ana ya logueada."""

    def setUp(self):
        self.admin = User.objects.create_user(username="admin_t", password="x", is_staff=True, is_superuser=True)
        self.ana = User.objects.create_user(username="ana", password="x", is_staff=True, first_name="Ana", last_name="Paz")
        self.cliente_user = User.objects.create_user(username="cliente_t", password="x")
        self.client.force_login(self.ana)

    def crear(self, **datos):
        return self.client.post(reverse("dashboard:home"), {"accion": "crear_implementacion", **datos})
