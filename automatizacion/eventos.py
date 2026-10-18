"""Registro de los eventos de las implementaciones."""

from . import actores, correlacion
from .models import EventoImplementacion


def registrar(actor, accion, implementacion=None, *, seccion="", datos=None, post_envio=None, origen=None):
    """Guarda un evento. Se llama desde los servicios, dentro de la misma transacción que el cambio.

    - `post_envio` se calcula solo: es verdadero si actúa alguien que no es el cliente y la
      implementación ya fue enviada. Se puede forzar pasándolo explícito.
    - Los `datos` tienen que ser serializables a JSON (fechas y UUID están contemplados).
    """
    if post_envio is None:
        post_envio = bool(
            implementacion is not None and implementacion.enviado and actor.tipo != actores.CLIENTE
        )
    if origen is None:
        sistema = actor.tipo == actores.SISTEMA
        origen = EventoImplementacion.ORIGEN_SISTEMA if sistema else EventoImplementacion.ORIGEN_WEB
    return EventoImplementacion.objects.create(
        implementacion=implementacion,
        implementacion_uuid=implementacion.uuid if implementacion is not None else None,
        actor_tipo=actor.tipo, actor_ref=actor.ref, accion=accion, seccion=seccion,
        datos=datos or {}, origen=origen, correlation_id=correlacion.actual(), post_envio=post_envio,
    )


def diferencias(antes, despues, prefijo=""):
    """Lo que cambió entre dos fotos de una sección: {campo: {"antes": a, "despues": d}}.

    Las fotos son diccionarios (se compara campo por campo, y los diccionarios anidados con el
    camino "Grupo › campo") o listas (se compara la lista entera, bajo el campo "lista"). Si no
    cambió nada, devuelve un diccionario vacío."""
    if not (isinstance(antes, dict) and isinstance(despues, dict)):
        return {} if antes == despues else {prefijo or "lista": {"antes": antes, "despues": despues}}
    cambios = {}
    for campo in list(antes) + [c for c in despues if c not in antes]:
        a, d = antes.get(campo), despues.get(campo)
        nombre = f"{prefijo} › {campo}" if prefijo else str(campo)
        if isinstance(a, dict) and isinstance(d, dict):
            cambios.update(diferencias(a, d, nombre))
        elif a != d:
            cambios[nombre] = {"antes": a, "despues": d}
    return cambios
