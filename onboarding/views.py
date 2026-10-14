import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from catalog.models import TipoLicencia, TipoNovedad
from clients.models import Implementacion, Modulo
from clients.services import resumen_implementacion
from employees.forms import EmpleadoForm, ImportarArchivoForm
from employees.services import generar_plantilla_xlsx
from notifications.services import notificar_implementacion_completa, notificar_revision_solicitada

from . import services
from .forms import (
    ConfiguracionForm,
    DocumentosLegajoForm,
    EmpresaForm,
    FechaImplementacionForm,
    LicenciasNovedadesForm,
    ModulosForm,
    PedirRevisionForm,
    rol_formset_obligatorio,
    SucursalFormSet,
)
from .services import TOTAL_PASOS

logger = logging.getLogger(__name__)

EDITADO_POR_CLIENTE = "Cliente"

TITULOS_PASO = {
    1: "Datos de contacto",
    2: "Módulos contratados",
    3: "Apoderado/s, Liquidador y Admin. de RRHH",
    4: "Configuración de firma y adjuntos",
    5: "Sucursales",
    6: "Licencias y Novedades",
    7: "Documentos de Legajo Digital",
    8: "Carga de empleados",
    9: "Revisión y envío",
}


@login_required(login_url="login")
def mis_implementaciones(request):
    cliente = getattr(request.user, "cliente", None)
    if cliente is None:
        return HttpResponseForbidden("Esta cuenta no tiene una empresa cliente asociada.")
    implementaciones = cliente.implementaciones.order_by("-creado")
    return render(
        request, "onboarding/mis_implementaciones.html",
        {"cliente": cliente, "implementaciones": implementaciones},
    )


