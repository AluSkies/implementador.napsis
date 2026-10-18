"""Lógica de guardado compartida entre el wizard del cliente y el panel interno,
para que ambos apliquen exactamente las mismas reglas al modificar una implementación.

Cada función de guardado registra primero una versión anterior (clients.services.guardar_version)
con el estado previo de la sección, así el cliente y el equipo pueden consultarlas después.
"""

import hashlib
from datetime import timedelta

from django.contrib import messages
from django.forms.models import model_to_dict
from django.db import IntegrityError, transaction
from django.utils import timezone

from catalog.models import TipoDocumento, TipoLiquidacion
from clients.models import (
    ImplementacionLicencia,
    ImplementacionLiquidacion,
    ImplementacionNovedad,
    ImplementacionTipoDocumento,
    Modulo,
    PersonaRol,
    Sucursal,
    UbicacionFirma,
)
from automatizacion import actores, eventos
from clients.services import cambio_de_seccion, guardar_version, revocar_validacion
from employees.models import Empleado, ImportBatch
from employees.services import COLUMNAS, leer_archivo_empleados, normalizar_cuil

from .forms import FirmaForm

TOTAL_PASOS = 10

# Orden del wizard. La nómina va antes que los roles (para poder elegir de ahí a las personas
# con rol) y las sucursales antes que la nómina (para poder asignar a cada empleado la suya).
(
    PASO_DATOS, PASO_MODULOS, PASO_SUCURSALES, PASO_NOMINA, PASO_ROLES,
    PASO_CONFIGURACION, PASO_FIRMA, PASO_LICENCIAS, PASO_DOCUMENTOS, PASO_REVISION,
) = range(1, TOTAL_PASOS + 1)

# El cliente solo puede pedir una fecha de implementación a partir de tantos días hábiles
# (lunes a viernes; no se descuentan feriados). El equipo de implementación puede poner
# cualquier fecha desde el panel.
DIAS_HABILES_MINIMOS_CLIENTE = 10

# Pasos que solo aplican si el cliente contrató alguno de estos módulos.
# Los pasos que no aparecen acá (datos, módulos, nómina y revisión) son universales.
TITULOS_PASO = {
    PASO_DATOS: "Datos de contacto",
    PASO_MODULOS: "Módulos contratados",
    PASO_SUCURSALES: "Sucursales",
    PASO_NOMINA: "Carga de empleados",
    PASO_ROLES: "Apoderado/s, Liquidador y Admin. de RRHH",
    PASO_CONFIGURACION: "Configuración y adjuntos",
    PASO_FIRMA: "Firma del recibo",
    PASO_LICENCIAS: "Licencias y Novedades",
    PASO_DOCUMENTOS: "Documentos de Legajo Digital",
    PASO_REVISION: "Revisión y envío",
}

# Código estable de cada paso: las observaciones de una devolución se guardan con él, así que no se
# pierden aunque cambie el número de orden de los pasos.
CODIGO_DE_PASO = {
    PASO_DATOS: "datos", PASO_MODULOS: "modulos", PASO_SUCURSALES: "sucursales", PASO_NOMINA: "nomina",
    PASO_ROLES: "roles", PASO_CONFIGURACION: "configuracion", PASO_FIRMA: "firma", PASO_LICENCIAS: "licencias",
    PASO_DOCUMENTOS: "documentos", PASO_REVISION: "revision",
}

