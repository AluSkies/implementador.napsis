from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from django.views.generic import TemplateView

from clients.views import PerfilView, PortalLoginView, media_protegida

urlpatterns = [
    path("", TemplateView.as_view(template_name="landing.html"), name="landing"),
    path("login/", PortalLoginView.as_view(), name="login"),
    path("perfil/", PerfilView.as_view(), name="perfil"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("panel/", include("dashboard.urls")),
    path("r/", include("onboarding.urls")),
    # Archivos subidos: siempre por la app (con permisos), también en producción.
    path("media/<path:ruta>", media_protegida, name="media"),
]
