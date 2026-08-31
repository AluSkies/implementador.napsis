"""Carga el catálogo de módulos contratables.

Antes esto vivía repartido en dos migraciones de datos (0002_seed_modulos,
que sembraba el catálogo original, y 0007_actualizar_catalogo_modulos, que
lo corregía después: renombró "Legajo" a "Legajos", sacó "Autogestión" y
agregó "Novedades"). Correrlo como comando aparte evita que "manage.py
migrate" —usado también para armar la base de datos de test— siembre este
catálogo automáticamente, y deja el estado final en un solo lugar en vez de
tener que leer el historial completo de migraciones para saber cuál es.

Es seguro correrlo de nuevo (usa get_or_create/update_or_create).
"""

from django.core.management.base import BaseCommand

from clients.models import Modulo

MODULOS = ["Recibo Digital", "Comunicación", "Fichada", "Legajos", "Novedades"]


class Command(BaseCommand):
    help = "Carga (o completa) el catálogo de módulos contratables."

    def handle(self, *args, **options):
        for i, nombre in enumerate(MODULOS):
            Modulo.objects.update_or_create(nombre=nombre, defaults={"orden": i})

        self.stdout.write(self.style.SUCCESS(f"Catálogo de módulos listo: {len(MODULOS)} módulos."))
