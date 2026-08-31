from django.db import models


class TipoLicencia(models.Model):
    """Catálogo fijo relevado en Licencias y Novedades.xlsx (16 tipos)."""

    nombre = models.CharField(max_length=150, unique=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Tipo de licencia"
        verbose_name_plural = "Tipos de licencia"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class TipoNovedad(models.Model):
    """Catálogo fijo relevado en Licencias y Novedades.xlsx (10 tipos)."""

    nombre = models.CharField(max_length=150, unique=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Tipo de novedad"
        verbose_name_plural = "Tipos de novedad"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class TipoDocumento(models.Model):
    """
    Tipo de documento del Legajo Digital.

    Los 16 tipos relevados en Documentos Legajo Digital.xlsx se cargan como
    catálogo global (implementacion=None, es_custom=False). Durante el wizard,
    una implementación puede además agregar tipos propios ("Otros"): quedan
    con implementacion seteada y es_custom=True, sin aparecer en el catálogo
    de otras implementaciones.
    """

    nombre = models.CharField(max_length=150)
    implementacion = models.ForeignKey(
        "clients.Implementacion",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tipos_documento_custom",
        help_text="Vacío = catálogo global. Seteado = tipo 'Otros' agregado en esa implementación.",
    )
    es_custom = models.BooleanField(default=False)
    requiere_firma = models.BooleanField("Requiere Firma", default=False)
    circuito_aprobacion = models.CharField(
        "Circuito de Aprobación del Documento", max_length=255, blank=True
    )
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Tipo de documento"
        verbose_name_plural = "Tipos de documento"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class CampoDocumento(models.Model):
    tipo_documento = models.ForeignKey(
        TipoDocumento, on_delete=models.CASCADE, related_name="campos"
    )
    nombre = models.CharField(max_length=150)
    obligatorio = models.BooleanField(default=False)
    permite_multiples_adjuntos = models.PositiveSmallIntegerField(
        default=1, help_text="Cantidad de adjuntos permitidos para este campo (1 = uno solo)."
    )
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Campo de documento"
        verbose_name_plural = "Campos de documento"
        ordering = ["tipo_documento", "orden"]

    def __str__(self):
        return f"{self.tipo_documento} · {self.nombre}"
