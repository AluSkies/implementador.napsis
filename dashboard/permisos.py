"""Roles del equipo de Napsis y qué implementaciones ve y toca cada uno.

- **Implementador**: cuenta de staff (`is_staff`) que no es superusuario. Ve y actúa solo sobre las
  implementaciones que tiene asignadas.
- **Supervisor**: un implementador que además pertenece al grupo de Django `Supervisor`. Ve las suyas y las de los
  integrantes de los grupos de trabajo que tiene a cargo (`GrupoDeTrabajo`), y actúa sobre todas las que ve. Es
  quien las asigna, pero solo dentro de su equipo. No ve las de otros supervisores ni las de sus equipos.
- **Admin**: superusuario. Ve y puede todo, incluidas las implementaciones sin asignar, y además administra las
  cuentas del equipo (alta, modificación, baja y rol de cada una, el de Admin incluido) y sus grupos.

La regla de qué se ve vive en `implementaciones_visibles`: todo lo demás (listado, ficha, descargas, exportación,
ficha de la empresa) pasa por ella, para que no haya un camino que se la salte.

Los clientes son cuentas sin `is_staff` y no entran al panel.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import resolve_url

from automatizacion.actores import es_supervisor
from clients.models import Cliente, Implementacion


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


def implementaciones_visibles(usuario):
    """Las implementaciones que el usuario puede ver: todas el admin; el supervisor, las suyas y las de los
    integrantes de sus grupos; el implementador, las que tiene asignadas. Las que no tienen asignado solo las ve el
    admin. Una cuenta que no es del equipo no ve ninguna."""
    if not (getattr(usuario, "is_authenticated", False) and usuario.is_staff):
        return Implementacion.objects.none()
    if usuario.is_superuser:
        return Implementacion.objects.all()
    if es_supervisor(usuario):
        return Implementacion.objects.filter(
            Q(implementador_asignado=usuario) | Q(implementador_asignado__membresia__grupo__supervisor=usuario)
        )
    return Implementacion.objects.filter(implementador_asignado=usuario)


def puede_ver(usuario, implementacion):
    return implementaciones_visibles(usuario).filter(pk=implementacion.pk).exists()


def puede_accionar(usuario, implementacion):
    """Quién puede actuar sobre una implementación: el supervisor y el admin sobre todas las que ven; el
    implementador, sobre las que tiene asignadas (que son las únicas que ve)."""
    if not puede_ver(usuario, implementacion):
        return False
    return puede_asignar(usuario) or implementacion.implementador_asignado_id == usuario.pk


def clientes_visibles(usuario):
    """Las empresas con alguna implementación que el usuario ve (el admin ve todas)."""
    if usuario.is_superuser:
        return Cliente.objects.all()
    return Cliente.objects.filter(pk__in=implementaciones_visibles(usuario).values("cliente_id"))


def puede_accionar_sobre_el_cliente(usuario, cliente):
    """Para las acciones de la ficha de la empresa (acceso, invitación): el admin, o quien ve alguna
    implementación de esa empresa."""
    if usuario.is_superuser:
        return True
    return implementaciones_visibles(usuario).filter(cliente=cliente).exists()
