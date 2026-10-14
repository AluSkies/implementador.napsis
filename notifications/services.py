import logging

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def _resumen_dict(implementacion):
    cliente = implementacion.cliente
    modulos_activos = [
        implementacion_modulo.modulo.nombre
        for implementacion_modulo in implementacion.modulos.filter(activo=True)
    ]
    licencias_activas = [
        implementacion_licencia.tipo_licencia.nombre
        for implementacion_licencia in implementacion.licencias.filter(activo=True)
    ]
    novedades_activas = [
        implementacion_novedad.tipo_novedad.nombre
        for implementacion_novedad in implementacion.novedades.filter(activo=True)
    ]
    documentos_activos = [
        implementacion_documento.tipo_documento.nombre
        for implementacion_documento in implementacion.documentos_legajo.filter(activo=True)
    ]
    return {
        "razon_social": cliente.razon_social or cliente.nombre,
        "nombre": cliente.nombre,
        "cuits": cliente.cuits,
        "implementador": implementacion.asignado_nombre,
        "mail_contacto": implementacion.mail_contacto,
        "telefono": implementacion.telefono,
        "modulos": ", ".join(modulos_activos),
        "licencias": ", ".join(licencias_activas),
        "novedades": ", ".join(novedades_activas),
        "documentos_legajo": ", ".join(documentos_activos),
        "cantidad_empleados": implementacion.empleados.count(),
        "cantidad_sucursales": implementacion.sucursales.count(),
        "roles": ", ".join(
            f"{r.get_rol_display()}: {r.apellido_nombre}" for r in implementacion.roles.all()
        ),
    }


def _destinatarios(implementacion):
    """El equipo (lista fija) más el implementador asignado, sin repetir."""
    asignado = implementacion.implementador_asignado
    extra = [asignado.email] if asignado and asignado.email else []
    return list(dict.fromkeys([*settings.IMPLEMENTATION_TEAM_EMAILS, *extra]))


def _detalle_url(implementacion, request=None):
    try:
        path = reverse("dashboard:implementacion_detalle", kwargs={"pk": implementacion.pk})
        base = request.build_absolute_uri("/") if request else settings.SITE_BASE_URL
        return base.rstrip("/") + path
    except Exception:
        return settings.SITE_BASE_URL


def _enviar_mail_equipo(asunto, template, contexto, destinatarios):
    """Envía un mail al equipo de implementación, o lo omite si no hay destinatarios."""
    if not destinatarios:
        logger.warning("Sin destinatarios (IMPLEMENTATION_TEAM_EMAILS vacío y sin implementador asignado); se omite el mail.")
        return

    send_mail(
        subject=asunto,
        message=render_to_string(template, contexto),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=destinatarios,
        fail_silently=False,
    )


def notificar_implementacion_completa(implementacion, request=None):
    """Dispara el mail al equipo de implementación y el dump a Google Sheets."""
    contexto = {"detalle_url": _detalle_url(implementacion, request), **_resumen_dict(implementacion)}
    _enviar_mail_equipo(
        f"Nueva implementación completada: {implementacion.cliente.nombre}",
        "notifications/mail_resumen.txt", contexto, _destinatarios(implementacion),
    )
    _enviar_a_google_sheets(implementacion)


def notificar_revision_solicitada(implementacion, request=None):
    """El cliente pidió que lo contacten: avisa por mail al equipo de implementación."""
    contexto = {
        "razon_social": implementacion.cliente.nombre,
        "mensaje": implementacion.revision_mensaje,
        "detalle_url": _detalle_url(implementacion, request),
    }
    _enviar_mail_equipo(
        f"Pedido de contacto: {implementacion.cliente.nombre}",
        "notifications/mail_revision_solicitada.txt", contexto, _destinatarios(implementacion),
    )


def _enviar_a_google_sheets(implementacion):
    if not settings.GOOGLE_SHEETS_WEBHOOK_URL:
        logger.info("GOOGLE_SHEETS_WEBHOOK_URL no configurado; se omite el dump a Sheets.")
        return

    payload = _resumen_dict(implementacion)
    try:
        response = requests.post(settings.GOOGLE_SHEETS_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception(
            "Falló el POST al webhook de Google Sheets para la implementación %s", implementacion.pk
        )
