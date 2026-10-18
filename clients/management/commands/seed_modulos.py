"""Carga el catálogo de módulos contratables.

Antes esto vivía repartido en dos migraciones de datos (0002_seed_modulos,
que sembraba el catálogo original, y 0007_actualizar_catalogo_modulos, que
lo corregía después: renombró "Legajo" a "Legajos", sacó "Autogestión" y
agregó "Novedades"). Correrlo como comando aparte evita que "manage.py
migrate" —usado también para armar la base de datos de test— siembre este
catálogo automáticamente, y deja el estado final en un solo lugar en vez de
tener que leer el historial completo de migraciones para saber cuál es.

Es seguro correrlo de nuevo: solo crea los módulos que falten y no modifica los que ya existen
(los nombres están cableados en el wizard, ver PASO_REQUIERE_MODULO, y el orden se puede ajustar
desde el admin sin que un reinicio lo deshaga).
"""

from django.core.management.base import BaseCommand

from clients.models import Modulo

# (código estable, nombre visible). El código es lo que usa el wizard; el nombre se puede corregir en el admin.
MODULOS = [
    (Modulo.RECIBO_DIGITAL, "Recibo Digital"),
    (Modulo.COMUNICACION, "Comunicación"),
    (Modulo.FICHADA, "Fichada"),
    (Modulo.LEGAJOS, "Legajos"),
    (Modulo.NOVEDADES, "Novedades"),
]


class Command(BaseCommand):
    help = "Carga (o completa) el catálogo de módulos contratables."

    def handle(self, *args, **options):
        for i, (codigo, nombre) in enumerate(MODULOS):
            if Modulo.objects.filter(codigo=codigo).exists():
                continue
            # Una base armada antes de los códigos puede tener el módulo con ese nombre y sin código.
            existente = Modulo.objects.filter(nombre=nombre, codigo=None).first()
            if existente:
                existente.codigo = codigo
                existente.save(update_fields=["codigo"])
            else:
                Modulo.objects.create(codigo=codigo, nombre=nombre, orden=i)

        self.stdout.write(self.style.SUCCESS(f"Catálogo de módulos listo: {len(MODULOS)} módulos."))
