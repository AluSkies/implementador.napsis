"""Piezas de seguridad compartidas por el login (usadas por django-axes)."""

from django.conf import settings


def ip_del_cliente(request):
    """IP real del cliente, detrás de nuestro proxy reverso.

    El límite de intentos de login cuenta fallos por (IP, usuario). Detrás de un
    proxy, REMOTE_ADDR es siempre la IP del proxy: sin esto todos los usuarios
    compartirían la misma IP. El proxy agrega al final de X-Forwarded-For la IP que
    le habló, así que la del cliente es la N-ésima desde la DERECHA, con N =
    TRUSTED_PROXY_COUNT (cantidad de proxies nuestros en el camino). Lo que venga
    más a la izquierda lo escribe el cliente y se ignora: no se puede evadir el
    límite inventando un X-Forwarded-For.

    Si no hay proxy configurado (N=0) o el header no trae suficientes entradas,
    se usa REMOTE_ADDR, que no se puede falsificar.
    """
    saltos = settings.TRUSTED_PROXY_COUNT
    reenviadas = [
        ip.strip() for ip in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if ip.strip()
    ]
    if saltos > 0 and len(reenviadas) >= saltos:
        return reenviadas[-saltos]
    return request.META.get("REMOTE_ADDR")
