from django.contrib import admin

from .models import EventoDeCuenta


@admin.register(EventoDeCuenta)
class EventoDeCuentaAdmin(admin.ModelAdmin):
    """Solo lectura: el registro de cambios en las cuentas no se edita ni se borra, ni siquiera desde acá."""

    list_display = ("momento", "accion", "actor", "sujeto")
    list_filter = ("accion",)
    search_fields = ("actor", "sujeto", "accion")
    date_hierarchy = "momento"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
