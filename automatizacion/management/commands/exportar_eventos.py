"""Exporta el registro de eventos a JSONL (una línea JSON por evento), por ejemplo para entrenar o
auditar. Es una decisión explícita: nada sale solo del portal."""

import json
import sys

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.dateparse import parse_date

from automatizacion.models import EventoImplementacion


class Command(BaseCommand):
    help = "Exporta los eventos de las implementaciones a un archivo JSONL (o a la salida estándar)."

    def add_arguments(self, parser):
        parser.add_argument("--desde", help="Fecha inicial (AAAA-MM-DD), inclusive.")
        parser.add_argument("--hasta", help="Fecha final (AAAA-MM-DD), inclusive.")
        parser.add_argument("--implementacion", help="uuid de una implementación.")
        parser.add_argument("--salida", help="Archivo de salida. Sin esto, escribe en la salida estándar.")

    def handle(self, *args, **opciones):
        eventos = EventoImplementacion.objects.all()
        for clave, filtro in (("desde", "momento__date__gte"), ("hasta", "momento__date__lte")):
            if opciones[clave]:
                fecha = parse_date(opciones[clave])
                if not fecha:
                    raise CommandError(f"--{clave} tiene que ser una fecha AAAA-MM-DD.")
                eventos = eventos.filter(**{filtro: fecha})
        if opciones["implementacion"]:
            eventos = eventos.filter(implementacion_uuid=opciones["implementacion"])

        salida = open(opciones["salida"], "w", encoding="utf-8") if opciones["salida"] else None
        cantidad = 0
        try:
            for e in eventos.iterator():
                linea = json.dumps({
                    "id": e.id, "momento": e.momento, "implementacion": e.implementacion_uuid,
                    "actor_tipo": e.actor_tipo, "actor_ref": e.actor_ref, "accion": e.accion,
                    "seccion": e.seccion, "datos": e.datos, "origen": e.origen,
                    "correlation_id": e.correlation_id, "post_envio": e.post_envio,
                    "version_esquema": e.version_esquema,
                }, cls=DjangoJSONEncoder, ensure_ascii=False)
                if opciones["salida"]:
                    salida.write(linea + "\n")
                else:
                    sys.stdout.write(linea + "\n")
                cantidad += 1
        finally:
            if opciones["salida"]:
                salida.close()
        if opciones["salida"]:
            self.stderr.write(f"{cantidad} eventos exportados a {opciones['salida']}.")
