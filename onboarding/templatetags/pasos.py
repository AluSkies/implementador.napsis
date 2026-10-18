from django import template

from onboarding.services import TOTAL_PASOS

register = template.Library()


@register.simple_tag
def total_pasos():
    """Cantidad de pasos del wizard, para mostrar «paso N/total» sin escribir el número a mano."""
    return TOTAL_PASOS
