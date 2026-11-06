"""Grupos de trabajo del equipo y registro de los cambios en las cuentas.

Un **grupo** es una lista de implementadores a cargo de un supervisor: define qué implementaciones ve cada
supervisor (las suyas y las de los integrantes de sus grupos). Un implementador pertenece a un solo grupo
(`Membresia.usuario` es único), así que ninguna implementación queda a la vista de dos supervisores.
"""

from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from automatizacion.models import EventoInmutable, EventoQuerySet


class GrupoDeTrabajo(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    # PROTECT: una cuenta con grupos a cargo no se puede borrar (ni dejar de ser supervisor) sin reasignarlos.
    supervisor = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="grupos_a_cargo",
        help_text="Quien ve las implementaciones de los integrantes del grupo.",
    )
    creado = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "Grupo de trabajo"
        verbose_name_plural = "Grupos de trabajo"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Membresia(models.Model):
    """Un implementador dentro de un grupo. Una cuenta pertenece a lo sumo a un grupo."""

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name="membresia")
    grupo = models.ForeignKey(GrupoDeTrabajo, on_delete=models.CASCADE, related_name="membresias")

    class Meta:
        verbose_name = "Integrante de un grupo"
        verbose_name_plural = "Integrantes de los grupos"

    def __str__(self):
        return f"{self.usuario.get_username()} en {self.grupo}"


class EventoDeCuenta(models.Model):
    """Un cambio en las cuentas del equipo o en sus grupos: quién lo hizo, a quién, y qué cambió.

    Registro de solo agregado, como los eventos de las implementaciones. Dar el rol Admin o mover a alguien de
    grupo cambia quién ve qué: por eso queda rastro. Guarda nombres como texto para que sobreviva a la cuenta.
    """

    momento = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    actor = models.CharField(max_length=150, help_text="Usuario de quien hizo el cambio.")
    sujeto = models.CharField(max_length=150, help_text="La cuenta o el grupo afectado.")
    accion = models.CharField(max_length=60, db_index=True)
    datos = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)

    objects = EventoQuerySet.as_manager()

    class Meta:
        verbose_name = "Evento de cuenta"
        verbose_name_plural = "Eventos de cuentas"
        ordering = ["-momento", "-id"]

    def __str__(self):
        return f"{self.momento:%d/%m/%Y %H:%M} · {self.accion} · {self.sujeto}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise EventoInmutable("Los eventos no se pueden modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise EventoInmutable("Los eventos no se pueden borrar.")
