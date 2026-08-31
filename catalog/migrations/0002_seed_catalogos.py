from django.db import migrations

# Esta migración sembraba el catálogo global (licencias/novedades/documentos)
# insertando datos directamente. Se pasó a un comando de management
# (catalog/management/commands/seed_catalogos.py) para que "manage.py migrate"
# —que también arma la base de datos de test— no siembre datos reales cada vez.
#
# Se deja como no-op (en vez de borrar el archivo) porque bases ya existentes
# tienen esta migración marcada como aplicada, y otras migraciones dependen de
# su nombre — no toca nada en una base que ya la corrió.


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
