from django.contrib import admin

from .models import EventoImplementacion


@admin.register(EventoImplementacion)
class EventoImplementacionAdmin(admin.ModelAdmin):
    """Solo lectura: el registro no se edita ni se borra, ni siquiera desde acá."""

    list_display = ("momento", "accion", "actor_tipo", "actor_ref", "seccion", "post_envio", "implementacion")
    list_filter = ("accion", "actor_tipo", "post_envio", "origen")
    search_fields = ("actor_ref", "accion", "correlation_id", "implementacion_uuid")
    date_hierarchy = "momento"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
