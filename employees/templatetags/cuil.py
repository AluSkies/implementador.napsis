from django import template

from employees.services import formatear_cuil

register = template.Library()


@register.filter(name="cuil")
def cuil_con_guiones(valor):
    """Muestra un CUIL como NN-NNNNNNNN-N, lo haya escrito la persona con guiones o sin ellos."""
    return formatear_cuil(valor)
