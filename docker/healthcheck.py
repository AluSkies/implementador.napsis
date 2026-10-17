"""Healthcheck del contenedor: pide /salud/ a la app y falla si no responde 200.

Hay que presentarse con un Host válido (el primero de DJANGO_ALLOWED_HOSTS) y como si
llegara por HTTPS: sin eso Django rechazaría el pedido (400) o lo redirigiría a https.
Eso sí verifica algo útil: que la app atiende y que llega a la base de datos.
"""

import os
import sys
import urllib.request

hosts = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
host = next((h for h in hosts if not h.startswith(".") and h != "*"), "localhost")

pedido = urllib.request.Request(
    "http://127.0.0.1:8000/salud/", headers={"Host": host, "X-Forwarded-Proto": "https"},
)
try:
    with urllib.request.urlopen(pedido, timeout=5) as respuesta:
        sys.exit(0 if respuesta.status == 200 else 1)
except Exception:
    sys.exit(1)
