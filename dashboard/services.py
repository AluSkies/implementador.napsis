"""Gestión de las cuentas de implementadores (el rol Admin las administra desde el panel)."""

from django.contrib.auth.models import Group, User
from django.db.models import Count, Q

from automatizacion.actores import GRUPO_SUPERVISOR
from clients.services import generar_password

ROL_IMPLEMENTADOR = "implementador"
ROL_SUPERVISOR = "supervisor"
ROLES = ((ROL_IMPLEMENTADOR, "Implementador"), (ROL_SUPERVISOR, "Supervisor"))


def implementadores():
    """Cuentas con rol Implementador o Supervisor: staff que no es superusuario. Los admins y los
    clientes no aparecen acá, así que no se pueden tocar por esta vía. `es_supervisor` dice cuál de los dos."""
    return (
        User.objects.filter(is_staff=True, is_superuser=False)
        .annotate(creadas=Count("implementaciones_generadas", distinct=True))
        .annotate(es_supervisor=Count("groups", filter=Q(groups__name=GRUPO_SUPERVISOR), distinct=True))
        .order_by("-is_active", "username")
    )


def asignables():
    """Cuentas a las que se puede asignar una implementación: todo el equipo activo
    (implementadores y admins)."""
    return User.objects.filter(is_staff=True, is_active=True).order_by("first_name", "username")


def asignar_rol(usuario, rol):
    """Deja a la cuenta como Implementador o como Supervisor (pertenencia al grupo Supervisor)."""
    grupo, _ = Group.objects.get_or_create(name=GRUPO_SUPERVISOR)
    if rol == ROL_SUPERVISOR:
        usuario.groups.add(grupo)
    else:
        usuario.groups.remove(grupo)


def crear_implementador(username, first_name, last_name, email, rol=ROL_IMPLEMENTADOR):
    """Crea la cuenta (Implementador o Supervisor) con una contraseña generada. Devuelve
    (usuario, password_en_claro): la contraseña solo se puede ver esta vez."""
    password = generar_password()
    usuario = User.objects.create_user(
        username=username, email=email, password=password,
        first_name=first_name, last_name=last_name,
        is_staff=True, is_superuser=False,
    )
    asignar_rol(usuario, rol)
    return usuario, password


def resetear_password(usuario):
    """Nueva contraseña generada; la anterior (y las sesiones abiertas) dejan de valer."""
    password = generar_password()
    usuario.set_password(password)
    usuario.save(update_fields=["password"])
    return password


def dar_de_baja(usuario):
    """Baja lógica: no puede ingresar, pero la cuenta se conserva. Se mantiene en vez de
    borrarla para no perder a quién se atribuyen las implementaciones que creó."""
    usuario.is_active = False
    usuario.save(update_fields=["is_active"])


def reactivar(usuario):
    usuario.is_active = True
    usuario.save(update_fields=["is_active"])
