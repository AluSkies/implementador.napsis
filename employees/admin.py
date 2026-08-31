from django.contrib import admin

from .models import Empleado, ImportBatch


@admin.register(Empleado)
class EmpleadoAdmin(admin.ModelAdmin):
    list_display = ("apellido", "nombre", "cuil", "implementacion", "legajo", "puesto")
    list_filter = ("implementacion",)
    search_fields = ("apellido", "nombre", "cuil", "dni")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("implementacion", "filas_totales", "filas_importadas", "creado")
