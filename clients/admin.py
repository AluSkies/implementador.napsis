from django.contrib import admin

from catalog.codigos import AdminConCodigo

from .models import (
    Cliente,
    Implementacion,
    ImplementacionLicencia,
    ImplementacionModulo,
    ImplementacionNovedad,
    ImplementacionTipoDocumento,
    ImplementacionVersion,
    Modulo,
    PersonaRol,
    Sucursal,
)


class ImplementacionInline(admin.TabularInline):
    model = Implementacion
    extra = 0
    fields = ("estado", "paso_actual", "creado", "enviado")
    readonly_fields = ("creado",)
    show_change_link = True


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "cuits", "creado")
    search_fields = ("nombre", "cuits")
    inlines = [ImplementacionInline]


class ImplementacionModuloInline(admin.TabularInline):
    model = ImplementacionModulo
    extra = 0


class PersonaRolInline(admin.TabularInline):
    model = PersonaRol
    extra = 0


class SucursalInline(admin.TabularInline):
    model = Sucursal
    extra = 0


@admin.register(Implementacion)
class ImplementacionAdmin(admin.ModelAdmin):
    list_display = ("cliente", "estado", "paso_actual", "revision_solicitada", "creado", "enviado")
    list_filter = ("estado", "revision_solicitada", "origen")
    readonly_fields = ("token", "uuid")
    inlines = [ImplementacionModuloInline, PersonaRolInline, SucursalInline]


@admin.register(Modulo)
class ModuloAdmin(AdminConCodigo, admin.ModelAdmin):
    list_display = ("nombre", "codigo", "orden")
    # Renombrar un módulo es seguro (los pasos dependen del código); borrarlo no lo es.
admin.site.register(ImplementacionLicencia)
admin.site.register(ImplementacionNovedad)
admin.site.register(ImplementacionTipoDocumento)


@admin.register(ImplementacionVersion)
class ImplementacionVersionAdmin(admin.ModelAdmin):
    list_display = ("implementacion", "seccion", "editado_por", "creado")
    list_filter = ("seccion",)
    readonly_fields = ("implementacion", "seccion", "datos", "editado_por", "creado")
