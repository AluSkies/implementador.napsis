from django.db import migrations


class Migration(migrations.Migration):
    """Mueve ImplementacionLicencia/Novedad/TipoDocumento a la app clients, donde ya
    vivían PersonaRol y Sucursal — consolida en un solo lugar todos los modelos de
    datos por-paso del wizard, en vez de tenerlos repartidos entre dos apps.

    Solo toca el estado de migraciones de esta app (no la base): el rename real de
    las tablas lo hace la migración de clients que depende de esta.
    """

    dependencies = [
        ("onboarding", "0002_remove_implementacionlicencia_fecha_activacion_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="ImplementacionLicencia"),
                migrations.DeleteModel(name="ImplementacionNovedad"),
                migrations.DeleteModel(name="ImplementacionTipoDocumento"),
            ],
            database_operations=[],
        ),
    ]
