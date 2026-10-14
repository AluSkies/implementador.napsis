from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Q
from django.http import FileResponse, Http404
from django.urls import reverse_lazy

from .models import Implementacion


class PortalLoginView(LoginView):
    """Login único del portal. Redirige según el tipo de cuenta: staff al panel
    interno, clientes a su listado de implementaciones."""

    template_name = "login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        next_url = self.get_redirect_url()
        es_staff = self.request.user.is_staff
        # Un "next" hacia /panel/ para un cliente (o viceversa) rebotaría de
        # nuevo contra el control de permisos y armaría un loop con el propio
        # login — en ese caso preferimos el destino por defecto según el rol.
        if next_url and next_url.startswith("/panel/") == es_staff:
            return next_url
        if es_staff:
            return str(reverse_lazy("dashboard:home"))
        return str(reverse_lazy("onboarding:mis_implementaciones"))


@login_required
def media_protegida(request, ruta):
    """Sirve los archivos subidos (banner, modelo de recibo, planillas importadas).

    El equipo (staff) accede a cualquiera; un cliente solo al banner y al modelo de
    recibo de sus propias implementaciones. Cualquier otro caso devuelve 404 (no 403)
    para no revelar si el archivo existe. Así el proxy reverso no necesita servir
    /media/ por su cuenta: la app es la única que decide quién ve qué.
    """
    base = Path(settings.MEDIA_ROOT).resolve()
    archivo = (base / ruta).resolve()
    if not archivo.is_relative_to(base) or not archivo.is_file():
        raise Http404

    if not request.user.is_staff:
        cliente = getattr(request.user, "cliente", None)
        nombre = archivo.relative_to(base).as_posix()
        propio = cliente is not None and Implementacion.objects.filter(
            Q(banner=nombre) | Q(modelo_recibo=nombre), cliente=cliente
        ).exists()
        if not propio:
            raise Http404

    return FileResponse(archivo.open("rb"))
