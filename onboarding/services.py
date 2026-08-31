"""Lógica de guardado compartida entre el wizard del cliente y el panel interno,
para que ambos apliquen exactamente las mismas reglas al modificar una implementación.

Cada función de guardado registra primero una versión anterior (clients.services.guardar_version)
con el estado previo de la sección, así el cliente y el equipo pueden consultarlas después.
"""

from catalog.models import TipoDocumento
from clients.models import Implementacion, PersonaRol, Sucursal
from clients.services import guardar_version
from employees.models import Empleado, ImportBatch
from employees.services import parse_archivo_empleados

from .models import ImplementacionLicencia, ImplementacionNovedad, ImplementacionTipoDocumento

TOTAL_PASOS = 9

# Pasos que solo aplican si el cliente contrató alguno de estos módulos.
# Los pasos que no aparecen acá (1, 2, 8, 9) son universales para cualquier implementación.
PASO_REQUIERE_MODULO = {
    3: {"Recibo Digital", "Legajos"},  # Roles: Apoderado/Liquidador (recibos) o Admin RRHH (legajo)
    4: {"Recibo Digital"},             # Configuración de firma y adjuntos del recibo
    5: {"Fichada"},                    # Sucursales (fichada por ubicación)
    6: {"Novedades"},                  # Licencias y Novedades
    7: {"Legajos"},                    # Documentos de Legajo Digital
}


def pasos_activos(implementacion):
    """Devuelve la lista ordenada de pasos que le corresponde completar a esta
    implementación puntual, según los módulos que contrató."""
    modulos_activos = set(
        implementacion.modulos.filter(activo=True).values_list("modulo__nombre", flat=True)
    )
    activos = []
    for paso in range(1, TOTAL_PASOS + 1):
        requeridos = PASO_REQUIERE_MODULO.get(paso)
        if requeridos is None or requeridos & modulos_activos:
            activos.append(paso)
    return activos


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


def guardar_datos_contacto(implementacion, form, editado_por):
    # OJO: Django ya mutó `implementacion` en memoria durante form.is_valid()
    # (ModelForm._post_clean() escribe los valores nuevos en la instancia antes
    # de guardar). Para que el snapshot capture el estado ANTERIOR de verdad,
    # hay que leerlo de nuevo desde la base, no del objeto que nos pasaron.
    anterior = Implementacion.objects.get(pk=implementacion.pk)
    guardar_version(anterior, "datos_contacto", editado_por)
    form.save()


def guardar_modulos(implementacion, modulos_qs, activos_ids, editado_por):
    guardar_version(implementacion, "modulos", editado_por)
    for modulo in modulos_qs:
        implementacion.modulos.update_or_create(modulo=modulo, defaults={"activo": modulo.id in activos_ids})


def guardar_roles(implementacion, formset, editado_por):
    guardar_version(implementacion, "roles", editado_por)
    implementacion.roles.all().delete()
    nuevos = []
    for form in formset:
        if form.cleaned_data.get("DELETE"):
            continue
        nombre = form.cleaned_data.get("apellido_nombre")
        if not nombre:
            continue
        nuevos.append(
            PersonaRol(
                implementacion=implementacion,
                rol=form.cleaned_data["rol"],
                apellido_nombre=nombre,
                cuil=form.cleaned_data.get("cuil", ""),
                mail=form.cleaned_data.get("mail", ""),
            )
        )
    PersonaRol.objects.bulk_create(nuevos)


def guardar_sucursales(implementacion, formset, editado_por):
    guardar_version(implementacion, "sucursales", editado_por)
    implementacion.sucursales.all().delete()
    nuevas = []
    for form in formset:
        if form.cleaned_data.get("DELETE"):
            continue
        if not any(form.cleaned_data.get(f) for f in ("nombre", "calle", "localidad")):
            continue
        nuevas.append(
            Sucursal(implementacion=implementacion, **{k: v for k, v in form.cleaned_data.items() if k != "DELETE"})
        )
    Sucursal.objects.bulk_create(nuevas)


def guardar_licencias_y_novedades(implementacion, form, licencias_qs, novedades_qs, editado_por):
    guardar_version(implementacion, "licencias_novedades", editado_por)
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


def guardar_documentos(implementacion, form, todos_qs, editado_por):
    guardar_version(implementacion, "documentos", editado_por)
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


def _resolver_jerarquia_importada(implementacion, filas):
    """Segunda pasada del import: liga Reporta A / Aprobador por CUIL, ya con
    todos los empleados de la fila creados (no se puede resolver en la primera pasada
    porque un empleado puede referenciar a otro que todavía no existía)."""
    for fila in filas:
        if not (fila.get("reporta_a") or fila.get("aprobador")):
            continue
        empleado = Empleado.objects.filter(implementacion=implementacion, cuil=fila["cuil"]).first()
        if not empleado:
            continue
        if fila.get("reporta_a"):
            empleado.reporta_a = Empleado.objects.filter(
                implementacion=implementacion, cuil=fila["reporta_a"]
            ).first()
        if fila.get("aprobador"):
            empleado.aprobador = Empleado.objects.filter(
                implementacion=implementacion, cuil=fila["aprobador"]
            ).first()
        empleado.save()


def importar_archivo_empleados(implementacion, archivo, editado_por):
    """Parsea y carga un archivo de empleados. Devuelve (filas_importadas, errores)."""
    guardar_version(implementacion, "empleados", editado_por)
    filas, errores = parse_archivo_empleados(archivo)
    batch = ImportBatch.objects.create(
        implementacion=implementacion, archivo=archivo,
        filas_totales=len(filas) + len(errores), filas_importadas=len(filas), errores=errores,
    )
    for fila in filas:
        fila_datos = {k: v for k, v in fila.items() if k not in ("reporta_a", "aprobador")}
        Empleado.objects.update_or_create(
            implementacion=implementacion, cuil=fila["cuil"], defaults={**fila_datos, "import_batch": batch},
        )
    _resolver_jerarquia_importada(implementacion, filas)
    return filas, errores


def agregar_empleado(implementacion, empleado_form, editado_por):
    """Guarda un EmpleadoForm ya validado. Devuelve True si se agregó."""
    if not empleado_form.is_valid():
        return False
    guardar_version(implementacion, "empleados", editado_por)
    empleado = empleado_form.save(commit=False)
    empleado.implementacion = implementacion
    empleado.save()
    return True


def eliminar_empleado(implementacion, empleado_id, editado_por):
    if not str(empleado_id).isdigit():
        return
    guardar_version(implementacion, "empleados", editado_por)
    implementacion.empleados.filter(pk=empleado_id).delete()
