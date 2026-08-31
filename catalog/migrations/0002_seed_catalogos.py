from django.db import migrations

LICENCIAS = [
    "Día de Cumpleaños",
    "Licencia CON Goce de Sueldo",
    "Licencia por Accidente de Trabajo (ART)",
    "Licencia por Donación de Sangre",
    "Licencia por Enfermedad",
    "Licencia por Examen",
    "Licencia por Excedencia",
    "Licencia por Fallecimiento",
    "Licencia por Maternidad",
    "Licencia por Matrimonio",
    "Licencia por Mudanza",
    "Licencia por Nacimiento",
    "Licencia por Paternidad",
    "Licencia por reserva de puesto",
    "Licencia SIN Goce de Sueldo",
    "Vacaciones",
]

NOVEDADES = [
    "Almuerzo",
    "Anticipo de Haberes",
    "Gastos de Guardería",
    "Gimnasio",
    "Horas Extra",
    "Horas Extra al 50%",
    "Horas Extra al 100%",
    "Prestamo",
    "SUBE",
    "Viáticos",
]

# (nombre_documento, requiere_firma, [(nombre_campo, obligatorio, max_adjuntos), ...])
TIPOS_DOCUMENTO = [
    ("DDJJ DOM", False, [
        ("CALLE", True, 1), ("DIRECCION/Altura", True, 1), ("PLANTA/VIVIENDA", False, 1),
        ("LOCALIDAD", True, 1), ("PROVINCIA", False, 1), ("CODIGO POSTAL", True, 1),
        ("ENTRE CALLES", False, 1), ("OBSERVACIONES", False, 1), ("ADJUNTO", True, 1),
    ]),
    ("CUENTA BANCARIA (CBU)", False, [
        ("NOMBRE DEL TITULAR", True, 1), ("BANCO", True, 1), ("NUMERO DE CUENTA", False, 1),
        ("CBU", True, 1), ("ALIAS", False, 1), ("FORMA DE PAGO", True, 1), ("ADJUNTO", True, 1),
    ]),
    ("OBRA SOCIAL", False, [
        ("NOMBRE DE LA OBRA SOCIAL", False, 1), ("NUMERO DE AFILIADO", False, 1),
        ("NOMBRE DEL PLAN DE COBERTURA", False, 1), ("TIPO DE AFILIACION", False, 1),
        ("PARENTESCO/VINCULO", False, 1), ("ADJUNTO", False, 1),
    ]),
    ("PREPAGA", False, [
        ("NOMBRE PREPAGA", True, 1), ("APELLIDO", True, 1), ("NOMBRE", True, 1),
        ("PARENTESCO/VINCULO", False, 1), ("NUMERO DE AFILIADO", False, 1),
        ("NOMBRE DEL PLAN", False, 1), ("TIPO DE AFILIACIÓN", True, 1), ("ADJUNTO", False, 1),
    ]),
    ("DNI", False, [
        ("NUMERO DE DOCUMENTO", True, 1), ("SEXO", True, 1), ("NACIONALIDAD", True, 1),
        ("NUMERO DEL EJEMPLAR", False, 1), ("NUMERO DE TRAMITE", False, 1), ("ADJUNTO", True, 1),
    ]),
    ("CONSTANCIA DE CUIL", False, [("ADJUNTO", True, 1)]),
    ("FORMACION", False, [
        ("FECHA DE INICIO", True, 1), ("FECHA DE FINALIZACION", False, 1),
        ("FECHA DE EMISION", True, 1), ("INSTITUCION", True, 1), ("NIVEL DE ESTUDIO", True, 1),
        ("TITULO", True, 1), ("ESTADO", True, 1), ("ADJUNTO", True, 1),
    ]),
    ("VACUNACION", False, [
        ("FECHA DE VACUNACION", True, 1), ("TIPO DE VACUNA RECIBIDA", True, 1),
        ("MARCA RECIBIDA", False, 1), ("N° DOSIS", False, 1), ("ADJUNTO", False, 1),
    ]),
    ("CURRICULUM VITAE", False, [("ADJUNTO", True, 1)]),
    ("FAMILIARES", False, [
        ("NOMBRE", True, 1), ("APELLIDO", True, 1), ("PARENTESCO/VINCULO", True, 1),
        ("SEXO", True, 1), ("FECHA DE NACIMIENTO", True, 1), ("EDAD", False, 1),
        ("DNI", False, 1), ("ADJUNTO", False, 3),
    ]),
    ("SVO", False, [
        ("APELLIDO", True, 1), ("NOMBRE", True, 1), ("CUIL", True, 1),
        ("FECHA DE NACIMIENTO", True, 1), ("% BENEFICIARIO", True, 1), ("ADJUNTO", False, 1),
    ]),
    ("ART", False, [("ADJUNTO", True, 1)]),
    ("ELEMENTOS DE TRABAJO", False, [
        ("ELEMENTO DE TRABAJO", True, 1), ("MARCA DEL ELEMENTO", False, 1),
        ("MODELO DEL ELEMENTO", True, 1), ("FECHA DE ENTREGA", True, 1),
        ("FECHA DE VENCIMIENTO", False, 1), ("MOTIVO DE LA ENTREGA", False, 1),
        ("OBSERVACIONES", False, 1), ("ADJUNTO", True, 1),
    ]),
    ("CUD", False, [
        ("FECHA DE EMISION", True, 1), ("FECHA DE VENCIMIENTO", True, 1),
        ("REQUIERE ACOMPAÑANTE/ASISTENTE", True, 1), ("ADJUNTO", True, 1),
    ]),
    ("FACTURA INTERNET", False, [
        ("PROVEEDOR DEL SERVICIO", True, 1), ("FECHA DE CARGA", True, 1),
        ("PERIODO DE FACTURACION", True, 1), ("MONTO DEL SERVICIO", True, 1), ("ADJUNTO", True, 1),
    ]),
    ("GASTOS DE GUARDERIA", False, [
        ("TIPO DE SERVICIO", True, 1), ("FECHA DE CARGA", True, 1),
        ("PERIODO DE FACTURACION", True, 1), ("MONTO DEL SERVICIO", True, 1),
        ("DNI HIJO/A", True, 1), ("APELLIDO/NOMBRE HIJO/A", True, 1),
        ("EDAD DEL HIJO/A", True, 1), ("PRIMERA VEZ EN EL AÑO", True, 1),
        ("PADRE/MADRE PERCIBE EL BENEFICIO", True, 1), ("ADJUNTO", True, 3),
    ]),
]


