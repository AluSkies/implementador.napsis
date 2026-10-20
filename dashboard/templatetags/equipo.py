from django import template

from automatizacion.actores import es_supervisor

register = template.Library()


@register.filter
def rol_del_equipo(usuario):
    """El nombre del rol de una cuenta de staff, para mostrarlo en el encabezado."""
    if usuario.is_superuser:
        return "Admin"
    return "Supervisor" if es_supervisor(usuario) else "Implementador"
