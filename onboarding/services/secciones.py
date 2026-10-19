"""Guardado de las secciones simples de una implementación (datos, módulos, sucursales, licencias,
liquidaciones, documentos, condiciones y fecha).

Cada función de guardado registra primero una versión anterior (clients.services.guardar_version)
con el estado previo de la sección, así el cliente y el equipo pueden consultarlas después, y deja
el evento con el antes y el después. Las usan por igual el wizard del cliente y el panel del equipo,
para que apliquen exactamente las mismas reglas."""

from catalog.models import TipoDocumento, TipoLiquidacion
from clients.models import (
    ImplementacionLicencia,
    ImplementacionLiquidacion,
    ImplementacionNovedad,
    ImplementacionTipoDocumento,
    Modulo,
    Sucursal,
)
from clients.services import cambio_de_seccion


def guardar_condiciones(implementacion, form, actor):
    """Aplica las condiciones del proceso (form = CondicionesForm ya validado) registrando antes
    la versión anterior."""
    with cambio_de_seccion(implementacion, "condiciones", actor, accion="implementacion.condiciones_actualizadas"):
        form.aplicar(implementacion)
        implementacion.save()


def guardar_fecha_implementacion(implementacion, fecha, actor):
    """Guarda la fecha de salida en productivo (None la borra), registrando antes la versión
    anterior. Lo usan el cliente (con su mínimo) y el panel (sin límite)."""
    with cambio_de_seccion(implementacion, "fecha_implementacion", actor, accion="implementacion.fecha_cambiada"):
        implementacion.fecha_salida_productivo = fecha
        implementacion.save(update_fields=["fecha_salida_productivo"])


def tipos_documento_disponibles(implementacion):
    """Catálogo global de documentos + los tipos 'Otros' que esta implementación agregó."""
    tipos_qs = TipoDocumento.objects.filter(implementacion=None).prefetch_related("campos")
    otros_qs = TipoDocumento.objects.filter(implementacion=implementacion, es_custom=True).prefetch_related("campos")
    return list(tipos_qs) + list(otros_qs)


def estado_actual_licencias(implementacion):
    return {lic.tipo_licencia_id: {"activo": lic.activo} for lic in implementacion.licencias.all()}


def estado_actual_novedades(implementacion):
    return {nov.tipo_novedad_id: {"activo": nov.activo} for nov in implementacion.novedades.all()}


def estado_actual_documentos(implementacion):
    return {doc.tipo_documento_id: {"activo": doc.activo} for doc in implementacion.documentos_legajo.all()}


def guardar_datos_contacto(implementacion, form, actor):
    """Guarda un formulario de datos de la implementación (contacto, empresa o configuración)."""
    with cambio_de_seccion(implementacion, "datos_contacto", actor):
        form.save()


def guardar_modulos(implementacion, modulos_qs, activos_ids, actor):
    """Guarda qué módulos tiene la implementación. Recibo Digital es el corazón del producto: va en
    todas, no se puede sacar (ni el cliente ni el equipo)."""
    with cambio_de_seccion(implementacion, "modulos", actor):
        for modulo in modulos_qs:
            activo = modulo.id in activos_ids or modulo.codigo == Modulo.RECIBO_DIGITAL
            implementacion.modulos.update_or_create(modulo=modulo, defaults={"activo": activo})


def guardar_sucursales(implementacion, formset, actor):
    """Guarda las sucursales conservando las que siguen existiendo (se reconocen por el nombre):
    antes se borraban todas y se recreaban, y cada empleado perdía la sucursal que tenía asignada
    cada vez que el cliente volvía a guardar este paso."""
    with cambio_de_seccion(implementacion, "sucursales", actor):
        existentes = {}
        for sucursal in implementacion.sucursales.all():
            existentes.setdefault(sucursal.nombre.strip().lower(), sucursal)

        conservadas = set()
        for form in formset:
            if form.cleaned_data.get("DELETE"):
                continue
            if not any(form.cleaned_data.get(f) for f in ("nombre", "calle", "localidad")):
                continue
            datos = {k: v for k, v in form.cleaned_data.items() if k != "DELETE"}
            clave = datos.get("nombre", "").strip().lower()
            sucursal = existentes.get(clave) if clave and clave not in conservadas else None
            if sucursal:
                for campo, valor in datos.items():
                    setattr(sucursal, campo, valor)
                sucursal.save()
            else:
                sucursal = Sucursal.objects.create(implementacion=implementacion, **datos)
            conservadas.add(clave)
            existentes[clave] = sucursal

        mantener = [s.pk for s in existentes.values() if s.nombre.strip().lower() in conservadas]
        implementacion.sucursales.exclude(pk__in=mantener).delete()


def guardar_licencias_y_novedades(implementacion, form, licencias_qs, novedades_qs, actor):
    with cambio_de_seccion(implementacion, "licencias_novedades", actor):
        for licencia in licencias_qs:
            ImplementacionLicencia.objects.update_or_create(
                implementacion=implementacion, tipo_licencia=licencia,
                defaults={"activo": form.cleaned_data.get(f"licencia_{licencia.id}_activo", False)},
            )
        for novedad in novedades_qs:
            ImplementacionNovedad.objects.update_or_create(
                implementacion=implementacion, tipo_novedad=novedad,
                defaults={"activo": form.cleaned_data.get(f"novedad_{novedad.id}_activo", False)},
            )


def guardar_liquidaciones(implementacion, tipos, actor):
    """Guarda qué tipos de liquidación usa la empresa (`tipos`: los elegidos; el resto queda inactivo)."""
    elegidos = {t.pk for t in tipos}
    with cambio_de_seccion(implementacion, "liquidaciones", actor):
        for tipo in TipoLiquidacion.objects.all():
            ImplementacionLiquidacion.objects.update_or_create(
                implementacion=implementacion, tipo_liquidacion=tipo, defaults={"activo": tipo.pk in elegidos},
            )


def guardar_documentos(implementacion, form, todos_qs, actor):
    with cambio_de_seccion(implementacion, "documentos", actor):
        for tipo in todos_qs:
            ImplementacionTipoDocumento.objects.update_or_create(
                implementacion=implementacion, tipo_documento=tipo,
                defaults={"activo": form.cleaned_data.get(f"tipo_{tipo.id}_activo", False)},
            )
        for nombre, campos in form.parse_otros_documentos():
            nuevo_tipo, _ = TipoDocumento.objects.get_or_create(
                implementacion=implementacion, nombre=nombre, defaults={"es_custom": True}
            )
            for i, campo_nombre in enumerate(campos):
                nuevo_tipo.campos.get_or_create(nombre=campo_nombre, defaults={"orden": i})
            ImplementacionTipoDocumento.objects.update_or_create(
                implementacion=implementacion, tipo_documento=nuevo_tipo, defaults={"activo": True}
            )