def _verificar_acceso_cliente(request, implementacion):
    """Devuelve una respuesta (redirect a login, o 403) si el usuario logueado no
    puede ver esta implementación puntual; None si el acceso es válido."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url=reverse_lazy("login"))
    cliente = getattr(request.user, "cliente", None)
    if cliente is None or cliente.pk != implementacion.cliente_id:
        return HttpResponseForbidden("No tenés acceso a esta implementación.")
    return None


def _get_implementacion(token):
    return get_object_or_404(Implementacion.objects.select_related("cliente"), token=token)


def _paso_siguiente(activos, desde):
    """El próximo paso activo después de `desde` (según los módulos contratados),
    o el último activo si `desde` ya era el último."""
    for p in activos:
        if p > desde:
            return p
    return activos[-1]


def _paso_anterior(activos, desde):
    anterior = None
    for p in activos:
        if p >= desde:
            break
        anterior = p
    return anterior


def _marcar_progreso(implementacion, paso):
    if paso > implementacion.paso_actual:
        implementacion.paso_actual = paso
        implementacion.save(update_fields=["paso_actual", "actualizado"])


def wizard_step(request, token, step):
    implementacion = _get_implementacion(token)
    acceso = _verificar_acceso_cliente(request, implementacion)
    if acceso:
        return acceso

    step = int(step)
    if step < 1 or step > TOTAL_PASOS:
        raise Http404("Paso inválido")

    if implementacion.estado == Implementacion.ESTADO_CANCELADA:
        return render(request, "onboarding/cancelada.html", {"implementacion": implementacion})

    if implementacion.enviado:
        # El cliente ya envió el relevamiento: pasa a solo-lectura sin importar
        # si el equipo de Napsis ya terminó de implementar (eso es otro estado).
        return _vista_solo_lectura(request, implementacion)

    activos = services.pasos_activos(implementacion)
    if step not in activos:
        # Este paso no le corresponde a esta implementación según los módulos
        # que contrató (ej: Sucursales sin Fichada) — lo mandamos al que sí.
        return redirect("onboarding:wizard_step", token=implementacion.token, step=_paso_siguiente(activos, step - 1))

    handler = _HANDLERS[step]
    return handler(request, implementacion, step)


def _vista_solo_lectura(request, implementacion, recien_enviado=False):
    if request.method == "POST" and request.POST.get("accion") == "pedir_revision":
        form = PedirRevisionForm(request.POST)
        if form.is_valid():
            implementacion.pedir_revision(form.cleaned_data.get("mensaje", ""))
            notificar_revision_solicitada(implementacion, request=request)
            messages.success(request, "Le avisamos al equipo de Napsis que necesitás que te contacten.")
            return redirect("onboarding:wizard_step", token=implementacion.token, step=1)
    else:
        form = PedirRevisionForm()

    contexto = resumen_implementacion(implementacion)
    contexto["recien_enviado"] = recien_enviado
    contexto["pedir_revision_form"] = form
    return render(request, "onboarding/ya_enviado.html", contexto)


def _wizard_context(implementacion, step, extra=None):
    activos = services.pasos_activos(implementacion)
    ctx = {
        "implementacion": implementacion,
        "cliente": implementacion.cliente,
        "paso": step,
        "total_pasos": len(activos),
        "titulo_paso": TITULOS_PASO[step],
        "pasos": [(n, TITULOS_PASO[n]) for n in activos],
        "paso_anterior": _paso_anterior(activos, step),
    }
    ctx.update(extra or {})
    return ctx


def _redirect_next(implementacion, step):
    activos = services.pasos_activos(implementacion)
    siguiente = _paso_siguiente(activos, step)
    _marcar_progreso(implementacion, siguiente)
    return redirect("onboarding:wizard_step", token=implementacion.token, step=siguiente)


def _step_empresa(request, implementacion, step):
    if request.method == "POST":
        form = EmpresaForm(request.POST, instance=implementacion)
        if form.is_valid():
            services.guardar_datos_contacto(implementacion, form, EDITADO_POR_CLIENTE)
            return _redirect_next(implementacion, step)
    else:
        form = EmpresaForm(instance=implementacion)
    return render(request, "onboarding/step_empresa.html", _wizard_context(implementacion, step, {"form": form}))


def _step_modulos(request, implementacion, step):
    modulos_qs = Modulo.objects.all()
    activos_ids = set(implementacion.modulos.filter(activo=True).values_list("modulo_id", flat=True))
    editable = implementacion.modulos_editables_por_cliente

    if request.method == "POST":
        if not editable:
            # Los módulos los precargó el implementador al generar el link; el cliente
            # solo los confirma, no puede modificarlos desde acá.
            return _redirect_next(implementacion, step)
        form = ModulosForm(request.POST, modulos_qs=modulos_qs, activos_ids=activos_ids)
        if form.is_valid():
            nuevos_activos = {m.id for m in modulos_qs if form.cleaned_data.get(f"modulo_{m.id}", False)}
            services.guardar_modulos(implementacion, modulos_qs, nuevos_activos, EDITADO_POR_CLIENTE)
            return _redirect_next(implementacion, step)
    else:
        form = ModulosForm(modulos_qs=modulos_qs, activos_ids=activos_ids, disabled=not editable)
    return render(
        request, "onboarding/step_modulos.html",
        _wizard_context(implementacion, step, {"form": form, "editable": editable}),
    )


def _step_roles(request, implementacion, step):
    existentes = list(implementacion.roles.all())
    initial = [
        {"rol": r.rol, "apellido_nombre": r.apellido_nombre, "cuil": r.cuil, "mail": r.mail}
        for r in existentes
    ]

    RolesFormSet = rol_formset_obligatorio(implementacion.max_roles)
    if request.method == "POST":
        formset = RolesFormSet(request.POST)
        if formset.is_valid():
            services.guardar_roles(implementacion, formset, EDITADO_POR_CLIENTE)
            return _redirect_next(implementacion, step)
    else:
        formset = RolesFormSet(initial=initial)
    return render(
        request, "onboarding/step_roles.html",
        _wizard_context(implementacion, step, {"formset": formset, "max_roles": implementacion.max_roles}),
    )


def _step_configuracion(request, implementacion, step):
    if request.method == "POST":
        form = ConfiguracionForm(request.POST, request.FILES, instance=implementacion)
        if form.is_valid():
            services.guardar_datos_contacto(implementacion, form, EDITADO_POR_CLIENTE)
            return _redirect_next(implementacion, step)
    else:
        form = ConfiguracionForm(instance=implementacion)
    return render(request, "onboarding/step_configuracion.html", _wizard_context(implementacion, step, {"form": form}))


def _step_sucursales(request, implementacion, step):
    existentes = list(implementacion.sucursales.all())
    initial = [
        {
            "nombre": s.nombre, "calle": s.calle, "altura": s.altura, "piso_depto": s.piso_depto,
            "codigo_postal": s.codigo_postal, "localidad": s.localidad,
            "entre_calles": s.entre_calles, "observaciones": s.observaciones,
        }
        for s in existentes
    ]

    if request.method == "POST":
        formset = SucursalFormSet(request.POST)
        if formset.is_valid():
            services.guardar_sucursales(implementacion, formset, EDITADO_POR_CLIENTE)
            return _redirect_next(implementacion, step)
    else:
        formset = SucursalFormSet(initial=initial)
    return render(request, "onboarding/step_sucursales.html", _wizard_context(implementacion, step, {"formset": formset}))


def _step_licencias_novedades(request, implementacion, step):
    licencias_qs = TipoLicencia.objects.all()
    novedades_qs = TipoNovedad.objects.all()
    estado_licencia = services.estado_actual_licencias(implementacion)
    estado_novedad = services.estado_actual_novedades(implementacion)

    if request.method == "POST":
        form = LicenciasNovedadesForm(
            request.POST, licencias_qs=licencias_qs, novedades_qs=novedades_qs,
            estado_por_licencia=estado_licencia, estado_por_novedad=estado_novedad,
        )
        if form.is_valid():
            services.guardar_licencias_y_novedades(implementacion, form, licencias_qs, novedades_qs, EDITADO_POR_CLIENTE)
            return _redirect_next(implementacion, step)
    else:
        form = LicenciasNovedadesForm(
            licencias_qs=licencias_qs, novedades_qs=novedades_qs,
            estado_por_licencia=estado_licencia, estado_por_novedad=estado_novedad,
        )

    licencias_rows = [
        (licencia, form[f"licencia_{licencia.id}_activo"])
        for licencia in licencias_qs
    ]
    novedades_rows = [
        (novedad, form[f"novedad_{novedad.id}_activo"])
        for novedad in novedades_qs
    ]
    return render(
        request, "onboarding/step_licencias_novedades.html",
        _wizard_context(implementacion, step, {"form": form, "licencias_rows": licencias_rows, "novedades_rows": novedades_rows}),
    )


def _step_documentos(request, implementacion, step):
    todos_qs = services.tipos_documento_disponibles(implementacion)
    estado_por_tipo = services.estado_actual_documentos(implementacion)

    if request.method == "POST":
        form = DocumentosLegajoForm(request.POST, tipos_qs=todos_qs, estado_por_tipo=estado_por_tipo)
        if form.is_valid():
            services.guardar_documentos(implementacion, form, todos_qs, EDITADO_POR_CLIENTE)
            return _redirect_next(implementacion, step)
    else:
        form = DocumentosLegajoForm(tipos_qs=todos_qs, estado_por_tipo=estado_por_tipo)

    tipos_rows = [
        (tipo, form[f"tipo_{tipo.id}_activo"])
        for tipo in todos_qs
    ]
    return render(
        request, "onboarding/step_documentos.html",
        _wizard_context(implementacion, step, {"form": form, "tipos_rows": tipos_rows}),
    )


def _importar_archivo_empleados(request, implementacion):
    """Maneja la acción 'importar' del paso de empleados. Devuelve (import_form, errores_import)."""
    import_form = ImportarArchivoForm(request.POST, request.FILES)
    if not import_form.is_valid():
        errores = [{"fila": "-", "mensaje": e} for e in import_form.errors.get("archivo", [])]
        return import_form, errores

    filas, errores = services.importar_archivo_empleados(implementacion, import_form.cleaned_data["archivo"], EDITADO_POR_CLIENTE)
    if errores:
        messages.warning(
            request, f"Se importaron {len(filas)} empleados. {len(errores)} filas tuvieron errores y no se cargaron."
        )
    else:
        messages.success(request, f"Se importaron {len(filas)} empleados correctamente.")
    return import_form, errores


def _agregar_empleado_manual(request, implementacion):
    """Maneja la acción 'agregar_manual' del paso de empleados. Devuelve el EmpleadoForm a mostrar."""
    empleado_form = EmpleadoForm(request.POST, implementacion=implementacion)
    if services.agregar_empleado(implementacion, empleado_form, EDITADO_POR_CLIENTE):
        messages.success(request, "Empleado agregado.")
        return EmpleadoForm(implementacion=implementacion)
    return empleado_form


def _step_empleados(request, implementacion, step):
    accion = request.POST.get("accion") if request.method == "POST" else None

    import_form = ImportarArchivoForm()
    empleado_form = EmpleadoForm(implementacion=implementacion)
    errores_import = []

    if accion == "importar":
        import_form, errores_import = _importar_archivo_empleados(request, implementacion)
    elif accion == "agregar_manual":
        empleado_form = _agregar_empleado_manual(request, implementacion)
    elif accion == "eliminar":
        services.eliminar_empleado(implementacion, request.POST.get("empleado_id"), EDITADO_POR_CLIENTE)
        messages.info(request, "Empleado eliminado.")
    elif accion == "continuar":
        if implementacion.empleados.exists():
            return _redirect_next(implementacion, step)
        messages.error(request, "Tenés que cargar la nómina (al menos un empleado) para poder continuar.")

    empleados = implementacion.empleados.all().order_by("apellido", "nombre")
    return render(
        request, "onboarding/step_empleados.html",
        _wizard_context(implementacion, step, {
            "import_form": import_form,
            "empleado_form": empleado_form,
            "empleados": empleados,
            "errores_import": errores_import,
        }),
    )


def descargar_plantilla_empleados(request, token):
    implementacion = _get_implementacion(token)
    acceso = _verificar_acceso_cliente(request, implementacion)
    if acceso:
        return acceso
    buffer = generar_plantilla_xlsx()
    return FileResponse(
        buffer, as_attachment=True, filename="plantilla_empleados_napsis.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _step_revision(request, implementacion, step):
    pendientes = services.pendientes_de_envio(implementacion)
    enviando = request.method == "POST" and request.POST.get("accion") == "enviar"
    fecha_form = FechaImplementacionForm(
        request.POST if enviando else None,
        implementacion=implementacion, minima=services.fecha_minima_para_cliente(),
    )

    if enviando:
        if pendientes:
            messages.error(request, "Todavía falta completar algunos datos obligatorios para poder enviar.")
        elif fecha_form.is_valid():
            fecha = fecha_form.cleaned_data["fecha_salida_productivo"]
            if fecha != implementacion.fecha_salida_productivo:
                services.guardar_fecha_implementacion(implementacion, fecha, EDITADO_POR_CLIENTE)
            # Primero se registra el envío y recién después se avisa al equipo: si el mail
            # falla (SMTP caído, etc.) el cliente no tiene por qué ver un error ni perder
            # lo que ya terminó. La falla queda en el log.
            implementacion.enviado = timezone.now()
            implementacion.save(update_fields=["enviado"])
            try:
                notificar_implementacion_completa(implementacion, request=request)
            except Exception:
                logger.exception("No se pudo notificar al equipo la implementación %s", implementacion.pk)
            return redirect("onboarding:enviado", token=implementacion.token)

    resumen = {
        "licencias_activas": implementacion.licencias.filter(activo=True).count(),
        "novedades_activas": implementacion.novedades.filter(activo=True).count(),
        "documentos_activos": implementacion.documentos_legajo.filter(activo=True).count(),
    }
    return render(
        request, "onboarding/step_revision.html",
        _wizard_context(implementacion, step, {"resumen": resumen, "pendientes": pendientes, "fecha_form": fecha_form}),
    )


def enviado(request, token):
    implementacion = _get_implementacion(token)
    acceso = _verificar_acceso_cliente(request, implementacion)
    if acceso:
        return acceso
    return _vista_solo_lectura(request, implementacion, recien_enviado=True)


_HANDLERS = {
    1: _step_empresa,
    2: _step_modulos,
    3: _step_roles,
    4: _step_configuracion,
    5: _step_sucursales,
    6: _step_licencias_novedades,
    7: _step_documentos,
    8: _step_empleados,
    9: _step_revision,
}