PASO_REQUIERE_MODULO = {
    PASO_SUCURSALES: {Modulo.FICHADA},                          # Sucursales (fichada por ubicación)
    PASO_ROLES: {Modulo.RECIBO_DIGITAL, Modulo.LEGAJOS},        # Apoderado/Liquidador (recibos) o Admin RRHH (legajo)
    PASO_CONFIGURACION: {Modulo.RECIBO_DIGITAL},                # Configuración y adjuntos del recibo
    PASO_FIRMA: {Modulo.RECIBO_DIGITAL},                        # Dónde va la firma sobre el recibo
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

    if not implementacion.usa_modulo(Modulo.RECIBO_DIGITAL):
        pendientes.append({"paso": PASO_MODULOS, "mensaje": "Recibo Digital es obligatorio en toda implementación."})

    if PASO_SUCURSALES in activos and not implementacion.sucursales.exclude(nombre="").exists():
        pendientes.append({"paso": PASO_SUCURSALES, "mensaje": "Cargar al menos una sucursal (el módulo Fichada la necesita)."})

    if PASO_ROLES in activos:
        roles = list(implementacion.roles.exclude(apellido_nombre=""))
        faltan = [nombre for rol, nombre in PersonaRol.ROL_CHOICES if rol not in {r.rol for r in roles}]
        if faltan:
            pendientes.append({
                "paso": PASO_ROLES,
                "mensaje": "Cargar al menos una persona para cada rol. Falta: " + ", ".join(faltan) + ".",
            })
        cuils_nomina = set(implementacion.empleados.values_list("cuil", flat=True))
        for rol in roles:
            if rol.rol in PersonaRol.ROLES_EN_NOMINA and normalizar_cuil(rol.cuil) not in cuils_nomina:
                pendientes.append({
                    "paso": PASO_ROLES,
                    "mensaje": f"{rol.apellido_nombre} ({rol.get_rol_display()}) no figura en la nómina: "
                               "cargalo como empleado o corregí su CUIL.",
                })

    if PASO_CONFIGURACION in activos and not implementacion.modelo_recibo:
        pendientes.append({"paso": PASO_CONFIGURACION, "mensaje": "Subir el modelo de recibo (PDF)."})

    if PASO_CONFIGURACION in activos and not implementacion.liquidaciones.filter(activo=True).exists():
        pendientes.append({
            "paso": PASO_CONFIGURACION, "mensaje": "Elegir al menos un tipo de liquidación.",
        })

    if PASO_FIRMA in activos:
        firma = implementacion.firma
        if firma is None or not firma.imagen:
            pendientes.append({
                "paso": PASO_FIRMA, "mensaje": "Subir la imagen de la firma y ubicarla sobre el recibo.",
            })
        elif firma.estado == UbicacionFirma.ESTADO_OBSERVADA:
            pendientes.append({
                "paso": PASO_FIRMA, "mensaje": "Ajustar la firma según lo que pidió el equipo de Napsis.",
            })

    if not implementacion.empleados.exists():
        pendientes.append({"paso": PASO_NOMINA, "mensaje": "Cargar la nómina de empleados (al menos una persona)."})
    elif implementacion.usa_modulo(Modulo.RECIBO_DIGITAL):
        sin_ingreso = implementacion.empleados.filter(fecha_ingreso__isnull=True).count()
        if sin_ingreso:
            pendientes.append({
                "paso": PASO_NOMINA,
                "mensaje": f"Completar la fecha de ingreso de {sin_ingreso} empleado{'s' if sin_ingreso != 1 else ''} "
                           "(es obligatoria para Recibo Digital).",
            })

    return sorted(pendientes, key=lambda p: p["paso"])


def pendientes_de_validacion(implementacion):
    """Los textos de lo que le impide al equipo validar la documentación: lo mismo que impide el envío
    más que la firma tiene que estar validada. Es lo que se le muestra en la ficha antes de validar."""
    mensajes = [p["mensaje"] for p in pendientes_de_envio(implementacion)]
    firma = implementacion.firma
    if (
        implementacion.usa_modulo(Modulo.RECIBO_DIGITAL) and firma is not None and firma.imagen
        and firma.estado == UbicacionFirma.ESTADO_PROPUESTA
    ):
        mensajes.append("Falta validar la firma del recibo.")
    return mensajes


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


def vincular_roles_con_nomina(implementacion):
    """Liga cada persona con rol a su empleado de la nómina (por CUIL). Se llama cuando cambian los
    roles o la nómina. Si el empleado se borra, el vínculo queda vacío solo."""
    por_cuil = {e.cuil: e for e in implementacion.empleados.all()}
    for rol in implementacion.roles.all():
        empleado = por_cuil.get(normalizar_cuil(rol.cuil)) if rol.cuil else None
        if (empleado.pk if empleado else None) != rol.empleado_id:
            rol.empleado = empleado
            rol.save(update_fields=["empleado"])


def guardar_roles(implementacion, formset, actor):
    with cambio_de_seccion(implementacion, "roles", actor):
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
        vincular_roles_con_nomina(implementacion)


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


def guardar_firma(implementacion, actor, *, pagina, geometria, imagen=None):
    """Guarda la intención del cliente sobre su firma: página, recuadros y (si se sube una) la imagen.

    - La imagen anterior no se borra: queda en el disco y el evento `archivo.reemplazado` apunta a las dos.
    - Si guarda el cliente, la firma queda «propuesta» cuando algo cambió (o si estaba observada: es
      su respuesta). Si guarda el equipo, es una corrección posterior al envío y queda validada.
    """
    del_cliente = actor.tipo == actores.CLIENTE
    accion = "firma.propuesta" if del_cliente else "firma.corregida_por_implementador"
    with cambio_de_seccion(implementacion, "firma", actor, accion=accion):
        firma = implementacion.firmas.filter(tipo_liquidacion__isnull=True).first() or UbicacionFirma(
            implementacion=implementacion,
        )
        anterior = {"ruta": firma.imagen.name, "sha256": firma.imagen_sha256} if firma.imagen else None
        cambio = firma.pk is None or firma.pagina != pagina or firma.geometria != geometria or imagen is not None
        firma.pagina = pagina
        firma.geometria = geometria
        if imagen is not None:
            hash_imagen = hashlib.sha256()
            for trozo in imagen.chunks():
                hash_imagen.update(trozo)
            imagen.seek(0)
            firma.imagen.save(imagen.name, imagen, save=False)
            firma.imagen_sha256 = hash_imagen.hexdigest()
        if del_cliente:
            if cambio or firma.estado == UbicacionFirma.ESTADO_OBSERVADA:
                firma.estado = UbicacionFirma.ESTADO_PROPUESTA
                firma.motivos, firma.comentario = [], ""
                firma.validada_por, firma.validada_en = "", None
            firma.propuesta_por = firma.propuesta_por or actor.etiqueta
        else:
            firma.estado = UbicacionFirma.ESTADO_VALIDADA
            firma.motivos, firma.comentario = [], ""
            firma.validada_por, firma.validada_en = actor.etiqueta, timezone.now()
        firma.save()
        if imagen is not None and anterior:
            eventos.registrar(actor, "archivo.reemplazado", implementacion, seccion="firma", datos={
                "campo": "imagen_firma", "anterior": anterior,
                "nuevo": {"ruta": firma.imagen.name, "sha256": firma.imagen_sha256},
            })
    return firma


def contexto_del_editor_de_firma(implementacion, firma, form=None):
    """Lo que necesita el editor de firma (el del cliente, el de la ficha del panel y el de solo lectura)."""
    return {
        "form": form or FirmaForm(firma=firma),
        "form_lectura": FirmaForm(firma=firma, auto_id="lectura_%s"),
        "firma": firma,
        "modelo_url": implementacion.modelo_recibo.url if implementacion.modelo_recibo else "",
        "imagen_url": firma.imagen.url if firma and firma.imagen else "",
    }


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


# bulk_update arma un CASE por campo con una rama por fila: con lotes grandes MySQL tarda mucho
# más que con varios lotes chicos (5.000 filas: ~25 s con lotes de 500).
LOTE_ACTUALIZACION = 100

CAMPOS_EMPLEADO_IMPORTADOS = [campo for _h, campo, _r, _t in COLUMNAS if campo not in ("reporta_a", "aprobador")]


# Lo más que se detalla en un evento de importación: el resto queda contado en el resumen.
MAX_CORRECCIONES_EN_EVENTO = 500
MAX_ERRORES_EN_EVENTO = 50


def _valor_json(valor):
    """Un valor de un campo, listo para guardarse en un evento (las relaciones, por su id)."""
    return valor.pk if hasattr(valor, "pk") else valor


def _resolver_jerarquia_importada(implementacion, filas, advertencias):
    """Segunda pasada del import: liga Reporta A / Aprobador por CUIL, ya con todos los
    empleados cargados (un empleado puede referenciar a otro que está más abajo en el archivo).
    Si el CUIL referenciado no existe en la nómina no se toca esa relación y se avisa.
    Devuelve cuántos empleados cambiaron de jerarquía."""
    con_jerarquia = [f for f in filas if f.get("reporta_a") or f.get("aprobador")]
    if not con_jerarquia:
        return 0
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
    return len(modificados)


def importar_archivo_empleados(implementacion, archivo, actor):
    """Parsea y carga un archivo de empleados. Devuelve (filas_importadas, errores, advertencias).

    Todo o nada: si algo falla a mitad de la carga no queda una nómina a medias. Las filas con
    errores no se cargan (se informan) pero no impiden cargar las demás. Si el archivo en sí no
    sirve (ilegible, sin columnas obligatorias, demasiado grande) levanta ArchivoInvalido ANTES de
    tocar nada. Solo se registra el resultado de la importación: el archivo no se guarda (tiene
    datos personales y no se vuelve a usar)."""
    lectura = leer_archivo_empleados(archivo, ingreso_obligatorio=implementacion.usa_modulo(Modulo.RECIBO_DIGITAL))
    with transaction.atomic():
        return _cargar_empleados(implementacion, archivo, lectura, actor)


def _cargar_empleados(implementacion, archivo, lectura, actor):
    filas, errores = lectura.filas, lectura.errores
    advertencias = []
    if lectura.columnas_ignoradas:
        advertencias.append(
            "No reconocimos estas columnas y se ignoraron: " + ", ".join(lectura.columnas_ignoradas) + "."
        )

    guardar_version(implementacion, "empleados", actor)
    batch = ImportBatch.objects.create(
        implementacion=implementacion, nombre_archivo=archivo.name[:255],
        filas_totales=len(filas) + len(errores), filas_importadas=len(filas), errores=errores,
    )

    # En lote: una importación de miles de filas con un update_or_create por fila eran decenas de
    # miles de consultas dentro del pedido web (y el proxy corta a los 60 s).
    existentes = {e.cuil: e for e in implementacion.empleados.all()}
    ahora = timezone.now()
    nuevos, actualizados, correcciones = [], [], []
    for fila in filas:
        datos = {campo: fila[campo] for campo in CAMPOS_EMPLEADO_IMPORTADOS}
        empleado = existentes.get(fila["cuil"])
        if empleado:
            # Solo se actualiza lo que cambió: volver a subir la misma planilla (o una con
            # pocas modificaciones) no reescribe miles de filas.
            cambios = {
                campo: {"antes": getattr(empleado, campo), "despues": valor}
                for campo, valor in datos.items() if getattr(empleado, campo) != valor
            }
            if cambios:
                for campo, valor in datos.items():
                    setattr(empleado, campo, valor)
                empleado.import_batch, empleado.actualizado = batch, ahora
                actualizados.append(empleado)
                correcciones.append({"empleado_id": empleado.pk, "cambios": cambios})
        else:
            nuevos.append(Empleado(implementacion=implementacion, import_batch=batch, **datos))
    Empleado.objects.bulk_create(nuevos, batch_size=500)
    Empleado.objects.bulk_update(
        actualizados, CAMPOS_EMPLEADO_IMPORTADOS + ["import_batch", "actualizado"], batch_size=LOTE_ACTUALIZACION,
    )
    jerarquias = _resolver_jerarquia_importada(implementacion, filas, advertencias)
    vincular_roles_con_nomina(implementacion)

    # El alta de empleados nuevos se cuenta (cada uno ya queda en `Empleado`); lo que se PISA
    # (valores que cambiaron en empleados existentes) se detalla, porque la base no lo conserva.
    if nuevos or actualizados:
        revocar_validacion(implementacion, actor, "empleados")
    eventos.registrar(
        actor, "nomina.importada", implementacion, seccion="empleados",
        datos={
            "archivo": archivo.name[:255], "filas_leidas": len(filas) + len(errores), "nuevos": len(nuevos),
            "actualizados": len(actualizados), "jerarquias_vinculadas": jerarquias,
            "filas_con_error": len(errores), "errores": errores[:MAX_ERRORES_EN_EVENTO],
            "errores_truncados": len(errores) > MAX_ERRORES_EN_EVENTO,
            "columnas_ignoradas": lectura.columnas_ignoradas, "advertencias": len(advertencias),
            "correcciones": correcciones[:MAX_CORRECCIONES_EN_EVENTO],
            "correcciones_truncadas": len(correcciones) > MAX_CORRECCIONES_EN_EVENTO,
        },
    )
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


def agregar_empleado(implementacion, empleado_form, actor):
    """Guarda un EmpleadoForm ya validado. Devuelve True si se agregó."""
    if not empleado_form.is_valid():
        return False
    try:
        with transaction.atomic():
            guardar_version(implementacion, "empleados", actor)
            empleado = empleado_form.save(commit=False)
            empleado.implementacion = implementacion
            empleado.save()
            vincular_roles_con_nomina(implementacion)
            eventos.registrar(actor, "empleado.agregado", implementacion, seccion="empleados",
                              datos={"empleado_id": empleado.pk})
            revocar_validacion(implementacion, actor, "empleados")
    except IntegrityError:
        # Doble clic o dos personas cargando al mismo tiempo: el CUIL ya está.
        empleado_form.add_error("cuil", "Ya hay un empleado cargado con ese CUIL.")
        return False
    return True


def editar_empleado(implementacion, empleado_form, actor):
    """Guarda los cambios de un EmpleadoForm (con instance) ya validado. Devuelve True si se guardó.
    El evento lleva el antes y el después de lo que cambió: la base se queda solo con lo nuevo."""
    if not empleado_form.is_valid():
        return False
    cambios = {
        campo: {"antes": _valor_json(empleado_form.initial.get(campo)),
                "despues": _valor_json(empleado_form.cleaned_data.get(campo))}
        for campo in empleado_form.changed_data
    }
    try:
        with transaction.atomic():
            guardar_version(implementacion, "empleados", actor)
            empleado = empleado_form.save()
            vincular_roles_con_nomina(implementacion)
            eventos.registrar(actor, "empleado.editado", implementacion, seccion="empleados",
                              datos={"empleado_id": empleado.pk, "cambios": cambios})
            if cambios:
                revocar_validacion(implementacion, actor, "empleados")
    except IntegrityError:
        empleado_form.add_error("cuil", "Ya hay un empleado cargado con ese CUIL.")
        return False
    return True


def eliminar_empleado(implementacion, empleado_id, actor):
    if not str(empleado_id).isdigit():
        return
    empleado = implementacion.empleados.filter(pk=empleado_id).first()
    if empleado is None:
        return
    with transaction.atomic():
        guardar_version(implementacion, "empleados", actor)
        # La base lo pierde: el evento guarda la foto completa de lo que se borró.
        foto = {campo: _valor_json(valor) for campo, valor in model_to_dict(empleado).items()}
        empleado.delete()
        eventos.registrar(actor, "empleado.eliminado", implementacion, seccion="empleados",
                          datos={"empleado_id": int(empleado_id), "foto": foto})
        revocar_validacion(implementacion, actor, "empleados")
