from django.db import migrations

# Corregía el catálogo de módulos ya sembrado por 0002 (renombraba "Legajo" a
# "Legajos", sacaba "Autogestión", agregaba "Novedades"). El estado final ya
# está reflejado directamente en clients/management/commands/seed_modulos.py,
# así que esta migración queda como no-op — ver el mismo comentario en
# clients/migrations/0002_seed_modulos.py.


class Migration(migrations.Migration):
    dependencies = [("clients", "0006_alter_implementacionversion_seccion")]
    operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
