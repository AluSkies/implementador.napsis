from contextlib import contextmanager

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Case, DateField, IntegerField, OuterRef, Subquery, Value, When
from django.db.models.functions import Cast, Coalesce, Greatest
from django.utils.crypto import get_random_string
from django.utils.dateparse import parse_date
from django.utils.text import slugify

from automatizacion import eventos

from .models import Implementacion, ImplementacionVersion, RondaRevision


def generar_password():
    """Contraseña temporal legible para compartirle al cliente (no queda guardada en texto plano)."""
    return get_random_string(10, allowed_chars="abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789")


def crear_o_resetear_acceso(cliente, username=None, email=""):
    """Crea (o resetea la contraseña de) la cuenta con la que el cliente inicia sesión.
    Devuelve (username, password_en_claro) — la contraseña solo se puede ver esta vez.

    Si es una cuenta nueva y se da un `email`, queda sin contraseña (no hay nada que pasar a
    mano): el cliente la crea con el link de la invitación y la password devuelta es None."""
    invitar = bool(email) and not cliente.usuario
    password = None if invitar else generar_password()

    if cliente.usuario:
        cliente.usuario.set_password(password)
        cliente.usuario.is_staff = False
        cliente.usuario.save()
        return cliente.usuario.username, password

    base = slugify(username or cliente.nombre) or "cliente"
    candidato = base
    sufijo = 1
    while User.objects.filter(username=candidato).exists():
        sufijo += 1
        candidato = f"{base}{sufijo}"

    usuario = User.objects.create_user(
        username=candidato, password=password, email=email if invitar else "", is_staff=False,
    )
    cliente.usuario = usuario
    cliente.save(update_fields=["usuario"])
    return usuario.username, password

COLUMNAS_ORDENABLES = {
    "cliente": "cliente__nombre",
    "estado": "estado_orden",
    "fecha_implementacion": "fecha_implementacion",
    "creado": "creado",
}


def con_ultimo_movimiento(queryset):
    """Agrega `movimiento_en` (cuándo fue lo último que pasó) a cada implementación, sin una consulta por fila."""
    from automatizacion.models import EventoImplementacion

    ultimo_evento = Subquery(
        EventoImplementacion.objects.filter(implementacion=OuterRef("pk")).order_by("-momento").values("momento")[:1]
    )
    return queryset.annotate(movimiento_en=Greatest(Coalesce(ultimo_evento, "creado"), "creado"))


