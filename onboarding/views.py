from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from automatizacion.actores import Actor
from catalog.models import TipoLicencia, TipoNovedad
from clients.models import Implementacion, Modulo
from clients.services import resumen_implementacion
from employees.forms import EmpleadoForm, ImportarArchivoForm
from employees.services import ArchivoInvalido, generar_plantilla_xlsx

from . import acciones, services
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
from .services import (
    PASO_CONFIGURACION, PASO_DATOS, PASO_DOCUMENTOS, PASO_LICENCIAS, PASO_MODULOS, PASO_NOMINA,
    PASO_REVISION, PASO_ROLES, PASO_SUCURSALES, TOTAL_PASOS,
)

def _actor(request):
    return Actor.de_usuario(request.user)


def _errores_de(formulario):
    """Qué falló en un formulario o formset, sin los valores que se cargaron (solo campo y motivo)."""
    if hasattr(formulario, "forms"):
        return {
            "filas": [_errores_de(f) for f in formulario.forms if f.errors],
            "generales": [str(e) for e in formulario.non_form_errors()],
        }
    return {campo: [str(e) for e in errores] for campo, errores in formulario.errors.items()}


def _invalido(request, implementacion, paso, formulario):
    """El cliente intentó guardar un paso y algo no pasó la validación: queda registrado qué."""
    acciones.registrar_validacion_fallida(_actor(request), implementacion, paso, _errores_de(formulario))


