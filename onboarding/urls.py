from django.urls import path

from . import views

app_name = "onboarding"

urlpatterns = [
    path("mis-implementaciones/", views.mis_implementaciones, name="mis_implementaciones"),
    path("<str:token>/", views.wizard_step, {"step": 1}, name="wizard_start"),
    path("<str:token>/paso/<int:step>/", views.wizard_step, name="wizard_step"),
    path("<str:token>/plantilla-empleados/", views.descargar_plantilla_empleados, name="plantilla_empleados"),
    path("<str:token>/enviado/", views.enviado, name="enviado"),
]
