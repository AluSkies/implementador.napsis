"""Aviso por mail cuando la app tiene un error 500.

Se engancha al logger `django.request` (ver LOGGING en config/settings.py), que es donde
Django registra cada error interno. Dos cuidados:

- **Un mail por tipo de error cada 10 minutos.** Si algo se rompe (la base caída, por ejemplo),
  cada pedido daría un 500: sin tope serían cientos de mails, y cada uno haría esperar al
  usuario por el SMTP.
- **Sin datos del pedido.** El mail trae el error y dónde ocurrió, pero no el cuerpo del POST
  (que puede tener datos personales de la nómina ni contraseñas).

Los imports de Django van adentro de las funciones: el logging se configura al arrancar,
antes de que las apps estén cargadas.
"""

import hashlib
import logging
import traceback

logger = logging.getLogger("notifications.alertas")

INTERVALO_SEGUNDOS = 10 * 60


class AlertaErrorHandler(logging.Handler):
    def emit(self, record):
        try:
            self._avisar(record)
        except Exception:
            # Un problema avisando nunca puede empeorar el error original.
            logger.warning("No se pudo enviar la alerta de error por mail.", exc_info=True)

    def _avisar(self, record):
        from django.conf import settings
        from django.core.cache import cache
        from django.core.mail import send_mail

        destinatarios = settings.ERROR_ALERT_EMAILS
        if not destinatarios or not record.exc_info:
            return

        tipo, valor, tb = record.exc_info
        marcos = traceback.extract_tb(tb)
        donde = f"{marcos[-1].filename}:{marcos[-1].lineno}" if marcos else "?"
        firma = hashlib.sha1(f"{tipo.__name__}|{donde}".encode()).hexdigest()
        if not cache.add(f"alerta-error-{firma}", 1, INTERVALO_SEGUNDOS):
            return  # ya avisamos de este error hace poco

        request = getattr(record, "request", None)
        usuario = getattr(getattr(request, "user", None), "username", "") or "anónimo"
        pedido = f"{request.method} {request.path}" if request is not None else "(sin pedido)"
        cuerpo = (
            f"Error interno en el Portal de Implementación.\n\n"
            f"Pedido: {pedido}\nUsuario: {usuario}\nError: {tipo.__name__}: {valor}\n\n"
            f"Traceback:\n{''.join(traceback.format_exception(tipo, valor, tb))}\n"
            f"(Se avisa una vez cada 10 minutos por tipo de error. El detalle completo está en el log "
            f"del contenedor: docker compose logs app)\n"
        )
        send_mail(
            subject=f"[Portal Napsis] Error 500: {tipo.__name__} en {pedido}",
            message=cuerpo, from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=list(destinatarios), fail_silently=False,
        )