TITULOS_PASO = {
    PASO_DATOS: "Datos de contacto",
    PASO_MODULOS: "Módulos contratados",
    PASO_SUCURSALES: "Sucursales",
    PASO_NOMINA: "Carga de empleados",
    PASO_ROLES: "Apoderado/s, Liquidador y Admin. de RRHH",
    PASO_CONFIGURACION: "Configuración de firma y adjuntos",
    PASO_LICENCIAS: "Licencias y Novedades",
    PASO_DOCUMENTOS: "Documentos de Legajo Digital",
    PASO_REVISION: "Revisión y envío",
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
            acciones.pedir_revision(
                _actor(request), implementacion, form.cleaned_data.get("mensaje", ""),
                base_url=request.build_absolute_uri("/"),
            ).mostrar(request)
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
            services.guardar_datos_contacto(implementacion, form, _actor(request))
            return _redirect_next(implementacion, step)
        _invalido(request, implementacion, step, form)
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
            services.guardar_modulos(implementacion, modulos_qs, nuevos_activos, _actor(request))
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

    RolesFormSet = rol_formset_obligatorio(
        implementacion.max_roles, cuils_nomina=implementacion.empleados.values_list("cuil", flat=True),
    )
    if request.method == "POST":
        formset = RolesFormSet(request.POST)
        if formset.is_valid():
            services.guardar_roles(implementacion, formset, _actor(request))
            return _redirect_next(implementacion, step)
        _invalido(request, implementacion, step, formset)
    else:
        formset = RolesFormSet(initial=initial)
    nomina = [
        {"etiqueta": f"{e.apellido}, {e.nombre} — {e.cuil}", "apellido_nombre": f"{e.apellido}, {e.nombre}",
         "cuil": e.cuil, "mail": e.mail}
        for e in implementacion.empleados.order_by("apellido", "nombre")
    ]
    return render(
        request, "onboarding/step_roles.html",
        _wizard_context(implementacion, step, {
            "formset": formset, "max_roles": implementacion.max_roles, "nomina": nomina, "paso_nomina": PASO_NOMINA,
        }),
    )


def _step_configuracion(request, implementacion, step):
    if request.method == "POST":
        form = ConfiguracionForm(request.POST, request.FILES, instance=implementacion)
        if form.is_valid():
            services.guardar_datos_contacto(implementacion, form, _actor(request))
            services.guardar_liquidaciones(implementacion, form.cleaned_data["tipos_liquidacion"], _actor(request))
            return _redirect_next(implementacion, step)
        _invalido(request, implementacion, step, form)
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
            services.guardar_sucursales(implementacion, formset, _actor(request))
            return _redirect_next(implementacion, step)
        _invalido(request, implementacion, step, formset)
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
            services.guardar_licencias_y_novedades(implementacion, form, licencias_qs, novedades_qs, _actor(request))
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
            services.guardar_documentos(implementacion, form, todos_qs, _actor(request))
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

    try:
        filas, errores, advertencias = services.importar_archivo_empleados(
            implementacion, import_form.cleaned_data["archivo"], _actor(request),
        )
    except ArchivoInvalido as error:
        acciones.registrar_validacion_fallida(
            _actor(request), implementacion, PASO_NOMINA, {"archivo": [str(error)]},
        )
        return import_form, [{"fila": "-", "mensaje": str(error)}]
    for nivel, texto in services.resumen_importacion(filas, errores, advertencias):
        messages.add_message(request, nivel, texto)
    return import_form, errores


def _agregar_empleado_manual(request, implementacion):
    """Maneja la acción 'agregar_manual' del paso de empleados. Devuelve el EmpleadoForm a mostrar."""
    empleado_form = EmpleadoForm(request.POST, implementacion=implementacion)
    if services.agregar_empleado(implementacion, empleado_form, _actor(request)):
        messages.success(request, "Empleado agregado.")
        return EmpleadoForm(implementacion=implementacion)
    _invalido(request, implementacion, PASO_NOMINA, empleado_form)
    return empleado_form


def _empleado_a_editar(implementacion, empleado_id):
    return implementacion.empleados.filter(pk=empleado_id).first() if str(empleado_id).isdigit() else None


def _step_empleados(request, implementacion, step):
    accion = request.POST.get("accion") if request.method == "POST" else None

    import_form = ImportarArchivoForm()
    empleado_form = EmpleadoForm(implementacion=implementacion)
    errores_import = []

    # Edición de un empleado ya cargado: ?editar=<id> abre el formulario con sus datos.
    editando = None
    if accion == "guardar_edicion":
        editando = _empleado_a_editar(implementacion, request.POST.get("empleado_id"))
        if editando:
            edicion_form = EmpleadoForm(request.POST, instance=editando, implementacion=implementacion)
            if services.editar_empleado(implementacion, edicion_form, _actor(request)):
                messages.success(request, "Empleado actualizado.")
                return redirect("onboarding:wizard_step", token=implementacion.token, step=step)
            _invalido(request, implementacion, step, edicion_form)
        accion = None
    elif request.method == "GET":
        editando = _empleado_a_editar(implementacion, request.GET.get("editar"))
        if editando:
            edicion_form = EmpleadoForm(instance=editando, implementacion=implementacion)

    if accion == "importar":
        import_form, errores_import = _importar_archivo_empleados(request, implementacion)
    elif accion == "agregar_manual":
        empleado_form = _agregar_empleado_manual(request, implementacion)
    elif accion == "eliminar":
        services.eliminar_empleado(implementacion, request.POST.get("empleado_id"), _actor(request))
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
            "editando": editando,
            "edicion_form": edicion_form if editando else None,
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
            acciones.registrar_validacion_fallida(
                _actor(request), implementacion, PASO_REVISION, {"pendientes": pendientes},
            )
        elif fecha_form.is_valid():
            acciones.enviar_relevamiento(
                _actor(request), implementacion, fecha_form.cleaned_data["fecha_salida_productivo"],
                base_url=request.build_absolute_uri("/"),
            )
            return redirect("onboarding:enviado", token=implementacion.token)
        else:
            _invalido(request, implementacion, PASO_REVISION, fecha_form)

    resumen = {
        "liquidaciones_activas": ", ".join(
            implementacion.liquidaciones.filter(activo=True).order_by("tipo_liquidacion__orden", "tipo_liquidacion__nombre").values_list("tipo_liquidacion__nombre", flat=True)
        ),
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
    PASO_DATOS: _step_empresa,
    PASO_MODULOS: _step_modulos,
    PASO_SUCURSALES: _step_sucursales,
    PASO_NOMINA: _step_empleados,
    PASO_ROLES: _step_roles,
    PASO_CONFIGURACION: _step_configuracion,
    PASO_LICENCIAS: _step_licencias_novedades,
    PASO_DOCUMENTOS: _step_documentos,
    PASO_REVISION: _step_revision,
}
