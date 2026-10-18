from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from . import actores


class EventoInmutable(Exception):
    """Los eventos son un registro de solo agregado: no se modifican ni se borran."""


class EventoQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise EventoInmutable("Los eventos no se pueden modificar.")

    def delete(self):
        raise EventoInmutable("Los eventos no se pueden borrar.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise EventoInmutable("Los eventos no se pueden modificar.")


class EventoImplementacion(models.Model):
    """Una cosa que pasó en una implementación: quién, cuándo, qué, y el antes y el después.

    Registro de solo agregado (ver `automatizacion.eventos.registrar`). Se guarda en la misma
    transacción que el cambio que describe. El detalle de lo que ya conserva la base (por ejemplo,
    cada empleado de una nómina importada) no se duplica acá: se registran los resúmenes y todo lo
    que la base pisa o borra.
    """

    ORIGEN_WEB = "web"
    ORIGEN_API = "api"
    ORIGEN_SISTEMA = "sistema"
    ORIGEN_COMANDO = "comando"
    ORIGEN_CHOICES = [
        (ORIGEN_WEB, "Web"), (ORIGEN_API, "API"), (ORIGEN_SISTEMA, "Sistema"), (ORIGEN_COMANDO, "Comando"),
    ]

    # El evento sobrevive a la implementación: si se borra, queda el uuid para reconstruir la historia.
    implementacion = models.ForeignKey(
        "clients.Implementacion", null=True, blank=True, on_delete=models.SET_NULL, related_name="eventos",
    )
    implementacion_uuid = models.UUIDField(null=True, blank=True, db_index=True)

    momento = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    actor_tipo = models.CharField(max_length=20, choices=[(t, t) for t in actores.TIPOS])
    actor_ref = models.CharField(max_length=150, blank=True)
    accion = models.CharField(max_length=60, db_index=True)
    seccion = models.CharField(max_length=40, blank=True)
    datos = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    origen = models.CharField(max_length=20, choices=ORIGEN_CHOICES, default=ORIGEN_WEB)
    correlation_id = models.CharField(max_length=64, blank=True)
    # La acción ocurrió con la documentación ya enviada por el cliente. Es la marca de las
    # correcciones del equipo: lo que más enseña a un agente.
    post_envio = models.BooleanField(default=False)
    version_esquema = models.PositiveSmallIntegerField(default=1)

    objects = EventoQuerySet.as_manager()

    class Meta:
        verbose_name = "Evento de implementación"
        verbose_name_plural = "Eventos de implementación"
        ordering = ["momento", "id"]
        indexes = [
            models.Index(fields=["implementacion_uuid", "momento"], name="evento_impl_momento_idx"),
            models.Index(fields=["accion", "momento"], name="evento_accion_momento_idx"),
        ]

    def __str__(self):
        return f"{self.momento:%d/%m/%Y %H:%M} · {self.accion} · {self.actor_tipo}:{self.actor_ref}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise EventoInmutable("Los eventos no se pueden modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise EventoInmutable("Los eventos no se pueden borrar.")


class CongeladaInmutable(Exception):
    """Una configuración congelada no se modifica ni se borra: si algo cambia, se crea otra versión."""


class CongeladaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise CongeladaInmutable("Las configuraciones congeladas no se pueden modificar.")

    def delete(self):
        raise CongeladaInmutable("Las configuraciones congeladas no se pueden borrar.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise CongeladaInmutable("Las configuraciones congeladas no se pueden modificar.")


class ConfiguracionCongelada(models.Model):
    """La foto de lo que el equipo aprobó para configurar (ver `automatizacion.congelada`).

    Una por cada vez que se valida la documentación; solo de lectura. `contenido` son los datos con
    códigos estables y `archivos` las copias inmutables (ruta y `sha256`) de lo que se subió."""

    # Como los eventos: sobrevive a la implementación (queda el uuid).
    implementacion = models.ForeignKey(
        "clients.Implementacion", null=True, blank=True, on_delete=models.SET_NULL, related_name="congeladas",
    )
    implementacion_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    version = models.PositiveIntegerField()
    version_esquema = models.PositiveSmallIntegerField(default=1)
    contenido = models.JSONField(encoder=DjangoJSONEncoder)
    archivos = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    hash = models.CharField(max_length=64)
    creada_por = models.CharField(max_length=150)
    creada_en = models.DateTimeField(default=timezone.now, editable=False)

    objects = CongeladaQuerySet.as_manager()

    class Meta:
        verbose_name = "Configuración congelada"
        verbose_name_plural = "Configuraciones congeladas"
        ordering = ["implementacion_uuid", "version"]
        constraints = [
            models.UniqueConstraint(fields=["implementacion_uuid", "version"], name="congelada_version_unica"),
        ]

    def __str__(self):
        return f"{self.implementacion_uuid} · v{self.version}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise CongeladaInmutable("Las configuraciones congeladas no se pueden modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise CongeladaInmutable("Las configuraciones congeladas no se pueden borrar.")
