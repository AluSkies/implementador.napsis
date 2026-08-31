from django.contrib import admin

from .models import ImplementacionLicencia, ImplementacionNovedad, ImplementacionTipoDocumento

admin.site.register(ImplementacionLicencia)
admin.site.register(ImplementacionNovedad)
admin.site.register(ImplementacionTipoDocumento)
