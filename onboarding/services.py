"""Lógica de guardado compartida entre el wizard del cliente y el panel interno,
para que ambos apliquen exactamente las mismas reglas al modificar una implementación.

Cada función de guardado registra primero una versión anterior (clients.services.guardar_version)
con el estado previo de la sección, así el cliente y el equipo pueden consultarlas después.
"""

from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.utils import timezone

from catalog.models import TipoDocumento
from clients.models import (
    Implementacion,
    ImplementacionLicencia,
    ImplementacionNovedad,
    ImplementacionTipoDocumento,
    Modulo,
    PersonaRol,
    Sucursal,
)
from clients.services import guardar_version
from employees.models import Empleado, ImportBatch
from employees.services import COLUMNAS, leer_archivo_empleados

TOTAL_PASOS = 9

# Orden del wizard. La nómina va antes que los roles (para poder elegir de ahí a las personas
# con rol) y las sucursales antes que la nómina (para poder asignar a cada empleado la suya).
(
    PASO_DATOS, PASO_MODULOS, PASO_SUCURSALES, PASO_NOMINA, PASO_ROLES,
    PASO_CONFIGURACION, PASO_LICENCIAS, PASO_DOCUMENTOS, PASO_REVISION,
) = range(1, TOTAL_PASOS + 1)

# El cliente solo puede pedir una fecha de implementación a partir de tantos días hábiles
# (lunes a viernes; no se descuentan feriados). El equipo de implementación puede poner
# cualquier fecha desde el panel.
DIAS_HABILES_MINIMOS_CLIENTE = 10

# Pasos que solo aplican si el cliente contrató alguno de estos módulos.
# Los pasos que no aparecen acá (datos, módulos, nómina y revisión) son universales.
PASO_REQUIERE_MODULO = {
    PASO_SUCURSALES: {Modulo.FICHADA},                          # Sucursales (fichada por ubicación)
    PASO_ROLES: {Modulo.RECIBO_DIGITAL, Modulo.LEGAJOS},        # Apoderado/Liquidador (recibos) o Admin RRHH (legajo)
    PASO_CONFIGURACION: {Modulo.RECIBO_DIGITAL},                # Configuración de firma y adjuntos del recibo
    PASO_LICENCIAS: {Modulo.NOVEDADES},                         # Licencias y Novedades
    PASO_DOCUMENTOS: {Modulo.LEGAJOS},                          # Documentos de Legajo Digital
}


def pasos_activos(implementacion):
    """Devuelve la lista ordenada de pasos que le corresponde completar a esta
    implementación puntual, según los módulos que contrató."""
    modulos_activos = set(
        implementacion.modulos.filter(activo=True).values_list("modulo__codigo", flat=True)
    )
    activos = []
    for paso in range(1, TOTAL_PASOS + 1):
        requeridos = PASO_REQUIERE_MODULO.get(paso)
        if requeridos is None or requeridos & modulos_activos:
            activos.append(paso)
    return activos


def sumar_dias_habiles(desde, cantidad):
    """La fecha que queda `cantidad` días hábiles (lunes a viernes) después de `desde`."""
    fecha = desde
    while cantidad > 0:
        fecha += timedelta(days=1)
        if fecha.weekday() < 5:
            cantidad -= 1
    return fecha


def fecha_minima_para_cliente(hoy=None):
    """Primera fecha de implementación que el cliente puede pedir."""
    return sumar_dias_habiles(hoy or timezone.localdate(), DIAS_HABILES_MINIMOS_CLIENTE)


def guardar_condiciones(implementacion, form, editado_por):
    """Aplica las condiciones del proceso (form = CondicionesForm ya validado) registrando antes
    la versión anterior."""
    guardar_version(implementacion, "condiciones", editado_por)
    form.aplicar(implementacion)
    implementacion.save()


def guardar_fecha_implementacion(implementacion, fecha, editado_por):
    """Guarda la fecha de salida en productivo (None la borra), registrando antes la versión
    anterior. Lo usan el cliente (con su mínimo) y el panel (sin límite)."""
    guardar_version(implementacion, "fecha_implementacion", editado_por)
    implementacion.fecha_salida_productivo = fecha
    implementacion.save(update_fields=["fecha_salida_productivo"])


