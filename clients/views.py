from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy


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
