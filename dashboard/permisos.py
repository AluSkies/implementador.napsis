"""Roles del equipo de Napsis.

- **Implementador**: cuenta de staff (`is_staff`) que no es superusuario. Trabaja el panel:
  implementaciones, clientes, nómina, etc.
- **Admin**: superusuario. Puede todo lo anterior y además administrar a los
  implementadores (alta, modificación y baja).

Los clientes son cuentas sin `is_staff` y no entran al panel.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import resolve_url


def admin_requerido(vista):
    """Restringe una vista al rol Admin.

    Sin sesión de staff manda al login. Con sesión de implementador responde 403 en vez de
    redirigir al login: el login lo devolvería al mismo panel (ya está autenticado) y se
    armaría un loop de redirecciones.
    """

    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        usuario = request.user
        if not (usuario.is_authenticated and usuario.is_active and usuario.is_staff):
            return redirect_to_login(request.get_full_path(), login_url=resolve_url("login"))
        if not usuario.is_superuser:
            raise PermissionDenied
        return vista(request, *args, **kwargs)

    return envoltura