def filtrar_y_ordenar_implementaciones(queryset, params):
    """Aplica al listado del panel los filtros y el orden que vengan por querystring
    (?cliente=&estado=&creado_desde=&creado_hasta=&fecha_impl_desde=&fecha_impl_hasta=&ordenar=&direccion=).
    """
    queryset = con_ultimo_movimiento(queryset).annotate(
        estado_orden=Case(
            When(estado=Implementacion.ESTADO_CANCELADA, then=Value(4)),
            When(estado=Implementacion.ESTADO_CUMPLIDA, then=Value(3)),
            When(validada_en__isnull=False, then=Value(2)),
            When(enviado__isnull=False, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        ronda_abierta_numero=Subquery(
            RondaRevision.objects.filter(implementacion=OuterRef("pk"), respondida_en__isnull=True)
            .order_by("-numero").values("numero")[:1]
        ),
        fecha_implementacion=Coalesce(
            Cast("cumplida_en", DateField()), "fecha_salida_productivo", output_field=DateField()
        ),
    )

    cliente_q = params.get("cliente", "").strip()
    if cliente_q:
        queryset = queryset.filter(cliente__nombre__icontains=cliente_q)

    estado = params.get("estado", "")
    if estado in Implementacion.VISUAL_LABELS:
        queryset = queryset.filter(Implementacion.filtro_visual(estado))
    elif estado == Implementacion.SIN_MOVIMIENTO:
        queryset = queryset.filter(
            estado=Implementacion.ESTADO_PENDIENTE, movimiento_en__lte=Implementacion.limite_sin_movimiento(),
        )

    creado_desde = parse_date(params.get("creado_desde", ""))
    if creado_desde:
        queryset = queryset.filter(creado__date__gte=creado_desde)
    creado_hasta = parse_date(params.get("creado_hasta", ""))
    if creado_hasta:
        queryset = queryset.filter(creado__date__lte=creado_hasta)

    fecha_impl_desde = parse_date(params.get("fecha_impl_desde", ""))
    if fecha_impl_desde:
        queryset = queryset.filter(fecha_implementacion__gte=fecha_impl_desde)
    fecha_impl_hasta = parse_date(params.get("fecha_impl_hasta", ""))
    if fecha_impl_hasta:
        queryset = queryset.filter(fecha_implementacion__lte=fecha_impl_hasta)

    ordenar = params.get("ordenar", "creado")
    if ordenar not in COLUMNAS_ORDENABLES:
        ordenar = "creado"
    direccion = params.get("direccion", "desc" if ordenar == "creado" else "asc")
    campo_orden = COLUMNAS_ORDENABLES[ordenar]
    if direccion == "desc":
        campo_orden = f"-{campo_orden}"

    return queryset.order_by(campo_orden)


def resumen_implementacion(implementacion):
    """Contexto de solo lectura con todo lo relevado en una implementación, reutilizado
    tanto por el panel interno como por la vista de consulta del cliente."""
    return {
        "implementacion": implementacion,
        "cliente": implementacion.cliente,
        "modulos_activos": implementacion.modulos.filter(activo=True).select_related("modulo"),
        "roles": implementacion.roles.all(),
        "sucursales": implementacion.sucursales.all(),
        "licencias_activas": implementacion.licencias.filter(activo=True).select_related("tipo_licencia"),
        "novedades_activas": implementacion.novedades.filter(activo=True).select_related("tipo_novedad"),
        "liquidaciones_activas": implementacion.liquidaciones.filter(activo=True).select_related("tipo_liquidacion").order_by("tipo_liquidacion__orden", "tipo_liquidacion__nombre"),
        "firma": implementacion.firma,
        "documentos_activos": implementacion.documentos_legajo.filter(activo=True).select_related("tipo_documento"),
        "empleados": implementacion.empleados.select_related("sucursal", "reporta_a", "aprobador"),
        "versiones": implementacion.versiones.all()[:50],
    }


# --- Historial de versiones ------------------------------------------------
# Antes de aplicar un cambio en una sección, se guarda una foto de cómo estaba
# esa sección, para que el cliente y el equipo puedan consultar versiones anteriores.

def _snapshot_datos_contacto(implementacion):
    return {
        "Razón social": implementacion.cliente.razon_social,
        "CUIT(s)": implementacion.cliente.cuits,
        "Teléfono": implementacion.telefono,
        "Mail de contacto": implementacion.mail_contacto,
        "Tipo de firma": implementacion.get_tipo_firma_display(),
        "Liquidador utilizado": implementacion.liquidador_utilizado,
        "Nomenclatura de PDFs": implementacion.nomenclatura_pdf,
        "Cantidad de capitas": implementacion.cantidad_capitas,
        "Segmentación liquidador": implementacion.segmentacion_liquidador,
        "Logo": implementacion.logo.url if implementacion.logo else None,
        "Banner": implementacion.banner.url if implementacion.banner else None,
        "Modelo de recibo": implementacion.modelo_recibo.url if implementacion.modelo_recibo else None,
    }


def _snapshot_modulos(implementacion):
    return {im.modulo.nombre: im.activo for im in implementacion.modulos.select_related("modulo")}


def _snapshot_roles(implementacion):
    return [
        {"Rol": r.get_rol_display(), "Apellido y Nombre": r.apellido_nombre, "CUIL": r.cuil, "Mail": r.mail}
        for r in implementacion.roles.all()
    ]


def _snapshot_sucursales(implementacion):
    return [
        {
            "Nombre": s.nombre, "Calle": s.calle, "Altura": s.altura, "Piso/depto": s.piso_depto,
            "CP": s.codigo_postal, "Localidad": s.localidad, "Entre calles": s.entre_calles,
            "Observaciones": s.observaciones,
        }
        for s in implementacion.sucursales.all()
    ]


def _snapshot_licencias_novedades(implementacion):
    return {
        "Licencias": {l.tipo_licencia.nombre: l.activo for l in implementacion.licencias.select_related("tipo_licencia")},
        "Novedades": {n.tipo_novedad.nombre: n.activo for n in implementacion.novedades.select_related("tipo_novedad")},
    }


def _snapshot_liquidaciones(implementacion):
    return {
        liq.tipo_liquidacion.nombre: liq.activo for liq in implementacion.liquidaciones.select_related("tipo_liquidacion")
    }


def _snapshot_firma(implementacion):
    firma = implementacion.firma
    if firma is None:
        return {}
    foto = {
        "Estado": firma.get_estado_display(),
        "Página": firma.get_pagina_display(),
        "Imagen": firma.imagen.url if firma.imagen else None,
        "Imagen (sha256)": firma.imagen_sha256,
    }
    for codigo, nombre in firma.ELEMENTOS:
        recuadro = firma.geometria.get(codigo, {})
        foto[nombre] = {campo: recuadro.get(campo) for campo in ("x", "y", "ancho", "alto")}
    if firma.motivos:
        foto["Motivos"] = firma.motivos_texto
        foto["Comentario"] = firma.comentario
    return foto


def _snapshot_documentos(implementacion):
    return {d.tipo_documento.nombre: d.activo for d in implementacion.documentos_legajo.select_related("tipo_documento")}


def _snapshot_condiciones(implementacion):
    return {
        "Tipo de firma": (
            "Que lo elija el cliente" if implementacion.tipo_firma_editable
            else implementacion.get_tipo_firma_display()
        ),
        "Nomenclatura de PDFs": (
            "Que la defina el cliente" if implementacion.nomenclatura_editable else implementacion.nomenclatura_pdf
        ),
        "Solo Área única": "No" if implementacion.segmentacion_editable else "Sí",
        "Máximo de personas con rol": implementacion.max_roles,
    }


def _snapshot_fecha_implementacion(implementacion):
    return {
        "Fecha estimada de salida en productivo": implementacion.fecha_salida_productivo,
    }


# "empleados" no está acá: Empleado es un modelo de la app employees, así que es esa
# app la que registra su propio snapshot builder (ver registrar_snapshot_builder).
_SNAPSHOT_BUILDERS = {
    "datos_contacto": _snapshot_datos_contacto,
    "modulos": _snapshot_modulos,
    "roles": _snapshot_roles,
    "sucursales": _snapshot_sucursales,
    "licencias_novedades": _snapshot_licencias_novedades,
    "liquidaciones": _snapshot_liquidaciones,
    "firma": _snapshot_firma,
    "documentos": _snapshot_documentos,
    "fecha_implementacion": _snapshot_fecha_implementacion,
    "condiciones": _snapshot_condiciones,
}


def registrar_snapshot_builder(seccion, builder):
    """Permite que otra app registre cómo tomar la foto de una sección que ella
    misma posee (ej. "empleados", dueño de employees), sin que este módulo tenga
    que importar esa app y conocer la forma de sus modelos."""
    _SNAPSHOT_BUILDERS[seccion] = builder


def _fresca(implementacion):
    """La implementación tal como está en la base ahora. Las fotos se toman de acá y no del objeto
    que llega: ese puede venir con datos ya modificados por un formulario (Django escribe en la
    instancia al validar) o con relaciones precargadas que quedan viejas después de guardar."""
    return Implementacion.objects.select_related("cliente").get(pk=implementacion.pk)


def foto_de_seccion(implementacion, seccion):
    """Cómo está hoy una sección (el mismo formato que usa el historial de versiones)."""
    return _SNAPSHOT_BUILDERS[seccion](_fresca(implementacion))


def guardar_version(implementacion, seccion, actor):
    """Guarda una foto del estado ACTUAL de una sección, antes de que se le aplique un cambio."""
    return ImplementacionVersion.objects.create(
        implementacion=implementacion, seccion=seccion,
        datos=_SNAPSHOT_BUILDERS[seccion](_fresca(implementacion)), editado_por=actor.etiqueta,
    )


# Estas secciones no forman parte de lo que se configura: cambiarlas no invalida una validación.
SECCIONES_QUE_NO_INVALIDAN = {"fecha_implementacion"}


def revocar_validacion(implementacion, actor, seccion):
    """Si la implementación ya estaba validada y alguien cambia algo de lo que se va a configurar, vuelve
    a «Documentación completa - Pendiente de validación»: no se configura con datos distintos a los que
    se aprobaron. (La `ConfiguracionCongelada` anterior queda como historia.) Devuelve si revocó."""
    revocadas = Implementacion.objects.filter(
        pk=implementacion.pk, estado=Implementacion.ESTADO_PENDIENTE, validada_en__isnull=False,
    ).update(validada_en=None)
    if not revocadas:
        return False
    implementacion.validada_en = None
    eventos.registrar(actor, "estado.validacion_revocada", implementacion, seccion=seccion)
    return True


@contextmanager
def cambio_de_seccion(implementacion, seccion, actor, accion="paso.guardado", datos=None):
    """Envuelve el guardado de una sección: deja la foto anterior en el historial, deja que el
    llamador aplique el cambio y registra el evento con lo que cambió (antes y después). Todo en
    una sola transacción: o queda el cambio completo con su historia, o no queda nada."""
    with transaction.atomic():
        antes = guardar_version(implementacion, seccion, actor).datos
        yield
        despues = _SNAPSHOT_BUILDERS[seccion](_fresca(implementacion))
        cambios = eventos.diferencias(antes, despues)
        eventos.registrar(actor, accion, implementacion, seccion=seccion, datos={**(datos or {}), "cambios": cambios})
        if cambios and seccion not in SECCIONES_QUE_NO_INVALIDAN:
            revocar_validacion(implementacion, actor, seccion)
