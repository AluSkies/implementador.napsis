import hashlib
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    LoginView, PasswordChangeView, PasswordResetCompleteView, PasswordResetConfirmView,
    PasswordResetDoneView, PasswordResetView,
)
from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse
from django.urls import reverse_lazy

from .forms import RecuperarClaveForm
from .security import ip_del_cliente
from .models import Implementacion


class PerfilView(LoginRequiredMixin, PasswordChangeView):
    """Autogestión de la cuenta ("Mi perfil"), igual para clientes y equipo. Por ahora solo
    permite cambiar la contraseña; el cambio mantiene abierta la sesión actual."""

    template_name = "perfil.html"
    success_url = reverse_lazy("perfil")

    def form_valid(self, form):
        messages.success(self.request, "Tu contraseña se cambió correctamente.")
        return super().form_valid(form)


class RecuperarClaveView(PasswordResetView):
    """"Olvidé mi contraseña": manda un link por mail (vale lo mismo que el de la invitación)."""

    template_name = "clave/recuperar.html"
    email_template_name = "clave/mail_recuperar.txt"
    subject_template_name = "clave/mail_recuperar_asunto.txt"
    form_class = RecuperarClaveForm
    success_url = reverse_lazy("clave_enviada")

    # Tope de pedidos (para que nadie use el portal para llenar de mails una casilla ajena ni
    # para ocupar a los workers): el mismo mail, una vez cada 10 minutos; una misma IP, hasta 10.
    VENTANA_SEGUNDOS = 10 * 60
    MAXIMO_POR_IP = 10

    def _dentro_del_limite(self, email):
        huella = hashlib.sha256(email.strip().lower().encode()).hexdigest()
        ip = hashlib.sha256((ip_del_cliente(self.request) or "?").encode()).hexdigest()
        # `add` solo crea la clave si no existía: es el "primer pedido" de este mail.
        if not cache.add(f"clave-mail-{huella}", 1, self.VENTANA_SEGUNDOS):
            return False
        clave_ip = f"clave-ip-{ip}"
        cache.add(clave_ip, 0, self.VENTANA_SEGUNDOS)
        try:
            return cache.incr(clave_ip) <= self.MAXIMO_POR_IP
        except ValueError:  # la clave venció justo ahora
            return True

    def form_valid(self, form):
        if not self._dentro_del_limite(form.cleaned_data["email"]):
            # Misma respuesta que si se hubiera mandado: no se revela nada, solo no se reenvía.
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class ClaveEnviadaView(PasswordResetDoneView):
    template_name = "clave/enviada.html"


class ClaveConfirmarView(PasswordResetConfirmView):
    """Donde cae el link del mail: sirve tanto para crear la contraseña (invitación) como
    para cambiarla. Al terminar manda al login."""

    template_name = "clave/confirmar.html"
    success_url = reverse_lazy("clave_lista")


class ClaveListaView(PasswordResetCompleteView):
    template_name = "clave/lista.html"


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
    """Sirve los archivos subidos (logo, banner, modelo de recibo, firma, planillas importadas).

    El equipo (staff) accede a cualquiera; un cliente solo al logo, al banner, a la firma y al modelo de
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
            Q(banner=nombre) | Q(logo=nombre) | Q(modelo_recibo=nombre) | Q(firmas__imagen=nombre), cliente=cliente
        ).exists()
        if not propio:
            raise Http404

    return FileResponse(archivo.open("rb"))


def salud(request):
    """Chequeo de salud para el monitoreo y el healthcheck del contenedor: responde 200 solo si
    la app llega a la base. Sin login ni datos: solo "ok" o 503."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"estado": "error"}, status=503)
    return JsonResponse({"estado": "ok"})
