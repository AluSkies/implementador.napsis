from django.db import models


class ImplementacionLicencia(models.Model):
    implementacion = models.ForeignKey(
        "clients.Implementacion", on_delete=models.CASCADE, related_name="licencias"
    )
    tipo_licencia = models.ForeignKey("catalog.TipoLicencia", on_delete=models.PROTECT)
    activo = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Licencia de la implementación"
        verbose_name_plural = "Licencias de la implementación"
        unique_together = ("implementacion", "tipo_licencia")

    def __str__(self):
        return f"{self.implementacion} - {self.tipo_licencia}"


class ImplementacionNovedad(models.Model):
    implementacion = models.ForeignKey(
        "clients.Implementacion", on_delete=models.CASCADE, related_name="novedades"
    )
    tipo_novedad = models.ForeignKey("catalog.TipoNovedad", on_delete=models.PROTECT)
    activo = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Novedad de la implementación"
        verbose_name_plural = "Novedades de la implementación"
        unique_together = ("implementacion", "tipo_novedad")

    def __str__(self):
        return f"{self.implementacion} - {self.tipo_novedad}"


class ImplementacionTipoDocumento(models.Model):
    """Activación de un TipoDocumento para una implementación puntual.

    La fecha de puesta en vigencia NO es por ítem — es única para toda la
    implementación (`Implementacion.fecha_salida_productivo`).
    """

    implementacion = models.ForeignKey(
        "clients.Implementacion", on_delete=models.CASCADE, related_name="documentos_legajo"
    )
    tipo_documento = models.ForeignKey("catalog.TipoDocumento", on_delete=models.CASCADE)
    activo = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Documento de legajo de la implementación"
        verbose_name_plural = "Documentos de legajo de la implementación"
        unique_together = ("implementacion", "tipo_documento")

    def __str__(self):
        return f"{self.implementacion} - {self.tipo_documento}"
