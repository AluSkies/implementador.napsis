"""Roles del equipo de Napsis.

- **Implementador**: cuenta de staff (`is_staff`) que no es superusuario. Ve todas las implementaciones, pero
  solo actúa (edita, valida, comenta...) sobre las que tiene asignadas.
- **Supervisor**: un implementador que además pertenece al grupo `Supervisor`. Actúa sobre todas las
  implementaciones y es quien las asigna a los demás.
- **Admin**: superusuario. Puede todo lo anterior y además administrar las cuentas del equipo
  (alta, modificación, baja y rol de cada una).

Los clientes son cuentas sin `is_staff` y no entran al panel.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import resolve_url

from automatizacion.actores import es_supervisor


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


def puede_asignar(usuario):
    """Quién reparte las implementaciones: el supervisor y el admin."""
    return usuario.is_superuser or es_supervisor(usuario)


def puede_accionar(usuario, implementacion):
    """Quién puede actuar sobre una implementación: el supervisor y el admin sobre todas; el implementador
    solo sobre las que tiene asignadas. Ver una puede cualquiera del equipo."""
    return puede_asignar(usuario) or implementacion.implementador_asignado_id == usuario.pk


def puede_accionar_sobre_el_cliente(usuario, cliente):
    """Para las acciones de la ficha de la empresa (acceso, invitación): quien puede asignar o quien tiene
    asignada alguna implementación de esa empresa."""
    return puede_asignar(usuario) or cliente.implementaciones.filter(implementador_asignado=usuario).exists()
