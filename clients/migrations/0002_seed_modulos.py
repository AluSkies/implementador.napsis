from django.db import migrations

MODULOS = [
    "Recibo Digital",
    "Autogestión",
    "Comunicación",
    "Legajo",
    "Fichada",
]


def seed(apps, schema_editor):
    Modulo = apps.get_model("clients", "Modulo")
    for i, nombre in enumerate(MODULOS):
        Modulo.objects.get_or_create(nombre=nombre, defaults={"orden": i})


def unseed(apps, schema_editor):
    Modulo = apps.get_model("clients", "Modulo")
    Modulo.objects.filter(nombre__in=MODULOS).delete()


class Migration(migrations.Migration):
    dependencies = [("clients", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
