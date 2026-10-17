"""Carga el catálogo global de licencias, novedades y documentos de legajo.

Vivía como migración de datos (catalog/migrations/0002_seed_catalogos.py),
pero eso hacía que "manage.py migrate" —y por lo tanto la base de datos de
test, que se arma corriendo todas las migraciones— insertara este catálogo
siempre. Correrlo como comando aparte deja las bases de test limpias, y en
desarrollo/producción se corre una sola vez después de migrar.

Es seguro correrlo de nuevo (usa get_or_create): no duplica filas si ya
existen, y no revierte activaciones/tipos "Otros" que haya cargado un cliente.
"""

from django.core.management.base import BaseCommand

from catalog.models import CampoDocumento, TipoDocumento, TipoLicencia, TipoNovedad

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


class Command(BaseCommand):
    help = (
        "Carga el catálogo global de licencias, novedades y documentos de legajo SOLO en lo que "
        "todavía está vacío: lo que ya se cargó o corrigió desde el admin no se toca."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--completar", action="store_true",
            help="Agrega lo que falte de la lista original aunque el catálogo ya tenga datos "
                 "(puede volver a crear algo que se haya borrado o renombrado a propósito).",
        )

    def handle(self, *args, **options):
        # Se corre en cada arranque del contenedor. Si sembrara siempre, un nombre corregido en
        # el admin ("Prestamo" -> "Préstamo") quedaría duplicado y lo borrado reaparecería.
        completar = options["completar"]
        sembrar_licencias = completar or not TipoLicencia.objects.exists()
        sembrar_novedades = completar or not TipoNovedad.objects.exists()
        sembrar_documentos = completar or not TipoDocumento.objects.filter(implementacion=None).exists()

        for i, nombre in enumerate(LICENCIAS if sembrar_licencias else []):
            TipoLicencia.objects.get_or_create(nombre=nombre, defaults={"orden": i})

        for i, nombre in enumerate(NOVEDADES if sembrar_novedades else []):
            TipoNovedad.objects.get_or_create(nombre=nombre, defaults={"orden": i})

        for i, (nombre, requiere_firma, campos) in enumerate(TIPOS_DOCUMENTO if sembrar_documentos else []):
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

        omitidos = [
            nombre for nombre, sembro in (
                ("licencias", sembrar_licencias), ("novedades", sembrar_novedades), ("documentos", sembrar_documentos),
            ) if not sembro
        ]
        self.stdout.write(self.style.SUCCESS(
            f"Catálogo listo: {len(LICENCIAS)} licencias, {len(NOVEDADES)} novedades, "
            f"{len(TIPOS_DOCUMENTO)} tipos de documento."
            + (f" Ya tenían datos y no se tocaron: {', '.join(omitidos)}." if omitidos else "")
        ))
