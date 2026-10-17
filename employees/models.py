from django.db import models

from clients.validators import validar_tamanio_archivo


class ImportBatch(models.Model):
    """Registro de cada archivo de nómina subido en una implementación, con el detalle de filas rechazadas."""

    implementacion = models.ForeignKey(
        "clients.Implementacion", on_delete=models.CASCADE, related_name="import_batches"
    )
    # Las importaciones nuevas no guardan el archivo (tiene datos personales y no se vuelve a usar):
    # solo `nombre_archivo` y el resultado. `archivo` queda para las importaciones anteriores.
    archivo = models.FileField(
        upload_to="implementaciones/importaciones/", validators=[validar_tamanio_archivo], blank=True
    )
    nombre_archivo = models.CharField(max_length=255, blank=True)
    filas_totales = models.PositiveIntegerField(default=0)
    filas_importadas = models.PositiveIntegerField(default=0)
    errores = models.JSONField(default=list, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Importación de nómina"
        verbose_name_plural = "Importaciones de nómina"
        ordering = ["-creado"]

    def __str__(self):
        return f"Importación {self.implementacion} ({self.creado:%d/%m/%Y})"


class Empleado(models.Model):
    """Empleado relevado en una implementación, sea por carga manual o por importación masiva."""

    SEXO_CHOICES = [("F", "Femenino"), ("M", "Masculino")]

    implementacion = models.ForeignKey(
        "clients.Implementacion", on_delete=models.CASCADE, related_name="empleados"
    )
    import_batch = models.ForeignKey(
        ImportBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="empleados"
    )

    cuil = models.CharField("CUIL", max_length=20)
    dni = models.CharField("DNI", max_length=20, blank=True)
    nombre = models.CharField("Nombre", max_length=150)
    apellido = models.CharField("Apellido", max_length=150)
    legajo = models.CharField("Legajo", max_length=50, blank=True)
    fecha_ingreso = models.DateField("Fecha Ingreso", null=True, blank=True)
    mail = models.EmailField("Mail", blank=True)
    sexo = models.CharField("Sexo", max_length=1, choices=SEXO_CHOICES, blank=True)
    fecha_nacimiento = models.DateField("Fecha de Nacimiento", null=True, blank=True)
    lugar_nacimiento = models.CharField("Lugar de Nacimiento", max_length=150, blank=True)
    nacionalidad = models.CharField("Nacionalidad", max_length=100, blank=True)
    estado_civil = models.CharField("Estado Civil", max_length=50, blank=True)

    domicilio = models.CharField("Domicilio", max_length=255, blank=True)
    planta_vivienda = models.CharField("Planta/Vivienda", max_length=100, blank=True)
    codigo_postal = models.CharField("Código Postal", max_length=20, blank=True)
    localidad = models.CharField("Localidad", max_length=150, blank=True)
    telefono = models.CharField("Teléfono", max_length=50, blank=True)

    obra_social = models.CharField("Obra Social", max_length=150, blank=True)
    centro_costo = models.CharField("Centro de Costo", max_length=150, blank=True)
    puesto = models.CharField("Puesto", max_length=150, blank=True)
    gerencia = models.CharField("Gerencia", max_length=150, blank=True)
    sector = models.CharField("Sector", max_length=150, blank=True)
    funcion = models.CharField("Función", max_length=150, blank=True)

    es_supervisor = models.BooleanField("¿Es supervisor?", default=False)
    home_office = models.BooleanField("Home Office", default=False)
    sucursal = models.ForeignKey(
        "clients.Sucursal", on_delete=models.SET_NULL, null=True, blank=True, related_name="empleados"
    )

    reporta_a = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reportes"
    )
    aprobador = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="aprobaciones"
    )

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Empleado"
        verbose_name_plural = "Empleados"
        ordering = ["apellido", "nombre"]
        unique_together = ("implementacion", "cuil")

    def __str__(self):
        return f"{self.apellido}, {self.nombre} ({self.cuil})"
