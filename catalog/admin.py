from django.contrib import admin

from .codigos import AdminConCodigo
from .models import CampoDocumento, TipoDocumento, TipoLicencia, TipoLiquidacion, TipoNovedad


class CampoDocumentoInline(admin.TabularInline):
    model = CampoDocumento
    extra = 0


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(AdminConCodigo, admin.ModelAdmin):
    list_display = ("nombre", "codigo", "implementacion", "es_custom", "requiere_firma", "orden")
    list_filter = ("es_custom", "requiere_firma")
    inlines = [CampoDocumentoInline]


@admin.register(TipoLicencia)
class TipoLicenciaAdmin(AdminConCodigo, admin.ModelAdmin):
    list_display = ("nombre", "codigo", "automatica", "orden")


@admin.register(TipoLiquidacion)
class TipoLiquidacionAdmin(AdminConCodigo, admin.ModelAdmin):
    list_display = ("nombre", "codigo", "orden")


@admin.register(TipoNovedad)
class TipoNovedadAdmin(AdminConCodigo, admin.ModelAdmin):
    list_display = ("nombre", "codigo", "orden")
