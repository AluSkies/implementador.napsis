from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from django.views.generic import TemplateView

from clients.views import PortalLoginView

urlpatterns = [
    path("", TemplateView.as_view(template_name="landing.html"), name="landing"),
    path("login/", PortalLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("panel/", include("dashboard.urls")),
    path("r/", include("onboarding.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