def seed(apps, schema_editor):
    TipoLicencia = apps.get_model("catalog", "TipoLicencia")
    TipoNovedad = apps.get_model("catalog", "TipoNovedad")
    TipoDocumento = apps.get_model("catalog", "TipoDocumento")
    CampoDocumento = apps.get_model("catalog", "CampoDocumento")

    for i, nombre in enumerate(LICENCIAS):
        TipoLicencia.objects.get_or_create(nombre=nombre, defaults={"orden": i})

    for i, nombre in enumerate(NOVEDADES):
        TipoNovedad.objects.get_or_create(nombre=nombre, defaults={"orden": i})

    for i, (nombre, requiere_firma, campos) in enumerate(TIPOS_DOCUMENTO):
        tipo, _ = TipoDocumento.objects.get_or_create(
            nombre=nombre,
            implementacion=None,
            defaults={"es_custom": False, "requiere_firma": requiere_firma, "orden": i},
        )
        for j, (campo_nombre, obligatorio, max_adjuntos) in enumerate(campos):
            CampoDocumento.objects.get_or_create(
                tipo_documento=tipo,
                nombre=campo_nombre,
                defaults={
                    "obligatorio": obligatorio,
                    "permite_multiples_adjuntos": max_adjuntos,
                    "orden": j,
                },
            )


def unseed(apps, schema_editor):
    TipoLicencia = apps.get_model("catalog", "TipoLicencia")
    TipoNovedad = apps.get_model("catalog", "TipoNovedad")
    TipoDocumento = apps.get_model("catalog", "TipoDocumento")

    TipoLicencia.objects.filter(nombre__in=LICENCIAS).delete()
    TipoNovedad.objects.filter(nombre__in=NOVEDADES).delete()
    TipoDocumento.objects.filter(
        nombre__in=[n for n, *_ in TIPOS_DOCUMENTO], implementacion=None
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
