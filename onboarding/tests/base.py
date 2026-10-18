"""Piezas compartidas por los tests de onboarding: el wizard armado y la implementación enviada."""

import io
from datetime import date

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from automatizacion.actores import Actor
from catalog.models import TipoLiquidacion
from clients.models import (
    Cliente,
    Implementacion,
    ImplementacionLiquidacion,
    ImplementacionModulo,
    Modulo,
    PersonaRol,
    UbicacionFirma,
)
from employees.models import Empleado
from onboarding import acciones


def _url(implementacion, paso):
    return reverse("onboarding:wizard_step", kwargs={"token": implementacion.token, "step": paso})


CUIT = "30-50001091-2"
CLIENTE = Actor.cliente("cliente_a")
ANA = Actor.implementador("ana")


def imagen(ancho, alto, nombre="imagen.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (ancho, alto), "white").save(buffer, format="PNG")
    return SimpleUploadedFile(nombre, buffer.getvalue(), content_type="image/png")


GEOMETRIA = {
    "empresa": {"x": 0.1, "y": 0.7, "ancho": 0.3, "alto": 0.1},
    "conforme": {"x": 0.1, "y": 0.85, "ancho": 0.3, "alto": 0.1},
    "disconforme": {"x": 0.55, "y": 0.85, "ancho": 0.3, "alto": 0.1},
}


def datos_de_formulario(**cambios):
    datos = {"pagina": "ultima"}
    for codigo, recuadro in GEOMETRIA.items():
        for campo, valor in recuadro.items():
            datos[f"{codigo}_{campo}"] = round(valor * 100, 1)
    datos.update(cambios)
    return datos


class BaseWizard(TestCase):
    """Un cliente con su implementación y los módulos que pida cada test."""

    modulos = ["Recibo Digital"]

    def setUp(self):
        self.usuario = User.objects.create_user(username="cliente_a", password="x")
        self.cliente = Cliente.objects.create(nombre="Empresa A", usuario=self.usuario)
        self.implementacion = Implementacion.objects.create(cliente=self.cliente)
        for nombre in self.modulos:
            modulo, _ = Modulo.objects.get_or_create(nombre=nombre)
            ImplementacionModulo.objects.create(implementacion=self.implementacion, modulo=modulo, activo=True)
        self.liquidacion = TipoLiquidacion.objects.create(nombre="Liquidación Normal")
        self.client.force_login(self.usuario)

    CUIL_APODERADO = "20111111112"
    CUIL_LIQUIDADOR = "20222222223"

    def agregar_empleado(self, cuil=CUIL_APODERADO, nombre="JUAN", apellido="PEREZ"):
        empleado, _ = Empleado.objects.get_or_create(
            implementacion=self.implementacion, cuil=cuil,
            defaults={"nombre": nombre, "apellido": apellido, "fecha_ingreso": date(2020, 1, 1)},  # obligatoria con Recibo Digital
        )
        return empleado

    def cargar_roles_completos(self):
        """Los tres roles. El Apoderado y el Liquidador salen de la nómina, así que se cargan sus empleados."""
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        for rol, nombre, cuil in (
            (PersonaRol.ROL_APODERADO, "Gomez, Ana", self.CUIL_APODERADO),
            (PersonaRol.ROL_LIQUIDADOR, "Ruiz, Luis", self.CUIL_LIQUIDADOR),
            (PersonaRol.ROL_ADMIN_RRHH, "Sosa, Eva", ""),
        ):
            PersonaRol.objects.create(implementacion=self.implementacion, rol=rol, apellido_nombre=nombre, cuil=cuil)

    def completar_todo(self):
        self.cliente.razon_social = "Empresa A S.A."
        self.cliente.cuits = CUIT
        self.cliente.save()
        self.cargar_roles_completos()
        ImplementacionLiquidacion.objects.update_or_create(
            implementacion=self.implementacion, tipo_liquidacion=self.liquidacion, defaults={"activo": True},
        )
        self.implementacion.modelo_recibo.save("m.pdf", SimpleUploadedFile("m.pdf", b"%PDF-1.4"))
        self.agregar_empleado()
        self.cargar_firma()

    def cargar_firma(self, estado=UbicacionFirma.ESTADO_VALIDADA):
        """La firma ya subida y ubicada (por defecto, también validada por el equipo)."""
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (300, 100), "white").save(buffer, format="PNG")
        firma = UbicacionFirma(implementacion=self.implementacion, estado=estado, propuesta_por="cliente_a")
        firma.imagen.save("firma.png", ContentFile(buffer.getvalue()), save=False)
        firma.save()
        return firma


class EnviadaBase(BaseWizard):
    """Una implementación completa y ya enviada por el cliente."""

    def setUp(self):
        super().setUp()
        self.implementacion.mail_contacto = "cliente@empresa.com"
        self.implementacion.save()
        self.completar_todo()
        acciones.enviar_relevamiento(CLIENTE, self.implementacion, None)
        self.implementacion.refresh_from_db()
        mail.outbox.clear()

    def devolver(self, motivo="Faltan los legajos del personal nuevo.", observaciones=None):
        return acciones.devolver_al_cliente(ANA, self.implementacion, motivo, observaciones)
