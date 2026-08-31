import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Contraparte de onboarding/migrations/0003: da de alta en el estado de clients
    los modelos ImplementacionLicencia/Novedad/TipoDocumento (mismos campos que tenían
    en onboarding) y renombra las tablas físicas para que coincidan con la app nueva.
    No se pierden datos — es un rename de tabla, no un create/drop.
    """

    dependencies = [
        ("clients", "0008_cliente_usuario"),
        ("onboarding", "0003_mover_modelos_a_clients"),
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ImplementacionLicencia",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("activo", models.BooleanField(default=False)),
                        ("implementacion", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="licencias", to="clients.implementacion")),
                        ("tipo_licencia", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalog.tipolicencia")),
                    ],
                    options={
                        "verbose_name": "Licencia de la implementación",
                        "verbose_name_plural": "Licencias de la implementación",
                        "unique_together": {("implementacion", "tipo_licencia")},
                    },
                ),
                migrations.CreateModel(
                    name="ImplementacionNovedad",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("activo", models.BooleanField(default=False)),
                        ("implementacion", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="novedades", to="clients.implementacion")),
                        ("tipo_novedad", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalog.tiponovedad")),
                    ],
                    options={
                        "verbose_name": "Novedad de la implementación",
                        "verbose_name_plural": "Novedades de la implementación",
                        "unique_together": {("implementacion", "tipo_novedad")},
                    },
                ),
                migrations.CreateModel(
                    name="ImplementacionTipoDocumento",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("activo", models.BooleanField(default=False)),
                        ("implementacion", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documentos_legajo", to="clients.implementacion")),
                        ("tipo_documento", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="catalog.tipodocumento")),
                    ],
                    options={
                        "verbose_name": "Documento de legajo de la implementación",
                        "verbose_name_plural": "Documentos de legajo de la implementación",
                        "unique_together": {("implementacion", "tipo_documento")},
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE onboarding_implementacionlicencia RENAME TO clients_implementacionlicencia;",
                    reverse_sql="ALTER TABLE clients_implementacionlicencia RENAME TO onboarding_implementacionlicencia;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE onboarding_implementacionnovedad RENAME TO clients_implementacionnovedad;",
                    reverse_sql="ALTER TABLE clients_implementacionnovedad RENAME TO onboarding_implementacionnovedad;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE onboarding_implementaciontipodocumento RENAME TO clients_implementaciontipodocumento;",
                    reverse_sql="ALTER TABLE clients_implementaciontipodocumento RENAME TO onboarding_implementaciontipodocumento;",
                ),
            ],
        ),
    ]
