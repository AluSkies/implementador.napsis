"""Identificador que une todo lo que pasó en un mismo pedido (eventos, errores en el log)."""

import contextvars
import logging
import re
import uuid

_actual = contextvars.ContextVar("correlacion_id", default="")
_VALIDO = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def actual():
    return _actual.get()


def nueva():
    """Abre una correlación nueva en el contexto actual (para comandos y tareas fuera de un pedido web)."""
    valor = uuid.uuid4().hex
    _actual.set(valor)
    return valor


def desde_encabezado(valor):
    """Acepta el X-Request-ID que mande el proxy si tiene un formato razonable; si no, genera uno."""
    return valor if valor and _VALIDO.match(valor) else uuid.uuid4().hex


class CorrelacionMiddleware:
    """Asigna un id a cada pedido y lo devuelve en el encabezado X-Request-ID."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        valor = desde_encabezado(request.META.get("HTTP_X_REQUEST_ID", ""))
        token = _actual.set(valor)
        try:
            respuesta = self.get_response(request)
        finally:
            _actual.reset(token)
        respuesta["X-Request-ID"] = valor
        return respuesta


class CorrelacionFilter(logging.Filter):
    """Agrega el id a cada línea del log, para poder buscar en el log lo que pasó en un pedido."""

    def filter(self, record):
        record.correlacion = actual() or "-"
        return True
