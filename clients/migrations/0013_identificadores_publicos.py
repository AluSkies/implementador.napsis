import uuid

from django.db import migrations, models


def asignar_uuid(apps, schema_editor):
    """Cada implementación que ya existía recibe su propio uuid (el default se evalúa una sola vez
    al agregar la columna, así que sin esto todas tendrían el mismo)."""
    Implementacion = apps.get_model("clients", "Implementacion")
    for pk in Implementacion.objects.values_list("pk", flat=True):
        Implementacion.objects.filter(pk=pk).update(uuid=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ("clients", "0012_codigos_estables"),
    ]

    operations = [
        migrations.AddField(
            model_name="implementacion",
            name="uuid",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(asignar_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="implementacion",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="implementacion",
            name="origen",
            field=models.CharField(
                choices=[("portal", "Creada en el portal"), ("hubspot", "HubSpot"), ("api", "API")],
                default="portal", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="implementacion",
            name="id_externo",
            field=models.CharField(
                blank=True, help_text="Por ejemplo, el ID del deal en el CRM. Único por origen.",
                max_length=100, null=True, verbose_name="ID en el sistema de origen",
            ),
        ),
        migrations.AddConstraint(
            model_name="implementacion",
            constraint=models.UniqueConstraint(
                fields=("origen", "id_externo"), name="implementacion_origen_id_externo_unico",
            ),
        ),
    ]
