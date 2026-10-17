from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("clientes/<int:pk>/", views.cliente_detalle, name="cliente_detalle"),
    path("implementaciones/<int:pk>/", views.implementacion_detalle, name="implementacion_detalle"),
    path("implementaciones/<int:pk>/nomina.xlsx", views.descargar_nomina, name="descargar_nomina"),
    path("exportar/", views.exportar_implementaciones, name="exportar"),
    path("implementadores/", views.implementadores_lista, name="implementadores"),
    path("implementadores/<int:pk>/", views.implementador_detalle, name="implementador_detalle"),
]