def pendientes_de_envio(implementacion):
    """Lo que todavía falta para poder enviar el relevamiento, como lista de
    {"paso": N, "mensaje": ...} (vacía = listo). Los pasos no son secuenciales (el cliente
    puede saltar de uno a otro por la URL), así que esta es la validación que de verdad
    protege el envío; cada paso valida además lo suyo para avisar a tiempo."""
    activos = pasos_activos(implementacion)
    pendientes = []

    cliente = implementacion.cliente
    if not (cliente.razon_social and cliente.cuits):
        pendientes.append({"paso": PASO_DATOS, "mensaje": "Completar la razón social y el CUIT de la empresa."})

    if PASO_ROLES in activos:
        presentes = set(implementacion.roles.exclude(apellido_nombre="").values_list("rol", flat=True))
        faltan = [nombre for rol, nombre in PersonaRol.ROL_CHOICES if rol not in presentes]
        if faltan:
            pendientes.append({
                "paso": PASO_ROLES,
                "mensaje": "Cargar al menos una persona para cada rol. Falta: " + ", ".join(faltan) + ".",
            })

    if PASO_CONFIGURACION in activos and not implementacion.modelo_recibo:
        pendientes.append({"paso": PASO_CONFIGURACION, "mensaje": "Subir el modelo de recibo (PDF)."})

    if not implementacion.empleados.exists():
        pendientes.append({"paso": PASO_NOMINA, "mensaje": "Cargar la nómina de empleados (al menos una persona)."})

    return sorted(pendientes, key=lambda p: p["paso"])


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


@transaction.atomic
def guardar_sucursales(implementacion, formset, editado_por):
    """Guarda las sucursales conservando las que siguen existiendo (se reconocen por el nombre):
    antes se borraban todas y se recreaban, y cada empleado perdía la sucursal que tenía asignada
    cada vez que el cliente volvía a guardar este paso."""
    guardar_version(implementacion, "sucursales", editado_por)
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


# bulk_update arma un CASE por campo con una rama por fila: con lotes grandes MySQL tarda mucho
# más que con varios lotes chicos (5.000 filas: ~25 s con lotes de 500).
LOTE_ACTUALIZACION = 100

CAMPOS_EMPLEADO_IMPORTADOS = [campo for _h, campo, _r, _t in COLUMNAS if campo not in ("reporta_a", "aprobador")]


def _resolver_jerarquia_importada(implementacion, filas, advertencias):
    """Segunda pasada del import: liga Reporta A / Aprobador por CUIL, ya con todos los
    empleados cargados (un empleado puede referenciar a otro que está más abajo en el archivo).
    Si el CUIL referenciado no existe en la nómina no se toca esa relación y se avisa."""
    con_jerarquia = [f for f in filas if f.get("reporta_a") or f.get("aprobador")]
    if not con_jerarquia:
        return
    por_cuil = {e.cuil: e for e in implementacion.empleados.all()}
    modificados = {}
    for fila in con_jerarquia:
        empleado = por_cuil.get(fila["cuil"])
        for campo, etiqueta in (("reporta_a", "Reporta A"), ("aprobador", "Aprobador")):
            if not fila.get(campo):
                continue
            referenciado = por_cuil.get(fila[campo])
            if referenciado is None:
                advertencias.append(
                    f"Fila {fila['numero_fila']}: el CUIL {fila[campo]} de '{etiqueta}' no está en la nómina; "
                    f"no se vinculó."
                )
                continue
            if getattr(empleado, f"{campo}_id") != referenciado.pk:
                setattr(empleado, campo, referenciado)
                modificados[empleado.pk] = empleado
    Empleado.objects.bulk_update(list(modificados.values()), ["reporta_a", "aprobador"], batch_size=LOTE_ACTUALIZACION)


def importar_archivo_empleados(implementacion, archivo, editado_por):
    """Parsea y carga un archivo de empleados. Devuelve (filas_importadas, errores, advertencias).

    Todo o nada: si algo falla a mitad de la carga no queda una nómina a medias. Las filas con
    errores no se cargan (se informan) pero no impiden cargar las demás. Si el archivo en sí no
    sirve (ilegible, sin columnas obligatorias, demasiado grande) levanta ArchivoInvalido ANTES de
    tocar nada. Solo se registra el resultado de la importación: el archivo no se guarda (tiene
    datos personales y no se vuelve a usar)."""
    lectura = leer_archivo_empleados(archivo)
    with transaction.atomic():
        return _cargar_empleados(implementacion, archivo, lectura, editado_por)


