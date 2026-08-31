from django.contrib import admin

from .models import CampoDocumento, TipoDocumento, TipoLicencia, TipoNovedad


class CampoDocumentoInline(admin.TabularInline):
    model = CampoDocumento
    extra = 0


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "implementacion", "es_custom", "requiere_firma", "orden")
    list_filter = ("es_custom", "requiere_firma")
    inlines = [CampoDocumentoInline]


@admin.register(TipoLicencia)
class TipoLicenciaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "orden")


@admin.register(TipoNovedad)
class TipoNovedadAdmin(admin.ModelAdmin):
    list_display = ("nombre", "orden")
