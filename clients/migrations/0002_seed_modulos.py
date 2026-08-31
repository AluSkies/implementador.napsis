from django.db import migrations

# Sembraba el catálogo de módulos. Se pasó a un comando de management
# (clients/management/commands/seed_modulos.py) — ver el mismo comentario en
# catalog/migrations/0002_seed_catalogos.py. Se deja como no-op por la misma
# razón: no tocar bases que ya la tienen aplicada.


class Migration(migrations.Migration):
    dependencies = [("clients", "0001_initial")]
    operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