def _cargar_empleados(implementacion, archivo, lectura, editado_por):
    filas, errores = lectura.filas, lectura.errores
    advertencias = []
    if lectura.columnas_ignoradas:
        advertencias.append(
            "No reconocimos estas columnas y se ignoraron: " + ", ".join(lectura.columnas_ignoradas) + "."
        )

    guardar_version(implementacion, "empleados", editado_por)
    batch = ImportBatch.objects.create(
        implementacion=implementacion, nombre_archivo=archivo.name[:255],
        filas_totales=len(filas) + len(errores), filas_importadas=len(filas), errores=errores,
    )

    # En lote: una importación de miles de filas con un update_or_create por fila eran decenas de
    # miles de consultas dentro del pedido web (y el proxy corta a los 60 s).
    existentes = {e.cuil: e for e in implementacion.empleados.all()}
    ahora = timezone.now()
    nuevos, actualizados = [], []
    for fila in filas:
        datos = {campo: fila[campo] for campo in CAMPOS_EMPLEADO_IMPORTADOS}
        empleado = existentes.get(fila["cuil"])
        if empleado:
            # Solo se actualiza lo que cambió: volver a subir la misma planilla (o una con
            # pocas modificaciones) no reescribe miles de filas.
            if any(getattr(empleado, campo) != valor for campo, valor in datos.items()):
                for campo, valor in datos.items():
                    setattr(empleado, campo, valor)
                empleado.import_batch, empleado.actualizado = batch, ahora
                actualizados.append(empleado)
        else:
            nuevos.append(Empleado(implementacion=implementacion, import_batch=batch, **datos))
    Empleado.objects.bulk_create(nuevos, batch_size=500)
    Empleado.objects.bulk_update(
        actualizados, CAMPOS_EMPLEADO_IMPORTADOS + ["import_batch", "actualizado"], batch_size=LOTE_ACTUALIZACION,
    )
    _resolver_jerarquia_importada(implementacion, filas, advertencias)
    return filas, errores, advertencias


def resumen_importacion(filas, errores, advertencias, maximo_detalle=5):
    """Los mensajes que se muestran después de importar, como lista de (nivel, texto)."""
    resultado = []
    if errores:
        resultado.append((
            messages.WARNING,
            f"Se importaron {len(filas)} empleados. {len(errores)} filas tuvieron errores y no se cargaron.",
        ))
    else:
        resultado.append((messages.SUCCESS, f"Se importaron {len(filas)} empleados correctamente."))
    for texto in advertencias[:maximo_detalle]:
        resultado.append((messages.WARNING, texto))
    if len(advertencias) > maximo_detalle:
        resultado.append((messages.WARNING, f"... y {len(advertencias) - maximo_detalle} avisos más."))
    return resultado


def agregar_empleado(implementacion, empleado_form, editado_por):
    """Guarda un EmpleadoForm ya validado. Devuelve True si se agregó."""
    if not empleado_form.is_valid():
        return False
    guardar_version(implementacion, "empleados", editado_por)
    empleado = empleado_form.save(commit=False)
    empleado.implementacion = implementacion
    try:
        with transaction.atomic():
            empleado.save()
    except IntegrityError:
        # Doble clic o dos personas cargando al mismo tiempo: el CUIL ya está.
        empleado_form.add_error("cuil", "Ya hay un empleado cargado con ese CUIL.")
        return False
    return True


def editar_empleado(implementacion, empleado_form, editado_por):
    """Guarda los cambios de un EmpleadoForm (con instance) ya validado. Devuelve True si se guardó."""
    if not empleado_form.is_valid():
        return False
    guardar_version(implementacion, "empleados", editado_por)
    try:
        with transaction.atomic():
            empleado_form.save()
    except IntegrityError:
        empleado_form.add_error("cuil", "Ya hay un empleado cargado con ese CUIL.")
        return False
    return True


def eliminar_empleado(implementacion, empleado_id, editado_por):
    if not str(empleado_id).isdigit():
        return
    guardar_version(implementacion, "empleados", editado_por)
    implementacion.empleados.filter(pk=empleado_id).delete()
