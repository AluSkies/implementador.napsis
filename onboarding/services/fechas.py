"""Fecha de implementación: el mínimo que se le exige al cliente y el cálculo de días hábiles."""

from datetime import timedelta

from django.utils import timezone

# Los primeros tantos días hábiles (lunes a viernes; no se descuentan feriados) no se pueden pedir:
# el cliente elige desde el día hábil siguiente. El equipo de implementación puede poner
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
    """Primera fecha de implementación que el cliente puede pedir: los primeros DIAS_HABILES_MINIMOS_CLIENTE
    días hábiles (el décimo incluido) quedan bloqueados, así que es el día hábil siguiente."""
    return sumar_dias_habiles(hoy or timezone.localdate(), DIAS_HABILES_MINIMOS_CLIENTE + 1)
