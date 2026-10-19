"""La nómina de empleados: importación desde un archivo y alta, edición y baja manual."""

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.utils import timezone

from automatizacion import eventos
from clients.models import Modulo
from clients.services import guardar_version, revocar_validacion
from employees.models import Empleado, ImportBatch
from employees.services import COLUMNAS, leer_archivo_empleados
from onboarding.services.roles import vincular_roles_con_nomina

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
