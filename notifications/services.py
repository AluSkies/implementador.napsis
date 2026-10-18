import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)


def _resumen_dict(implementacion):
    cliente = implementacion.cliente
    modulos_activos = [
        implementacion_modulo.modulo.nombre
        for implementacion_modulo in implementacion.modulos.filter(activo=True)
    ]
    liquidaciones_activas = [
        liq.tipo_liquidacion.nombre for liq in implementacion.liquidaciones.filter(activo=True).select_related("tipo_liquidacion").order_by("tipo_liquidacion__orden", "tipo_liquidacion__nombre")
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
        "liquidaciones": ", ".join(liquidaciones_activas),
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


def _base_url(base_url=None):
    """La URL pública del portal: la que llegó en el pedido o, sin ella, la de la configuración."""
    return (base_url or settings.SITE_BASE_URL).rstrip("/")


def _detalle_url(implementacion, base_url=None):
    try:
        return _base_url(base_url) + reverse("dashboard:implementacion_detalle", kwargs={"pk": implementacion.pk})
    except Exception:
        return settings.SITE_BASE_URL


def _enviar_mail_equipo(asunto, template, contexto, destinatarios):
    """Envía un mail al equipo de implementación, o lo omite si no hay destinatarios.
    Devuelve la lista de destinatarios (vacía si no se envió)."""
    if not destinatarios:
        logger.warning("Sin destinatarios (IMPLEMENTATION_TEAM_EMAILS vacío y sin implementador asignado); se omite el mail.")
        return []

    send_mail(
        subject=asunto,
        message=render_to_string(template, contexto),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=destinatarios,
        fail_silently=False,
    )
    return destinatarios


def notificar_implementacion_completa(implementacion, base_url=None):
    """Le avisa por mail al equipo de implementación que un cliente envió su relevamiento.
    Devuelve los destinatarios del mail (vacía si no se envió)."""
    contexto = {"detalle_url": _detalle_url(implementacion, base_url), **_resumen_dict(implementacion)}
    return _enviar_mail_equipo(
        f"Nueva implementación completada: {implementacion.cliente.nombre}",
        "notifications/mail_resumen.txt", contexto, _destinatarios(implementacion),
    )


def notificar_revision_solicitada(implementacion, base_url=None):
    """El cliente pidió que lo contacten: avisa por mail al equipo de implementación."""
    contexto = {
        "razon_social": implementacion.cliente.razon_social or implementacion.cliente.nombre,
        "mensaje": implementacion.revision_mensaje,
        "detalle_url": _detalle_url(implementacion, base_url),
    }
    return _enviar_mail_equipo(
        f"Pedido de contacto: {implementacion.cliente.nombre}",
        "notifications/mail_revision_solicitada.txt", contexto, _destinatarios(implementacion),
    )


def mail_del_cliente(implementacion):
    """A dónde escribirle al cliente: el mail de contacto de la implementación o, si no, el de
    su cuenta. Vacío si no hay ninguno (en ese caso no se le manda nada)."""
    usuario = implementacion.cliente.usuario
    return implementacion.mail_contacto or (usuario.email if usuario else "")


def _enviar_mail_cliente(asunto, template, contexto, destinatario):
    """Le escribe al cliente. Devuelve a quién (None si no hay mail cargado y no se mandó nada)."""
    if not destinatario:
        logger.info("El cliente no tiene mail cargado; se omite: %s", asunto)
        return None
    send_mail(
        subject=asunto, message=render_to_string(template, contexto),
        from_email=settings.DEFAULT_FROM_EMAIL, recipient_list=[destinatario], fail_silently=False,
    )
    return destinatario


def enviar_invitacion(usuario, base_url=None):
    """Le manda al cliente un link para crear (o cambiar) su contraseña. El link vence a los
    `PASSWORD_RESET_TIMEOUT` segundos y se anula al usarlo. No toca la contraseña actual."""
    base = _base_url(base_url)
    link = base + reverse("clave_confirmar", kwargs={
        "uidb64": urlsafe_base64_encode(force_bytes(usuario.pk)),
        "token": default_token_generator.make_token(usuario),
    })
    return _enviar_mail_cliente(
        "Tu acceso al Portal de Implementación de Napsis", "notifications/mail_invitacion.txt",
        {"usuario": usuario, "link": link, "login_url": base + reverse("login"),
         "dias": settings.PASSWORD_RESET_TIMEOUT // 86400},
        usuario.email,
    )


def notificar_cliente_relevamiento_recibido(implementacion, base_url=None):
    """Confirma al cliente que Napsis recibió su relevamiento. Devuelve a quién se lo mandó."""
    cliente = implementacion.cliente
    return _enviar_mail_cliente(
        "Recibimos tu información", "notifications/mail_cliente_recibido.txt",
        {"razon_social": cliente.razon_social or cliente.nombre, "implementador": implementacion.asignado_nombre,
         "link": _base_url(base_url) + reverse("login")},
        mail_del_cliente(implementacion),
    )


def notificar_cliente_devuelta(implementacion, ronda, base_url=None):
    """Le cuenta al cliente qué tiene que corregir o completar. Devuelve a quién se lo mandó."""
    from onboarding.services import CODIGO_DE_PASO, TITULOS_PASO

    titulo_de = {codigo: TITULOS_PASO[paso] for paso, codigo in CODIGO_DE_PASO.items()}
    cliente = implementacion.cliente
    return _enviar_mail_cliente(
        "Necesitamos que revises algunos datos de tu implementación", "notifications/mail_cliente_devuelta.txt",
        {"razon_social": cliente.razon_social or cliente.nombre, "implementador": implementacion.asignado_nombre,
         "motivo": ronda.motivo,
         "observaciones": [(titulo_de.get(codigo, codigo), texto) for codigo, texto in ronda.observaciones.items()],
         "link": _base_url(base_url) + implementacion.get_absolute_url()},
        mail_del_cliente(implementacion),
    )


def notificar_cliente_implementacion_cumplida(implementacion, base_url=None):
    """Le avisa al cliente que su implementación está lista. Devuelve a quién se lo mandó."""
    cliente = implementacion.cliente
    return _enviar_mail_cliente(
        "Tu implementación está lista", "notifications/mail_cliente_cumplida.txt",
        {"razon_social": cliente.razon_social or cliente.nombre, "implementador": implementacion.asignado_nombre,
         "link": _base_url(base_url) + reverse("login")},
        mail_del_cliente(implementacion),
    )
