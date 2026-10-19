"""Fecha de implementación: el mínimo que se le exige al cliente y el cálculo de días hábiles."""

from datetime import timedelta

from django.utils import timezone

# El cliente solo puede pedir una fecha de implementación a partir de tantos días hábiles
# (lunes a viernes; no se descuentan feriados). El equipo de implementación puede poner
# cualquier fecha desde el panel.
DIAS_HABILES_MINIMOS_CLIENTE = 10


def sumar_dias_habiles(desde, cantidad):
    """La fecha que queda `cantidad` días hábiles (lunes a viernes) después de `desde`."""
    fecha = desde
    while cantidad > 0:
        fecha += timedelta(days=1)
        if fecha.weekday() < 5:
            cantidad -= 1
    return fecha


def fecha_minima_para_cliente(hoy=None):
    """Primera fecha de implementación que el cliente puede pedir."""
    return sumar_dias_habiles(hoy or timezone.localdate(), DIAS_HABILES_MINIMOS_CLIENTE)
