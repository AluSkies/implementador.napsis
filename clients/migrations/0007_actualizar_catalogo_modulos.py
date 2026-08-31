from django.db import migrations

ORDEN_NUEVO = ["Recibo Digital", "Comunicación", "Fichada", "Legajos", "Novedades"]


def actualizar_modulos(apps, schema_editor):
    Modulo = apps.get_model("clients", "Modulo")
    ImplementacionModulo = apps.get_model("clients", "ImplementacionModulo")

    # "Legajo" pasa a llamarse "Legajos" (se renombra in-place para conservar
    # las activaciones ya cargadas en implementaciones existentes).
    Modulo.objects.filter(nombre="Legajo").update(nombre="Legajos")

    # "Autogestión" deja de ser un módulo del catálogo.
    autogestion = Modulo.objects.filter(nombre="Autogestión").first()
    if autogestion:
        ImplementacionModulo.objects.filter(modulo=autogestion).delete()
        autogestion.delete()

    # "Novedades" es un módulo nuevo.
    Modulo.objects.get_or_create(nombre="Novedades")

    for i, nombre in enumerate(ORDEN_NUEVO):
        Modulo.objects.filter(nombre=nombre).update(orden=i)


def revertir(apps, schema_editor):
    Modulo = apps.get_model("clients", "Modulo")
    Modulo.objects.filter(nombre="Legajos").update(nombre="Legajo")
    Modulo.objects.filter(nombre="Novedades").delete()
    Modulo.objects.get_or_create(nombre="Autogestión", defaults={"orden": 1})


class Migration(migrations.Migration):
    dependencies = [("clients", "0006_alter_implementacionversion_seccion")]
    operations = [migrations.RunPython(actualizar_modulos, revertir)]
